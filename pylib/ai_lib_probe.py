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
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

import ai_config
import ai_lib_github
from packaging.version import Version, InvalidVersion

# =============================================================================
# Constants
# =============================================================================

SCRIPT_DIR  = Path(__file__).parent

PROBE_CACHE_MAX_AGE_HOURS = 24
COMPAT_CACHE_MAX_AGE_DAYS = 7
SA_REPO    = "thu-ml/SageAttention"
FLASH_REPO = "Dao-AILab/flash-attention"

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


def _run_full(cmd: list[str], timeout: int = 15) -> tuple[int, str, str]:
    """Run a command, return (returncode, stdout, stderr). Returns (-1, '', err) on failure."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return -1, "", str(e)


def _parse_torch_tag(tag: str) -> str | None:
    """
    Parse compact torch tags from wheel filenames to version strings.
    'torch29' → '2.9',  'torch212' → '2.12',  'torch2120' → '2.12.0'
    Returns None if not parseable.
    """
    if not tag or not tag.startswith("torch"):
        return None
    digits = tag[5:]
    if not digits or not digits.isdigit() or len(digits) < 2:
        return None
    major = digits[0]
    rest  = digits[1:]
    if len(rest) == 1:
        return f"{major}.{rest}"
    # last digit '0' with 2+ remaining chars → minor=rest[:-1], patch=0
    if rest[-1] == "0" and len(rest) >= 2:
        return f"{major}.{int(rest[:-1])}.0"
    return f"{major}.{int(rest)}"


def _extract_torch_tag(wheel_name: str) -> str | None:
    """Extract the first 'torchNNN' substring from a wheel filename, or None."""
    m = re.search(r"(torch\d+)", wheel_name)
    return m.group(1) if m else None


def _extract_pkg_version(wheel_name: str) -> str | None:
    """Extract version from wheel filename: 'sageattention-2.2.0+...' → '2.2.0'."""
    m = re.match(r"[A-Za-z0-9_.\-]+-(\d+\.\d+\.\d+)", wheel_name)
    return m.group(1) if m else None


def _extract_abi_tag(wheel_name: str) -> str | None:
    """Extract python ABI tag from wheel filename: 'pkg-ver-cp312-cp312-...' → 'cp312'."""
    m = re.search(r"-(cp\d+)-cp\d+-", wheel_name)
    return m.group(1) if m else None


def _extract_cuda_local(wheel_name: str) -> str | None:
    """Extract cuda tag from wheel local version segment: '...+cu130...' → 'cu130'."""
    m = re.search(r"\+(cu\d+)", wheel_name)
    return m.group(1) if m else None


def _scan_wheels(wheels_dir: Path, pkg_prefix: str, abi: str) -> list[Path]:
    """Return .whl files matching pkg_prefix and abi tag in wheels_dir."""
    if not wheels_dir.is_dir():
        return []
    return [
        p for p in wheels_dir.iterdir()
        if p.suffix == ".whl"
        and p.name.lower().startswith(pkg_prefix.lower())
        and abi in p.name
    ]


def _probe_cache_is_fresh(cache: dict, current_driver: str) -> bool:
    """Return True if probe_cache is < 24h old and driver is unchanged."""
    ts = cache.get("torch_constraints_at")
    if not ts:
        return False
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(ts)
        if age > timedelta(hours=PROBE_CACHE_MAX_AGE_HOURS):
            return False
    except ValueError:
        return False
    if current_driver and cache.get("driver") != current_driver:
        return False
    return True


def _check_sa_venv(venv_python: Path) -> str:
    """
    Try importing sageattention in a venv python.
    Returns: 'ok' | 'not_installed' | 'broken_symbol' | 'broken_import' | 'venv_missing'
    """
    if not venv_python.exists():
        return "venv_missing"
    rc, out, err = _run_full(
        [str(venv_python), "-c", "import sageattention; print('ok')"], timeout=20
    )
    if rc == 0 and "ok" in out:
        return "ok"
    # Is it installed at all?
    _, pip_out, _ = _run_full(
        [str(venv_python), "-m", "pip", "show", "sageattention"], timeout=10
    )
    if "Name:" not in pip_out:
        return "not_installed"
    combined = (out + err).lower()
    if "undefined symbol" in combined:
        return "broken_symbol"
    return "broken_import"


def _sa_github_wheels(abi: str, cuda_tag: str) -> list[dict]:
    """
    Return list of {version, torch_str} for SA pre-built wheels matching abi
    and cuda_tag from GitHub releases. Returns [] on any error.
    """
    results = []
    try:
        releases = ai_lib_github.get_releases(SA_REPO, count=5)
        for rel in releases:
            for asset in rel.get("assets", []):
                name = asset.get("name", "")
                if (name.endswith(".whl")
                        and abi in name
                        and cuda_tag in name
                        and "sageattention" in name.lower()):
                    ver   = _extract_pkg_version(name)
                    torch = _parse_torch_tag(_extract_torch_tag(name))
                    if ver:
                        results.append({"version": ver, "torch_str": torch})
    except Exception as e:
        print(f"[probe] SA GitHub check failed: {e}", file=sys.stderr)
    return results


def _pypi_sa_latest() -> str | None:
    """Return the latest SageAttention version on PyPI, or None on error."""
    try:
        req = urllib.request.Request(
            "https://pypi.org/pypi/sageattention/json",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        return data.get("info", {}).get("version")
    except Exception:
        return None


def probe_sage_flash_torch(config: dict, probe: dict, target: str = "") -> dict:
    """
    Probe SageAttention and flash-attn availability for cp312 (ComfyUI).

    Checks (in order): probe_cache staleness, local wheel cache, GitHub releases,
    PyPI. Checks SA health in the ComfyUI venv if it is installed.

    Returns a probe_cache dict for writing to probe.probe_cache{} in JSON.
    Never raises — errors are absorbed and reflected in returned values.
    """
    current_driver = probe.get("gpu", {}).get("driver", "")
    torch_cuda     = probe.get("gpu", {}).get("torch_cuda", "")

    existing_cache = ai_config.load_all().get("probe", {}).get("probe_cache", {})
    if _probe_cache_is_fresh(existing_cache, current_driver):
        return existing_cache

    result: dict = {
        "torch_constraints_at": datetime.now(timezone.utc).isoformat(),
        "torch_cuda":           torch_cuda,
        "driver":               current_driver,
        "sage_max_torch":       None,
        "flash_max_torch":      None,
        "torch_candidate":      None,
        "stepdown_needed":      False,
        "stepdown_reason":      "",
        "sa_comfyui_status":    "unknown",
    }

    wheels_drive = config.get("wheels_drive", "/mnt/BACKUP_4.0_TB")
    cp312_dir    = Path(wheels_drive) / "AI_Collected_Wheels" / "localbuild" / "cp312"
    abi          = "cp312"

    # ── Wheel cache: flash_attn ───────────────────────────────────────────────
    flash_max: str | None = None
    for w in _scan_wheels(cp312_dir, "flash_attn", abi):
        torch_str = _parse_torch_tag(_extract_torch_tag(w.name))
        if torch_str and (flash_max is None
                          or _ver(torch_str) > _ver(flash_max)):
            flash_max = torch_str
    result["flash_max_torch"] = flash_max

    # ── Wheel cache: sageattention ────────────────────────────────────────────
    cache_sa_torch: str | None = None
    for w in _scan_wheels(cp312_dir, "sageattention", abi):
        torch_str = _parse_torch_tag(_extract_torch_tag(w.name))
        if torch_str and (cache_sa_torch is None
                          or _ver(torch_str) > _ver(cache_sa_torch)):
            cache_sa_torch = torch_str

    # ── GitHub releases: sageattention ───────────────────────────────────────
    gh_sa_torch: str | None = None
    if torch_cuda:
        gh_wheels = _sa_github_wheels(abi, torch_cuda)
        if gh_wheels:
            # pick the entry with the highest torch_str
            for entry in gh_wheels:
                ts = entry.get("torch_str")
                if ts and (gh_sa_torch is None or _ver(ts) > _ver(gh_sa_torch)):
                    gh_sa_torch = ts

    # ── PyPI: note latest SA version (informational) ─────────────────────────
    pypi_latest = _pypi_sa_latest()
    if pypi_latest:
        result["sage_pypi_latest"] = pypi_latest

    # Best sage_max_torch: prefer GitHub pre-built (has explicit torch tag),
    # then wheel cache, then None (can't determine)
    sage_max = gh_sa_torch or cache_sa_torch
    result["sage_max_torch"] = sage_max

    # ── torch_candidate and stepdown_needed ──────────────────────────────────
    constraints: list[tuple[str, str]] = []
    if flash_max:
        constraints.append(("flash_attn", flash_max))
    if sage_max:
        constraints.append(("sageattention", sage_max))

    if constraints:
        try:
            min_pkg, min_ver = min(constraints, key=lambda x: _ver(x[1]))
            result["torch_candidate"] = min_ver
            result["stepdown_needed"] = True
            result["stepdown_reason"] = "; ".join(
                f"{pkg} wheel requires torch ≤ {ver}" for pkg, ver in constraints
            )
        except (InvalidVersion, ValueError):
            pass

    # ── SA venv health in ComfyUI ────────────────────────────────────────────
    active_target = target or config.get("active_target", "")
    apps_subdir   = config.get("apps_subdir", "AI_Apps")
    if active_target:
        venv_py = (Path(active_target) / apps_subdir
                   / "ComfyUI" / "venv" / "bin" / "python")
        result["sa_comfyui_status"] = _check_sa_venv(venv_py)

    return result


def _ver(version_str: str) -> Version:
    """Parse version string; returns Version('0') on parse failure."""
    try:
        return Version(version_str)
    except InvalidVersion:
        return Version("0")


def best_drive(drives: list[dict]) -> str | None:
    """
    Return the single unambiguous install target, or None if ambiguous.
    Only returns a value if exactly one drive has existing AI dirs.
    """
    with_ai = [d for d in drives if d["has_ai"]]
    if len(with_ai) == 1:
        return with_ai[0]["mount"]
    return None     # ambiguous or none — conductor will prompt


def _compat_cache_is_fresh(cache: dict) -> bool:
    """Return True if compat_cache is less than COMPAT_CACHE_MAX_AGE_DAYS old."""
    ts = cache.get("fetched_at")
    if not ts:
        return False
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(ts)
        return age < timedelta(days=COMPAT_CACHE_MAX_AGE_DAYS)
    except ValueError:
        return False


def _pip_dry_run(venv_python: Path, packages: list[str],
                 extra_index: str = "") -> dict:
    """
    Run pip install --dry-run via a temp-file report.
    Returns {resolved_at, packages: {name: version}} or {error: str}.
    Uses a temp file to avoid stdout contamination from pip progress output.
    """
    report_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            report_path = f.name
        cmd = [str(venv_python), "-m", "pip", "install",
               "--dry-run", f"--report={report_path}", "-q"] + packages
        if extra_index:
            cmd += ["--extra-index-url", extra_index]
        rc, _, err_out = _run_full(cmd, timeout=120)
        if rc != 0:
            return {"error": (err_out or "pip dry-run failed")[:300]}
        with open(report_path) as fh:
            parsed = json.loads(fh.read())
        pkgs: dict[str, str] = {}
        for item in parsed.get("install", []):
            meta = item.get("metadata", {})
            name = (meta.get("name") or "").lower().replace("-", "_")
            ver  = meta.get("version") or ""
            if name and ver:
                pkgs[name] = ver
        return {
            "resolved_at": datetime.now(timezone.utc).isoformat(),
            "packages":    pkgs,
        }
    except Exception as e:
        return {"error": str(e)[:300]}
    finally:
        if report_path:
            Path(report_path).unlink(missing_ok=True)


def fetch_compat_data(config: dict, probe: dict) -> dict:
    """
    Fetch SA and flash-attn compatibility data from GitHub releases.
    Runs pip dry-runs for key ComfyUI install scenarios.

    Returns a compat_cache dict for writing via ai_config.write_compat_cache().
    Non-fatal throughout — errors are absorbed and reflected in partial results.
    Staleness check (7 days) is the caller's responsibility.
    """
    torch_cuda  = probe.get("gpu", {}).get("torch_cuda", "cu130")
    torch_index = probe.get("gpu", {}).get(
        "torch_index", f"https://download.pytorch.org/whl/{torch_cuda}"
    )

    result: dict = {
        "fetched_at":  datetime.now(timezone.utc).isoformat(),
        "available":   {"sageattention": {}, "flash_attn": {}},
        "pip_dry_runs": {},
    }

    # ── SA versions from GitHub releases ─────────────────────────────────────
    try:
        releases = ai_lib_github.get_releases(SA_REPO, count=10)
        for rel in releases:
            tag = rel.get("tag_name", "").lstrip("v")
            if not tag:
                continue
            pre_built: list[str] = []
            max_torch_sa: str | None = None
            for asset in rel.get("assets", []):
                name = asset.get("name", "")
                if not (name.endswith(".whl") and "sageattention" in name.lower()):
                    continue
                abi  = _extract_abi_tag(name)
                cuda = _extract_cuda_local(name)
                if abi and cuda:
                    pre_built.append(f"{abi}+{cuda}")
                ts = _parse_torch_tag(_extract_torch_tag(name))
                if ts and (max_torch_sa is None or _ver(ts) > _ver(max_torch_sa)):
                    max_torch_sa = ts
            result["available"]["sageattention"][tag] = {
                "max_torch": max_torch_sa,
                "pre_built": list(dict.fromkeys(pre_built)),
            }
    except Exception as e:
        print(f"[probe] fetch_compat_data SA releases failed: {e}", file=sys.stderr)

    # ── SA versions from GitHub tags — check local cache for tag-based wheels ─
    # SA distributed tag-based wheels (e.g. 2.2.0) as local assets, not GitHub
    # release assets, so get_release_by_tag returns 404. Use local wheel cache
    # instead — what we have tells us what exists and what ABI/cuda it targets.
    try:
        wheels_drive = config.get("wheels_drive", "/mnt/BACKUP_4.0_TB")
        localbuild   = Path(wheels_drive) / "AI_Collected_Wheels" / "localbuild"
        abi_dirs: list[Path] = (
            [d for d in localbuild.iterdir() if d.is_dir() and d.name.startswith("cp")]
            if localbuild.is_dir() else []
        )
        tags = ai_lib_github.get_tags(SA_REPO, count=20)
        for tag_obj in tags:
            raw_tag = tag_obj.get("name", "")
            ver = raw_tag.lstrip("v")
            if not ver or ver in result["available"]["sageattention"]:
                continue
            pre_built = []
            max_torch_sa = None
            for abi_dir in abi_dirs:
                for w in _scan_wheels(abi_dir, "sageattention", ""):
                    if ver not in w.name:
                        continue
                    abi  = _extract_abi_tag(w.name)
                    cuda = _extract_cuda_local(w.name)
                    if abi and cuda:
                        pre_built.append(f"{abi}+{cuda}")
                    ts = _parse_torch_tag(_extract_torch_tag(w.name))
                    if ts and (max_torch_sa is None or _ver(ts) > _ver(max_torch_sa)):
                        max_torch_sa = ts
            result["available"]["sageattention"][ver] = {
                "max_torch": max_torch_sa,
                "pre_built": list(dict.fromkeys(pre_built)),
            }
    except Exception as e:
        print(f"[probe] fetch_compat_data SA tags failed: {e}", file=sys.stderr)

    # ── flash-attn versions from GitHub (2.x series only) ────────────────────
    try:
        releases = ai_lib_github.get_releases(FLASH_REPO, count=25)
        for rel in releases:
            raw_tag = rel.get("tag_name", "")
            if not raw_tag.startswith("v2."):
                continue
            tag = raw_tag.lstrip("v")
            pre_built = []
            for asset in rel.get("assets", []):
                name = asset.get("name", "")
                if not (name.endswith(".whl") and "flash_attn" in name.lower()):
                    continue
                abi  = _extract_abi_tag(name)
                cuda = _extract_cuda_local(name)
                if abi and cuda:
                    pre_built.append(f"{abi}+{cuda}")
            result["available"]["flash_attn"][tag] = {
                "max_torch": None,
                "pre_built": list(dict.fromkeys(pre_built)),
            }
    except Exception as e:
        print(f"[probe] fetch_compat_data flash-attn GitHub failed: {e}", file=sys.stderr)

    # ── pip dry-runs for ComfyUI ──────────────────────────────────────────────
    active_target = config.get("active_target", "")
    apps_subdir   = config.get("apps_subdir", "AI_Apps")
    if active_target:
        venv_py = (Path(active_target) / apps_subdir
                   / "ComfyUI" / "venv" / "bin" / "python")
        if venv_py.exists():
            # SA local wheel + downgrade torch to 2.7.1
            # SA 2.2.0 is not on PyPI — use local cached wheel if available
            wheels_drive = config.get("wheels_drive", "/mnt/BACKUP_4.0_TB")
            cp312_dir    = (Path(wheels_drive)
                            / "AI_Collected_Wheels" / "localbuild" / "cp312")
            sa_wheels    = _scan_wheels(cp312_dir, "sageattention", "cp312")
            if sa_wheels:
                result["pip_dry_runs"]["comfyui:sa220_torch271"] = _pip_dry_run(
                    venv_py,
                    [str(sa_wheels[0]), f"torch==2.7.1+{torch_cuda}",
                     "--no-build-isolation"],
                    extra_index=torch_index,
                )
            else:
                result["pip_dry_runs"]["comfyui:sa220_torch271"] = {
                    "skipped": "no local SA wheel for cp312"
                }
            # SA latest with current torch (source build attempt)
            result["pip_dry_runs"]["comfyui:keep_current_torch"] = _pip_dry_run(
                venv_py,
                ["sageattention", "--no-build-isolation"],
            )

    return result


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
