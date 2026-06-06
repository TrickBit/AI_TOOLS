#!/usr/bin/env python3
# =============================================================================
# ai_lib_wheels.py  —  Wheel cache management for heavy compiled packages
# =============================================================================
# Manages the build-once / download-once wheel cache in AI_Collected_Wheels/.
#
# Priority chain (never skips a level):
#   1. localbuild/  — wheels we compiled ourselves
#   2. downloaded/  — prebuilt wheels fetched from external sources
#   3. Online search — GitHub API query, filenames only (no download yet)
#      → caller decides whether to fetch()
#   4. Source build — caller's problem; on success call cache_built_wheel()
#
# Python import usage (ai_installer.py):
#   import ai_lib_wheels
#   result = ai_lib_wheels.find("flash_attn", torch="2.12", cuda="cu130", python="cp311")
#   # {"localbuild": Path(...)} or {"downloaded": Path(...)} or {}
#
#   candidates = ai_lib_wheels.search("flash_attn", torch="2.12", cuda="cu130", python="cp311")
#   # [{"name": "flash_attn-...", "url": "https://...", "source": "mjun0812"}]
#
#   path = ai_lib_wheels.fetch(candidates[0], dest="downloaded")
#   ai_lib_wheels.install(path, venv_dir=Path("/mnt/.../venv"))
#
# Bash CLI usage (ai_*_install.sh):
#   python3 ai_lib_wheels.py install flash_attn \
#       --torch 2.12 --cuda cu130 --python cp311 --venv "${VENV_DIR}"
#   # Walks full chain interactively. Exit 0 = installed. Exit 1 = not installed.
#
# Requires: requests>=2.28.0  (system Python — no venv needed)
# =============================================================================

import os
import re
import sys
import json
from pathlib import Path
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Heavy packages registry
# ---------------------------------------------------------------------------
# Packages worth caching — source build takes >5 min or is fragile.
# Each entry defines how to name our localbuild wheels and where to search online.
#
# "cuda_in_name"  : True  → cuda tag embedded in local version label
# "torch_in_name" : True  → torch version embedded in local version label
# "sources"       : ordered list of search sources (tried in order)

HEAVY_PACKAGES = {
    "flash_attn": {
        "import_name":   "flash_attn",
        "cuda_in_name":  True,
        "torch_in_name": True,
        "sources":       ["mjun0812"],
        "fallback_ver":  None,   # no safe fallback — either works or doesn't
    },
    "sageattention": {
        "import_name":   "sageattention",
        "cuda_in_name":  True,
        "torch_in_name": False,  # snw35 uses +cu13 shorthand only
        "sources":       ["snw35"],
        "fallback_ver":  "1.0.6",  # pure-Python fallback available on PyPI
    },
    "nunchaku": {
        "import_name":   "nunchaku",
        "cuda_in_name":  True,
        "torch_in_name": True,
        "sources":       ["deepbeepmeep"],
        "fallback_ver":  None,
    },
}

# ---------------------------------------------------------------------------
# Wheel source definitions
# ---------------------------------------------------------------------------
# Used by search() to query the right place for each package.

WHEEL_SOURCES = {
    "mjun0812": {
        "type":       "github_releases",
        "owner_repo": "mjun0812/flash-attention-prebuild-wheels",
        "packages":   ["flash_attn"],
    },
    "snw35": {
        "type":       "github_releases",
        "owner_repo": "snw35/sageattention-wheel",
        "packages":   ["sageattention"],
    },
    "deepbeepmeep": {
        "type":       "github_releases",
        "owner_repo": "deepbeepmeep/kernels",
        "packages":   ["nunchaku"],
    },
}

# ---------------------------------------------------------------------------
# Wheels directory  (read from ai_config, with fallback)
# ---------------------------------------------------------------------------

def _wheels_root() -> Path:
    """
    Return the AI_Collected_Wheels root directory.
    Reads config.wheels_drive from ai_installer.json via ai_config.
    Falls back to /mnt/BACKUP_4.0_TB/AI_Collected_Wheels if config missing.
    """
    try:
        import ai_config
        found, drive = ai_config.get("config", "wheels_drive")
        if found and drive:
            return Path(drive) / "AI_Collected_Wheels"
    except ImportError:
        pass
    return Path("/mnt/BACKUP_4.0_TB/AI_Collected_Wheels")


def localbuild_dir() -> Path:
    return _wheels_root() / "localbuild"


def downloaded_dir() -> Path:
    return _wheels_root() / "downloaded"


# ---------------------------------------------------------------------------
# Filename matching
# ---------------------------------------------------------------------------
# Our localbuild convention:
#   flash_attn-2.8.3+cu130.torch212-cp311-cp311-linux_x86_64.whl
#
# Downloaded conventions vary by source:
#   mjun0812:  flash_attn-2.8.3+cu130torch2.12-cp311-cp311-linux_x86_64.whl
#   snw35:     sageattention-2.2.0+cu13-cp311-cp311-linux_x86_64.whl
#
# Matching rules:
#   - package name prefix must match (flash_attn, sageattention, nunchaku)
#   - python tag must match exactly (cp311, cp312)
#   - cuda tag: cu130 matches cu130, cu13, cu130 (major-only is a subset match)
#   - torch: if present in filename, must match major.minor (2.12)
#   - platform: linux_x86_64 only


def _cuda_matches(filename: str, cuda: str) -> bool:
    """
    True if cuda tag in filename is compatible with requested cuda.
    cu130 requested → matches cu130 and cu13 in filename.
    cu13  requested → matches cu13 and cu130 in filename.
    """
    # Normalise: strip 'cu' prefix, get major version digits
    requested = cuda.lstrip("cu")        # "130" or "13"
    major_req  = requested[:2]           # "13"

    # Find all cu\d+ tokens in filename
    found_tags = re.findall(r'cu(\d+)', filename)
    for tag in found_tags:
        major_found = tag[:2]
        if major_found == major_req:
            return True
    return False


def _torch_matches(filename: str, torch_ver: str) -> bool:
    """
    True if torch version in filename is compatible, or if filename has no torch tag.
    torch_ver is like "2.12" (major.minor only).
    Strips dots for comparison since filenames use both "2.12" and "212".
    """
    nodots = torch_ver.replace(".", "")  # "212"
    # Look for torchX.Y or torchXY patterns
    pattern = rf'torch({re.escape(torch_ver)}|{re.escape(nodots)})'
    if re.search(pattern, filename):
        return True
    # If no torch tag at all in filename — still compatible (e.g. snw35 sageattention)
    if not re.search(r'torch\d', filename):
        return True
    return False


def _pkg_name_matches(filename: str, pkg: str) -> bool:
    """Wheel filename starts with the package name (hyphens and underscores equivalent)."""
    normalised = pkg.replace("-", "_").lower()
    fn_lower   = filename.replace("-", "_").lower()
    return fn_lower.startswith(normalised + "-") or fn_lower.startswith(normalised + "_")


def _wheel_matches(filename: str, pkg: str, torch_ver: str, cuda: str, python: str) -> bool:
    """
    Return True if a wheel filename is compatible with the requested combination.
    All four dimensions must match.
    """
    if not filename.endswith(".whl"):
        return False
    if not _pkg_name_matches(filename, pkg):
        return False
    if python not in filename:
        return False
    if not _cuda_matches(filename, cuda):
        return False
    if not _torch_matches(filename, torch_ver):
        return False
    return True


def _best_wheel(directory: Path, pkg: str, torch_ver: str,
                cuda: str, python: str) -> Path | None:
    """
    Return the best matching wheel in a directory, or None.
    'Best' = most recent by filename sort (version numbers sort naturally).
    """
    if not directory.exists():
        return None
    matches = [
        f for f in directory.iterdir()
        if _wheel_matches(f.name, pkg, torch_ver, cuda, python)
    ]
    if not matches:
        return None
    return sorted(matches)[-1]   # latest version wins


# ---------------------------------------------------------------------------
# Public API — find / search / fetch / install
# ---------------------------------------------------------------------------

def find(pkg: str, *, torch: str, cuda: str, python: str) -> dict:
    """
    Check local cache for a matching wheel.
    Checks localbuild/ first, then downloaded/.

    Returns one of:
      {"localbuild": Path(...)}
      {"downloaded": Path(...)}
      {}   — nothing found locally

    Does NOT hit the network.

    Args:
        pkg:    package name, e.g. "flash_attn" or "sageattention"
        torch:  torch major.minor, e.g. "2.12"
        cuda:   cuda tag, e.g. "cu130"
        python: python tag, e.g. "cp311"
    """
    w = _best_wheel(localbuild_dir(), pkg, torch, cuda, python)
    if w:
        return {"localbuild": w}

    w = _best_wheel(downloaded_dir(), pkg, torch, cuda, python)
    if w:
        return {"downloaded": w}

    return {}


def search(pkg: str, *, torch: str, cuda: str, python: str) -> list[dict]:
    """
    Query online sources for matching prebuilt wheels.
    Returns a list of candidates — filenames and download URLs only.
    Does NOT download anything.

    Each candidate dict:
      {
        "name":    "flash_attn-2.8.3+cu130torch2.12-cp311-cp311-linux_x86_64.whl",
        "url":     "https://github.com/.../releases/download/.../flash_attn-...",
        "source":  "mjun0812",
        "size_mb": 234,   # may be None if not available from API
      }

    Returns [] on network error or no matches.
    """
    try:
        import ai_lib_github
    except ImportError:
        print("[ai_lib_wheels] ERROR: ai_lib_github not available", file=sys.stderr)
        return []

    if pkg not in HEAVY_PACKAGES:
        print(f"[ai_lib_wheels] '{pkg}' not in HEAVY_PACKAGES registry", file=sys.stderr)
        return []

    sources = HEAVY_PACKAGES[pkg]["sources"]
    candidates = []

    for source_key in sources:
        source = WHEEL_SOURCES.get(source_key)
        if not source:
            continue

        if source["type"] == "github_releases":
            owner_repo = source["owner_repo"]
            assets = ai_lib_github.get_release_assets_with_urls(owner_repo)
            for asset in assets:
                name = asset.get("name", "")
                url  = asset.get("url", "")
                size = asset.get("size_mb")
                if _wheel_matches(name, pkg, torch, cuda, python):
                    candidates.append({
                        "name":    name,
                        "url":     url,
                        "source":  source_key,
                        "size_mb": size,
                    })

    return candidates


def fetch(candidate: dict, dest: str = "downloaded") -> Path | None:
    """
    Download a wheel from a candidate dict (as returned by search()).
    Saves to downloaded/ or localbuild/ as specified by dest.
    Returns the saved Path on success, None on failure.

    Args:
        candidate: dict from search() with "name" and "url" keys
        dest:      "downloaded" or "localbuild"
    """
    try:
        import requests
    except ImportError:
        print("[ai_lib_wheels] ERROR: requests not available", file=sys.stderr)
        return None

    dest_dir = downloaded_dir() if dest == "downloaded" else localbuild_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)

    name     = candidate["name"]
    url      = candidate["url"]
    out_path = dest_dir / name

    if out_path.exists():
        print(f"  Already cached: {name}")
        return out_path

    print(f"  Downloading {name}...")
    print(f"    from: {url}")

    try:
        token = os.environ.get("GITHUB_TOKEN", "").strip()
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        resp = requests.get(url, headers=headers, stream=True, timeout=60)
        if not resp.ok:
            print(f"[ai_lib_wheels] Download failed: HTTP {resp.status_code}",
                  file=sys.stderr)
            return None

        total = int(resp.headers.get("content-length", 0))
        downloaded = 0
        with open(out_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded * 100 // total
                    print(f"\r    {pct:3d}%  {downloaded // 1024**2}MB / "
                          f"{total // 1024**2}MB", end="", flush=True)
        print()  # newline after progress

        size_mb = out_path.stat().st_size // 1024**2
        print(f"  OK: {name} ({size_mb}MB) → {dest_dir}")
        return out_path

    except Exception as e:
        print(f"[ai_lib_wheels] Download error: {e}", file=sys.stderr)
        out_path.unlink(missing_ok=True)
        return None


def install(wheel_path: Path, venv_dir: Path) -> bool:
    """
    Install a wheel into a venv using that venv's pip.
    Returns True on success.
    """
    import subprocess

    pip = venv_dir / "bin" / "pip"
    if not pip.exists():
        # InvokeAI uses python -m pip
        python = venv_dir / "bin" / "python"
        if not python.exists():
            print(f"[ai_lib_wheels] ERROR: no pip or python in {venv_dir}",
                  file=sys.stderr)
            return False
        cmd = [str(python), "-m", "pip", "install", str(wheel_path)]
    else:
        cmd = [str(pip), "install", str(wheel_path)]

    print(f"  Installing {wheel_path.name}...")
    result = subprocess.run(cmd, capture_output=False)
    return result.returncode == 0


def record_build_failure(pkg: str, reason: str) -> None:
    """
    Record a wheel build failure in ai_installer.json.
    Silently does nothing if ai_config is unavailable.
    """
    try:
        import ai_config
        data   = ai_config.load_all()
        builds = data.get("wheel_builds", {})
        builds[pkg] = {
            "attempted_at": datetime.now(timezone.utc).isoformat(),
            "status":       "failed",
            "reason":       reason,
        }
        data["wheel_builds"] = builds
        ai_config.save_all(data)
    except Exception:
        pass


def get_build_record(pkg: str) -> dict | None:
    """
    Return the last build record for a package, or None.
    Dict has keys: attempted_at, status, reason.
    """
    try:
        import ai_config
        data = ai_config.load_all()
        return data.get("wheel_builds", {}).get(pkg)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Interactive CLI  — used by bash installers
# ---------------------------------------------------------------------------

def _cli_install(args: list[str]) -> int:
    """
    install <pkg> --torch <ver> --cuda <tag> --python <tag> --venv <path>

    Full interactive chain:
      1. Check localbuild/ → offer to install (y/n)
      2. Check downloaded/ → offer to install (y/n)
      3. Check last build record → warn if previously failed
      4. Search online → offer to download and install (y/n)
      5. Offer source build (just exits 1 — caller does the build)

    Exit 0 = wheel installed into venv.
    Exit 1 = not installed (user declined, nothing found, or build needed).
    Exit 2 = argument error.
    """
    import argparse
    p = argparse.ArgumentParser(prog="ai_lib_wheels.py install")
    p.add_argument("pkg",            help="Package name, e.g. flash_attn")
    p.add_argument("--torch",        required=True, help="Torch major.minor, e.g. 2.12")
    p.add_argument("--cuda",         required=True, help="CUDA tag, e.g. cu130")
    p.add_argument("--python",       required=True, help="Python tag, e.g. cp311")
    p.add_argument("--venv",         required=True, help="Venv directory path")
    p.add_argument("--no-search",    action="store_true",
                   help="Skip online search (offline mode)")

    try:
        ns = p.parse_args(args)
    except SystemExit:
        return 2

    pkg        = ns.pkg
    torch_ver  = ns.torch
    cuda       = ns.cuda
    python_tag = ns.python
    venv_dir   = Path(ns.venv)

    def _prompt(msg: str) -> bool:
        try:
            ans = input(f"  {msg} [Y/n] ").strip().lower()
            return ans in ("y", "yes", "")   # empty = Y
        except (EOFError, KeyboardInterrupt):
            print()
            return False

    print(f"\n[wheels] {pkg}  torch={torch_ver}  cuda={cuda}  python={python_tag}")

    # ── Step 1: localbuild ──────────────────────────────────────────────────
    result = find(pkg, torch=torch_ver, cuda=cuda, python=python_tag)

    if "localbuild" in result:
        w = result["localbuild"]
        size_mb = w.stat().st_size // 1024**2
        print(f"  Found in localbuild: {w.name} ({size_mb}MB)")
        if _prompt("Install from local build cache?"):
            return 0 if install(w, venv_dir) else 1
        print("  Skipped.")
        return 1

    # ── Step 2: downloaded ──────────────────────────────────────────────────
    if "downloaded" in result:
        w = result["downloaded"]
        size_mb = w.stat().st_size // 1024**2
        print(f"  Found in downloaded: {w.name} ({size_mb}MB)")
        if _prompt("Install from downloaded cache?"):
            return 0 if install(w, venv_dir) else 1
        print("  Skipped.")
        return 1

    # ── Step 3: check build failure history ────────────────────────────────
    rec = get_build_record(pkg)
    if rec and rec.get("status") == "failed":
        print(f"  NOTE: Last build attempt failed ({rec.get('attempted_at', '?')})")
        print(f"        Reason: {rec.get('reason', 'unknown')}")
        print(f"        Recommending prebuilt wheel instead.")

    # ── Step 4: online search ───────────────────────────────────────────────
    if not ns.no_search:
        print(f"  Searching online for prebuilt wheels...")
        candidates = search(pkg, torch=torch_ver, cuda=cuda, python=python_tag)

        if candidates:
            print(f"  Found {len(candidates)} candidate(s):")
            for i, c in enumerate(candidates):
                size_str = f"{c['size_mb']}MB" if c.get("size_mb") else "?"
                print(f"    [{i+1}] {c['name']}  ({size_str})  [{c['source']}]")

            if _prompt(f"Download and install {candidates[0]['name']}?"):
                # Always download the first (best) match
                path = fetch(candidates[0], dest="downloaded")
                if path and install(path, venv_dir):
                    return 0
                print("  Download or install failed.", file=sys.stderr)
                return 1
            print("  Skipped.")
        else:
            print(f"  No prebuilt wheels found online for {pkg} "
                  f"{torch_ver}/{cuda}/{python_tag}.")

    # ── Step 5: source build needed ─────────────────────────────────────────
    print(f"  No cached or prebuilt wheel available.")
    print(f"  Caller should build from source and then run:")
    print(f"    python3 ai_collect_wheels.py --venv {venv_dir} --pkg {pkg}")
    return 1


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    cmd  = args[0]
    rest = args[1:]

    if cmd == "install":
        sys.exit(_cli_install(rest))
    elif cmd == "find":
        # Quick cache check — no prompting, just print result
        import argparse
        p = argparse.ArgumentParser(prog="ai_lib_wheels.py find")
        p.add_argument("pkg")
        p.add_argument("--torch",  required=True)
        p.add_argument("--cuda",   required=True)
        p.add_argument("--python", required=True)
        ns = p.parse_args(rest)
        result = find(ns.pkg, torch=ns.torch, cuda=ns.cuda, python=ns.python)
        if result:
            loc, path = next(iter(result.items()))
            print(f"{loc}: {path}")
            sys.exit(0)
        sys.exit(1)
    else:
        print(f"[ai_lib_wheels] unknown command '{cmd}' — use install / find",
              file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
