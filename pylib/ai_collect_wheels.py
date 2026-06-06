#!/usr/bin/env python3
# =============================================================================
# ai_collect_wheels.py  —  Pack installed heavy packages into localbuild/ cache
# =============================================================================
# Scans a venv's site-packages for heavy compiled packages (flash_attn,
# sageattention, nunchaku) and packs them into correctly-named wheels in
# AI_Collected_Wheels/localbuild/.
#
# Naming convention (our own builds):
#   flash_attn-2.8.3+cu130.torch212-cp311-cp311-linux_x86_64.whl
#
# Called automatically by ai_installer.py after a successful source build.
# Also runnable standalone for manual wheel caching.
#
# Usage:
#   python3 ai_collect_wheels.py --venv /mnt/1TB_SSD/AI_Apps/FramePack/venv
#   python3 ai_collect_wheels.py --venv /path/to/venv --pkg flash_attn
#   python3 ai_collect_wheels.py --venv /path/to/venv --list
#
# Requires: no third-party packages — stdlib only
# =============================================================================

import re
import sys
import zipfile
import argparse
import subprocess
from pathlib import Path

# ---------------------------------------------------------------------------
# Heavy packages we care about
# ---------------------------------------------------------------------------
# Import here so we share the registry with ai_lib_wheels
try:
    from ai_lib_wheels import HEAVY_PACKAGES, localbuild_dir
except ImportError:
    # Standalone fallback — minimal registry
    HEAVY_PACKAGES = {
        "flash_attn":    {"cuda_in_name": True, "torch_in_name": True},
        "sageattention": {"cuda_in_name": True, "torch_in_name": False},
        "nunchaku":      {"cuda_in_name": True, "torch_in_name": True},
        "torch":       {"cuda_in_name": True,  "torch_in_name": False},  # 800MB
        "torchvision": {"cuda_in_name": True,  "torch_in_name": False},  # ~7MB
        "torchaudio":  {"cuda_in_name": True,  "torch_in_name": False},  # ~5MB
    }
    def localbuild_dir() -> Path:
        return Path("/mnt/BACKUP_4.0_TB/AI_Collected_Wheels/localbuild")

# Large pip packages worth caching — py3-none, reusable across Python versions.
# No cuda/torch tag embedded in wheel name — just version + platform.
LARGE_PIP_PACKAGES = {
    # NVIDIA CUDA toolkit — py3-none, identical across Python versions
    "nvidia_cublas":            {"cuda_in_name": False, "torch_in_name": False},  # 423MB
    "nvidia_cudnn_cu13":        {"cuda_in_name": False, "torch_in_name": False},  # 366MB
    "nvidia_nccl_cu13":         {"cuda_in_name": False, "torch_in_name": False},  # 206MB
    "nvidia_cufft":             {"cuda_in_name": False, "torch_in_name": False},  # 214MB
    "nvidia_cusolver":          {"cuda_in_name": False, "torch_in_name": False},  # 201MB
    "nvidia_cusparse":          {"cuda_in_name": False, "torch_in_name": False},  # 146MB
    "nvidia_cuda_nvrtc":        {"cuda_in_name": False, "torch_in_name": False},  # 90MB
    "nvidia_cusparselt_cu13":   {"cuda_in_name": False, "torch_in_name": False},  # 170MB
    "nvidia_nvshmem_cu13":      {"cuda_in_name": False, "torch_in_name": False},  # 60MB
    "nvidia_curand":            {"cuda_in_name": False, "torch_in_name": False},  # 60MB
    "nvidia_nvjitlink":         {"cuda_in_name": False, "torch_in_name": False},  # 41MB
    # ML/compute — large, slow to download
    "triton":                   {"cuda_in_name": False, "torch_in_name": False},  # 201MB
    "onnxruntime_gpu":          {"cuda_in_name": False, "torch_in_name": False},  # 188MB
    "taichi":                   {"cuda_in_name": False, "torch_in_name": False},  # 56MB
    "llvmlite":                 {"cuda_in_name": False, "torch_in_name": False},  # 56MB
    # Computer vision — abi3, cross-Python-version
    "opencv_python":            {"cuda_in_name": False, "torch_in_name": False},  # 73MB
    "opencv_python_headless":   {"cuda_in_name": False, "torch_in_name": False},  # 60MB
    # Other large packages
    "gradio":                   {"cuda_in_name": False, "torch_in_name": False},  # 54MB
    "scipy":                    {"cuda_in_name": False, "torch_in_name": False},  # 35MB
    "xformers": {"cuda_in_name": False, "torch_in_name": False},  # cu121 build for A1111
}


# ---------------------------------------------------------------------------
# Venv introspection
# ---------------------------------------------------------------------------

def _venv_python(venv_dir: Path) -> Path | None:
    for candidate in ("bin/python", "bin/python3", ".venv/bin/python"):
        p = venv_dir / candidate
        if p.exists():
            return p
    return None


def _venv_site_packages(venv_dir: Path) -> Path | None:
    """Find site-packages directory inside a venv."""
    # Standard layout: lib/pythonX.Y/site-packages
    lib = venv_dir / "lib"
    if not lib.exists():
        # InvokeAI uses .venv/
        lib = venv_dir / ".venv" / "lib"
    if not lib.exists():
        return None
    for pydir in lib.iterdir():
        sp = pydir / "site-packages"
        if sp.exists():
            return sp
    return None


def _python_tag(venv_dir: Path) -> str | None:
    """Return cpXYZ tag from venv python, e.g. 'cp311'."""
    python = _venv_python(venv_dir)
    if not python:
        return None
    try:
        out = subprocess.check_output(
            [str(python), "-c",
             "import sys; print(f'cp{sys.version_info.major}{sys.version_info.minor}')"],
            stderr=subprocess.DEVNULL, text=True
        ).strip()
        return out if out.startswith("cp") else None
    except Exception:
        return None


def _torch_version(venv_dir: Path) -> str | None:
    """
    Return torch version string from venv, e.g. '2.12.0+cu130'.
    Returns None if torch not installed.
    """
    python = _venv_python(venv_dir)
    if not python:
        return None
    try:
        out = subprocess.check_output(
            [str(python), "-c", "import torch; print(torch.__version__)"],
            stderr=subprocess.DEVNULL, text=True
        ).strip()
        return out if out else None
    except Exception:
        return None


def _parse_torch_tags(torch_full: str) -> tuple[str, str]:
    """
    Parse '2.12.0+cu130' into (torch_tag, cuda_tag).
    torch_tag: '212'  (major+minor, no dots — for embedding in filename)
    cuda_tag:  'cu130'
    Returns ('', '') if unparseable.
    """
    # Torch version: X.Y.Z or X.Y.Z+cuNNN
    m = re.match(r'(\d+)\.(\d+)(?:\.\d+)?(?:\+cu(\d+))?', torch_full)
    if not m:
        return "", ""
    major, minor = m.group(1), m.group(2)
    cuda_digits  = m.group(3) or ""
    torch_tag    = f"{major}{minor}"         # "212"
    cuda_tag     = f"cu{cuda_digits}" if cuda_digits else ""
    return torch_tag, cuda_tag


# ---------------------------------------------------------------------------
# Wheel building from dist-info
# ---------------------------------------------------------------------------

def _find_dist_info(site_packages: Path, pkg: str) -> Path | None:
    """
    Find the .dist-info directory for a package.
    Handles both flash_attn and flash-attn style names, and local version
    tags in dist-info names (e.g. sageattention-2.2.0+cu13.dist-info).
    """
    normalised = pkg.replace("-", "_").lower()
    for di in site_packages.iterdir():
        if not di.is_dir() or not di.name.endswith(".dist-info"):
            continue
        # Strip .dist-info suffix
        base = di.name.replace(".dist-info", "")        # "sageattention-2.2.0+cu13"
        # Strip local version tag (+cu13 etc) before splitting
        base_no_local = base.split("+")[0]              # "sageattention-2.2.0"
        dist_name = base_no_local.rsplit("-", 1)[0].replace("-", "_").lower()
        if dist_name == normalised:
            return di
    return None


def _dist_info_version(dist_info: Path) -> str:
    """
    Extract version from dist-info directory name: PackageName-VERSION.dist-info
    Strips local version tag (+cu13 etc) so version is clean for wheel naming.
    e.g. sageattention-2.2.0+cu13.dist-info → "2.2.0" (not "2.2.0+cu13")
    """
    raw = dist_info.name.replace(".dist-info", "").rsplit("-", 1)[-1]
    return raw.split("+")[0]   # strip +cu13 etc


def _read_wheel_tags(dist_info: Path) -> tuple[str, str, str] | None:
    """
    Read the WHEEL metadata file from a dist-info directory and return
    (python_tag, abi_tag, platform_tag) from the first Tag: line found.

    Returns None if WHEEL file is missing or unparseable.

    Examples:
      Tag: cp311-cp311-linux_x86_64   → ('cp311', 'cp311', 'linux_x86_64')
      Tag: py3-none-manylinux2014_x86_64 → ('py3', 'none', 'manylinux2014_x86_64')
    """
    wheel_meta = dist_info / "WHEEL"
    if not wheel_meta.exists():
        return None
    for line in wheel_meta.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("Tag:"):
            parts = line.split(":", 1)[1].strip().split("-")
            if len(parts) == 3:
                return parts[0], parts[1], parts[2]
    return None


def _build_wheel_name(pkg: str, version: str, torch_tag: str, cuda_tag: str,
                       python_tag: str, abi_tag: str | None = None,
                       platform_tag: str | None = None) -> str:
    """
    Construct our canonical localbuild wheel filename.

    Convention (cpython package):
      flash_attn-2.8.3+cu130.torch212-cp311-cp311-linux_x86_64.whl

    Convention (py3-none package, e.g. nvidia cuda libs):
      nvidia_cublas-13.1.1.3-py3-none-manylinux2014_x86_64.whl

    Local version label (after +):
      - cuda tag always included if cuda_in_name
      - torch tag included if torch_in_name, separated by dot

    abi_tag / platform_tag: override the default cpython tags when the
    installed WHEEL metadata shows py3-none-* (i.e. not Python-version-locked).
    """
    pkg_info = HEAVY_PACKAGES.get(pkg, {})
    normalised_pkg = pkg.replace("-", "_")

    local_parts = []
    if pkg_info.get("cuda_in_name") and cuda_tag:
        local_parts.append(cuda_tag)
    if pkg_info.get("torch_in_name") and torch_tag:
        local_parts.append(f"torch{torch_tag}")

    local_label = ("+" + ".".join(local_parts)) if local_parts else ""

    _abi      = abi_tag      if abi_tag      else python_tag
    _platform = platform_tag if platform_tag else "linux_x86_64"

    return (f"{normalised_pkg}-{version}{local_label}"
            f"-{python_tag}-{_abi}-{_platform}.whl")


def _pack_wheel(dist_info: Path, site_packages: Path, dest: Path) -> bool:
    """
    Pack a wheel from a dist-info directory.
    Reads RECORD to find all files belonging to the package.
    Returns True on success.
    """
    record_path = dist_info / "RECORD"
    if not record_path.exists():
        print(f"  ERROR: no RECORD in {dist_info}", file=sys.stderr)
        return False

    record_lines = record_path.read_text(encoding="utf-8", errors="replace").splitlines()
    files_to_pack = []
    missing = []
    seen_arcnames = set()   # deduplicate — RECORD sometimes lists __pycache__ twice

    for line in record_lines:
        if not line.strip():
            continue
        filepath = line.split(",")[0].strip()
        if filepath in seen_arcnames:
            continue
        seen_arcnames.add(filepath)
        # RECORD paths are relative to site-packages
        src = site_packages / filepath
        if src.exists():
            files_to_pack.append((src, filepath))
        else:
            missing.append(filepath)

    if missing:
        print(f"  WARN: {len(missing)} RECORD entries not found on disk (skipping):")
        for m in missing[:5]:
            print(f"    {m}")
        if len(missing) > 5:
            print(f"    ... and {len(missing) - 5} more")

    if not files_to_pack:
        print(f"  ERROR: no files to pack for {dist_info.name}", file=sys.stderr)
        return False

    print(f"  Packing {len(files_to_pack)} files...")
    try:
        tmp = dest.with_suffix(".tmp.whl")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for src, arcname in files_to_pack:
                zf.write(src, arcname)
        tmp.rename(dest)
        return True
    except Exception as e:
        print(f"  ERROR: zip failed: {e}", file=sys.stderr)
        tmp.unlink(missing_ok=True)
        return False


# ---------------------------------------------------------------------------
# Main collection logic
# ---------------------------------------------------------------------------

def collect_package(pkg: str, venv_dir: Path,
                    python_tag: str, torch_tag: str, cuda_tag: str,
                    verbose: bool = True) -> bool:
    """
    Find, name, and pack one heavy package from a venv into localbuild/.
    Returns True if wheel was created or already exists.

    verbose=False suppresses SKIP lines (already-cached packages).
    Errors, warnings, and new packs always print regardless.
    """
    site_packages = _venv_site_packages(venv_dir)
    if not site_packages:
        print(f"  ERROR: could not find site-packages in {venv_dir}", file=sys.stderr)
        return False

    dist_info = _find_dist_info(site_packages, pkg)
    if not dist_info:
        if verbose:
            print(f"  SKIP: {pkg} not installed in {venv_dir}")
        return False

    version = _dist_info_version(dist_info)

    # Read installed WHEEL metadata to check actual tag — nvidia and similar
    # packages are py3-none-manylinux*: identical content across Python versions.
    # Use the real tags so we store one copy instead of one per Python version.
    abi_tag = platform_tag = None
    wheel_tags = _read_wheel_tags(dist_info)
    if wheel_tags:
        whl_py, whl_abi, whl_plat = wheel_tags
        if whl_py == "py3" and whl_abi == "none":
            # py3-none package — override cpython tags
            abi_tag      = "none"
            platform_tag = whl_plat   # e.g. manylinux2014_x86_64
            python_tag   = "py3"
            if verbose:
                print(f"  (py3-none detected → {python_tag}-{abi_tag}-{platform_tag})")

    whl_name  = _build_wheel_name(pkg, version, torch_tag, cuda_tag, python_tag,
                                   abi_tag, platform_tag)
    out_dir = localbuild_dir()
    # ABI-specific wheels go into cpXXX subdir; py3-none wheels stay in root
    if python_tag.startswith("cp"):
        out_dir = out_dir / python_tag
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path  = out_dir / whl_name

    if out_path.exists():
        if verbose:
            size_mb = out_path.stat().st_size // 1024**2
            print(f"  SKIP: {whl_name} already in localbuild/ ({size_mb}MB)")
        return True

    print(f"  Packing {pkg}=={version} → {whl_name}")
    ok = _pack_wheel(dist_info, site_packages, out_path)
    if ok:
        size_mb = out_path.stat().st_size // 1024**2
        print(f"  OK: {whl_name} ({size_mb}MB)")
    return ok


def collect_from_venv(venv_dir: Path, packages: list[str] | None = None,
                      verbose: bool = True) -> dict:
    """
    Collect all heavy packages from a venv into localbuild/.
    Returns dict of {pkg: True/False} for each package attempted.

    Args:
        venv_dir:  Path to venv root
        packages:  list of package names to collect, or None for all HEAVY_PACKAGES
        verbose:   if False, suppresses SKIP lines for already-cached packages.
                   Pass False when called from ai_installer.py to keep logs clean.
                   Errors, warnings, and new packs always print.
    """
    results = {}

    # Introspect venv
    python_tag = _python_tag(venv_dir)
    if not python_tag:
        print(f"ERROR: could not determine Python version from {venv_dir}",
              file=sys.stderr)
        return {}

    torch_full = _torch_version(venv_dir)
    if torch_full:
        torch_tag, cuda_tag = _parse_torch_tags(torch_full)
        print(f"  venv: {python_tag}  torch={torch_full}  → torch{torch_tag}  {cuda_tag}")
    else:
        torch_tag, cuda_tag = "", ""
        print(f"  venv: {python_tag}  (torch not installed)")

    pkg_list = packages if packages else (
        list(HEAVY_PACKAGES.keys()) + list(LARGE_PIP_PACKAGES.keys())
    )

    _all_pkgs = {**HEAVY_PACKAGES, **LARGE_PIP_PACKAGES}
    for pkg in pkg_list:
        if verbose:
            print(f"\n  [{pkg}]")
        pkg_info = _all_pkgs.get(pkg, {})
        _cuda  = cuda_tag  if pkg_info.get("cuda_in_name")  else ""
        _torch = torch_tag if pkg_info.get("torch_in_name") else ""
        ok = collect_package(pkg, venv_dir, python_tag, _torch, _cuda, verbose=verbose)
        results[pkg] = ok

    return results


# ---------------------------------------------------------------------------
# Auto-collection — scans entire venv, uses direct_url.json as priority signal
# ---------------------------------------------------------------------------

def _installed_size_mb(dist_info: Path, site_packages: Path) -> float:
    """Sum size of all files listed in RECORD for this package."""
    record = dist_info / "RECORD"
    if not record.exists():
        return 0.0
    total = 0
    for line in record.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        filepath = line.split(",")[0].strip()
        src = site_packages / filepath
        try:
            if src.exists():
                total += src.stat().st_size
        except OSError:
            pass
    return total / 1024 / 1024


def _is_source_build(dist_info: Path) -> bool:
    """
    Return True if direct_url.json exists and points to VCS or local path
    (i.e. was built from source, not downloaded from a package index).
    """
    direct_url = dist_info / "direct_url.json"
    if not direct_url.exists():
        return False
    try:
        import json as _json
        info = _json.loads(direct_url.read_text())
        # VCS install (git+https://...)
        if "vcs_info" in info:
            return True
        # Local directory install
        url = info.get("url", "")
        if url.startswith("file://"):
            return True
        # Direct URL to a non-index location is still a deliberate install
        # but NOT a source build — treat as normal (size-gated)
    except Exception:
        pass
    return False


def _has_direct_url(dist_info: Path) -> bool:
    """Return True if direct_url.json exists at all (any non-PyPI install)."""
    return (dist_info / "direct_url.json").exists()


def collect_auto_from_venv(venv_dir: Path, threshold_mb: float = 20.0,
                           verbose: bool = True) -> dict:
    """
    Auto-collect mode: scan ALL packages in venv, capture based on:
      - direct_url.json present → always capture (source build or direct URL)
      - no direct_url.json, size >= threshold_mb → capture
      - no direct_url.json, size < threshold_mb → skip (pip cache handles it)

    Runs in addition to (not instead of) the registered package scan.
    Returns dict of {pkg_name: True/False}.
    """
    site_packages = _venv_site_packages(venv_dir)
    if not site_packages:
        print(f"ERROR: could not find site-packages in {venv_dir}", file=sys.stderr)
        return {}

    python_tag = _python_tag(venv_dir)
    if not python_tag:
        print(f"ERROR: could not determine Python version from {venv_dir}", file=sys.stderr)
        return {}

    torch_full = _torch_version(venv_dir)
    if torch_full:
        torch_tag, cuda_tag = _parse_torch_tags(torch_full)
        print(f"  venv: {python_tag}  torch={torch_full}  → torch{torch_tag}  {cuda_tag}")
    else:
        torch_tag, cuda_tag = "", ""
        print(f"  venv: {python_tag}  (torch not installed)")

    print(f"  Auto-scan threshold: {threshold_mb:.0f}MB  "
          f"(direct_url packages always captured)")

    results = {}
    _all_known = {**HEAVY_PACKAGES, **LARGE_PIP_PACKAGES}

    for di in sorted(site_packages.iterdir()):
        if not di.is_dir() or not di.name.endswith(".dist-info"):
            continue

        # Derive normalised package name from dist-info dirname
        base         = di.name.replace(".dist-info", "").split("+")[0]
        pkg_raw      = base.rsplit("-", 1)[0]
        pkg          = pkg_raw.replace("-", "_").lower()

        source_build = _is_source_build(di)
        has_direct   = _has_direct_url(di)
        size_mb      = _installed_size_mb(di, site_packages)

        capture = source_build or has_direct or size_mb >= threshold_mb

        if not capture:
            continue

        reason = ("source-build" if source_build
                  else "direct-url" if has_direct
                  else f"{size_mb:.0f}MB")

        if verbose:
            print(f"\n  [{pkg}]  ({reason})")

        # Use registry info if available for cuda/torch tag embedding
        pkg_info = _all_known.get(pkg, {})
        _cuda    = cuda_tag  if pkg_info.get("cuda_in_name")  else ""
        _torch   = torch_tag if pkg_info.get("torch_in_name") else ""

        ok = collect_package(pkg, venv_dir, python_tag, _torch, _cuda,
                             verbose=verbose)
        results[pkg] = ok

    return results




def _list_venv_heavy(venv_dir: Path) -> None:
    """Print which heavy packages are installed in a venv."""
    site_packages = _venv_site_packages(venv_dir)
    if not site_packages:
        print(f"Could not find site-packages in {venv_dir}")
        return
    print(f"Heavy packages in {venv_dir}:")
    for pkg in HEAVY_PACKAGES:
        di = _find_dist_info(site_packages, pkg)
        if di:
            version = _dist_info_version(di)
            print(f"  {pkg:20s} {version}")
        else:
            print(f"  {pkg:20s} (not installed)")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Pack installed heavy packages into AI_Collected_Wheels/localbuild/")
    p.add_argument("--venv",      required=True,
                   help="Path to venv directory")
    p.add_argument("--pkg",       action="append", dest="packages",
                   help="Package to collect (repeat for multiple; default: all)")
    p.add_argument("--list",      action="store_true",
                   help="List heavy packages installed in venv, then exit")
    p.add_argument("--auto",      action="store_true",
                   help="Auto-scan entire venv: capture source builds (always) "
                        "and packages over --threshold (default 20MB)")
    p.add_argument("--threshold", type=float, default=20.0, metavar="MB",
                   help="Size threshold for --auto mode (default: 20MB)")
    ns = p.parse_args()

    venv_dir = Path(ns.venv)
    if not venv_dir.exists():
        print(f"ERROR: venv not found: {venv_dir}", file=sys.stderr)
        sys.exit(1)

    if ns.list:
        _list_venv_heavy(venv_dir)
        sys.exit(0)

    print(f"\nCollecting wheels from: {venv_dir}")
    print(f"Destination: {localbuild_dir()}\n")

    if ns.auto:
        results = collect_auto_from_venv(venv_dir, threshold_mb=ns.threshold)
    else:
        results = collect_from_venv(venv_dir, ns.packages)

    print(f"\n{'─'*50}")
    print("Summary:")
    ok_count = sum(1 for v in results.values() if v)
    for pkg, ok in results.items():
        status = "OK" if ok else "SKIP/FAIL"
        print(f"  {pkg:20s}  {status}")
    print(f"\n{ok_count}/{len(results)} packages collected")

    print(f"\nlocalbuild/ contents:")
    lb = localbuild_dir()
    if lb.exists():
        for w in sorted(lb.rglob("*.whl")):
            size_mb = w.stat().st_size // 1024**2
            print(f"  {w.name}  ({size_mb}MB)")
    else:
        print("  (empty)")

    sys.exit(0 if ok_count > 0 else 1)


if __name__ == "__main__":
    main()
