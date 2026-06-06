#!/usr/bin/env python3
# =============================================================================
# ai_lib_probe.py  —  System probe for the Jethro AI stack
# =============================================================================
# Called by ai_installer.py at startup. Probes GPU, driver, CUDA capability,
# tools, OS, and mounted drives. Returns a dict — ai_installer.py owns the
# JSON write (under the key "probe"). Reads the JSON path from the
# AI_INSTALLER_JSON env var or defaults to <script_dir>/ai_installer.json.
#
# Requires: packaging>=21.0  (Debian 13 system Python — no venv needed)
# If missing: pip install --break-system-packages packaging
#
# Usage:
#   python3 ai_lib_probe.py              # probe and write to JSON
#   python3 ai_lib_probe.py --dry-run    # probe but print result, do not write
#   python3 ai_lib_probe.py --help       # show this help
#
# JSON section written: ai_installer.json["probe"]
# Python calling pattern:
#   import ai_lib_probe
#   probe = ai_lib_probe.run()
#   # ai_installer.py then writes probe to JSON under key "probe"
# =============================================================================

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import ai_config

# =============================================================================
# Constants
# =============================================================================

SCRIPT_DIR  = Path(__file__).parent

# Driver major → (cuda_max string, torch cuda tag)
# Ordered from highest to lowest. First match wins.
DRIVER_CUDA_MAP = [
    (570, "13.0", "cu130"),
    (545, "12.6", "cu126"),
    (525, "12.4", "cu124"),
    (520, "12.0", "cu121"),
    (510, "11.8", "cu118"),
]
CUDA_FALLBACK = ("11.x", "cu118")

# =============================================================================
# Probe functions
# =============================================================================

def _run(cmd: list[str], timeout: int = 10) -> str:
    """Run a command, return stdout stripped. Returns '' on any failure."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def probe_gpu() -> dict:
    """
    Query nvidia-smi for GPU name, VRAM, and driver version.
    Derives max CUDA version and torch cuda tag from driver major version.
    Returns null values if nvidia-smi is unavailable.
    """
    raw = _run([
        "nvidia-smi",
        "--query-gpu=name,memory.total,driver_version",
        "--format=csv,noheader,nounits"
    ])

    if not raw:
        print("[probe] WARNING: nvidia-smi not available — GPU info will be null", file=sys.stderr)
        return {
            "name":         None,
            "vram_gb":      None,
            "driver":       None,
            "driver_major": None,
            "cuda_max":     None,
            "torch_cuda":   None,
            "torch_index":  None,
            "sage_v2_capable": False,
        }

    parts = [p.strip() for p in raw.split(",")]
    name       = parts[0] if len(parts) > 0 else None
    vram_mb    = parts[1] if len(parts) > 1 else "0"
    driver_ver = parts[2] if len(parts) > 2 else "0.0.0"

    try:
        vram_gb = round(int(vram_mb) / 1024)
    except ValueError:
        vram_gb = 0

    try:
        driver_major = int(driver_ver.split(".")[0])
    except (ValueError, IndexError):
        driver_major = 0

    cuda_max, torch_cuda = CUDA_FALLBACK
    for min_driver, cuda_ver, cuda_tag in DRIVER_CUDA_MAP:
        if driver_major >= min_driver:
            cuda_max   = cuda_ver
            torch_cuda = cuda_tag
            break

    sage_v2_capable = driver_major >= 570

    return {
        "name":            name,
        "vram_gb":         vram_gb,
        "driver":          driver_ver,
        "driver_major":    driver_major,
        "cuda_max":        cuda_max,
        "torch_cuda":      torch_cuda,
        "torch_index":     f"https://download.pytorch.org/whl/{torch_cuda}",
        "sage_v2_capable": sage_v2_capable,
    }


def probe_tools() -> dict:
    """
    Check for required and optional build tools.
    nvcc version is extracted from nvcc --version output if present.
    """
    nvcc_path = shutil.which("nvcc")
    nvcc_ver  = None
    if nvcc_path:
        raw = _run(["nvcc", "--version"])
        # "release 12.3, V12.3.52" → "12.3"
        for part in raw.split():
            if part.startswith("V") and "." in part:
                nvcc_ver = part[1:].split(",")[0]
                break
        if not nvcc_ver:
            # fallback: find "release X.Y" pattern
            import re
            m = re.search(r"release\s+(\d+\.\d+)", raw)
            nvcc_ver = m.group(1) if m else "unknown"

    pyenv_root = Path(os.environ.get("PYENV_ROOT", Path.home() / ".pyenv"))

    return {
        "nvcc":         nvcc_ver,              # str version or null
        "nvcc_path":    nvcc_path,             # full path or null
        "gcc12":        shutil.which("gcc-12") is not None,
        "git":          shutil.which("git")    is not None,
        "jq":           shutil.which("jq")     is not None,
        "pyenv":        pyenv_root.exists(),
        "pyenv_root":   str(pyenv_root),
    }


def probe_os() -> dict:
    """Read OS/distribution information."""
    debian = None
    debian_path = Path("/etc/debian_version")
    if debian_path.exists():
        try:
            debian = debian_path.read_text().strip()
        except OSError:
            pass

    hostname = None
    try:
        import socket
        hostname = socket.gethostname()
    except OSError:
        pass

    return {
        "debian":   debian,
        "hostname": hostname,
    }


# Filesystems that support hardlinks — required for the resource sharing model
HARDLINK_CAPABLE_FS = {"ext4", "ext3", "ext2", "btrfs", "xfs", "zfs", "f2fs", "reiserfs", "jfs"}

# Mount path prefixes that are never valid install targets
SYSTEM_MOUNT_PREFIXES = (
    "/boot", "/efi", "/sys", "/proc", "/dev",
    "/run", "/snap", "/tmp",
)


def _fs_type(mount: str) -> str:
    """Return filesystem type for mount point, or empty string on failure."""
    result = _run(["findmnt", "-n", "-o", "FSTYPE", "--target", mount])
    return result.strip().lower()


def _fs_supports_hardlinks(mount: str) -> bool:
    """Return True if the filesystem at mount supports hardlinks."""
    return _fs_type(mount) in HARDLINK_CAPABLE_FS


def probe_drives() -> list[dict]:
    """
    Return mounted filesystems that are valid install targets.

    Uses findmnt for a single authoritative call covering mount point,
    filesystem type, size, and available space. Filters to /mnt/* mounts
    that support hardlinks (ext4/btrfs/xfs/zfs etc).

    Each entry includes has_ai (existing AI dirs found) and fs_type.
    Sorted: drives with AI dirs first, then alphabetically.
    """
    raw_findmnt = _run([
        "findmnt", "-ln",
        "-o", "TARGET,FSTYPE",
    ])

    drives = []

    for line in raw_findmnt.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        mount  = parts[0]
        fstype = parts[1].lower()

        # Must be under /mnt/
        if not mount.startswith("/mnt"):
            continue

        # Skip system/boot/efi mounts
        if any(mount.startswith(p) for p in SYSTEM_MOUNT_PREFIXES):
            continue

        # Skip network shares
        if mount.startswith("//") or ":" in mount:
            continue

        # Must support hardlinks — silently skip FAT/exFAT/NTFS/etc
        if fstype not in HARDLINK_CAPABLE_FS:
            continue

        # Check for existing AI directories (permission-safe)
        has_ai = False
        for _d in ("AI_Apps", "AI-Shared-Resources", "AI_Outputs"):
            try:
                if Path(mount, _d).is_dir():
                    has_ai = True
                    break
            except (PermissionError, OSError):
                pass

        drives.append({
            "mount":   mount,
            "has_ai":  has_ai,
            "fs_type": fstype,
        })

    # Sort: drives with AI dirs first, then alphabetically by mount
    drives.sort(key=lambda d: (0 if d["has_ai"] else 1, d["mount"]))
    return drives


def best_drive(drives: list[dict]) -> str | None:
    """
    Return the single unambiguous install target, or None if ambiguous.
    Only returns a value if exactly one drive has existing AI dirs.
    """
    with_ai = [d for d in drives if d["has_ai"]]
    if len(with_ai) == 1:
        return with_ai[0]["mount"]
    return None     # ambiguous or none — conductor will prompt

# =============================================================================
# Main
# =============================================================================

def run() -> dict:
    """Run all probe functions and return the combined result dict."""
    gpu    = probe_gpu()
    tools  = probe_tools()
    os_    = probe_os()
    drives = probe_drives()

    return {
        "probed_at": datetime.now(timezone.utc).isoformat(),
        "gpu":       gpu,
        "tools":     tools,
        "os":        os_,
        "drives":    drives,
        "best_drive": best_drive(drives),
    }


def main() -> None:
    if "--help" in sys.argv:
        print(__doc__)
        sys.exit(0)

    dry_run = "--dry-run" in sys.argv

    print("[probe] Probing system...", file=sys.stderr)
    try:
        result = run()
    except Exception as e:
        print(f"[probe] FATAL: probe failed: {e}", file=sys.stderr)
        sys.exit(1)

    gpu = result["gpu"]
    if gpu["name"]:
        print(
            f"[probe] {gpu['name']} | driver {gpu['driver']} "
            f"| {gpu['torch_cuda']} | sage_v2={gpu['sage_v2_capable']}",
            file=sys.stderr
        )
    else:
        print("[probe] No GPU detected", file=sys.stderr)

    if dry_run:
        print(json.dumps({"probe": result}, indent=2))
        sys.exit(0)

    ok = ai_config.write_probe(result)
    if ok:
        print("[probe] Written to ai_installer.json", file=sys.stderr)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
