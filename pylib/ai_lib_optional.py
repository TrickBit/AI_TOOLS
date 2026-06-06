#!/usr/bin/env python3
# =============================================================================
# ai_lib_optional.py  —  Optional acceleration package detection
# =============================================================================
# Detects optional packages (Nunchaku, flash-attn) per app by scanning
# requirements files, checking installed versions in each app's venv, and
# querying GitHub releases for the latest available version including wheel
# availability for the app's Python version.
#
# Called by ai_installer.py as a pure function:
#   opt_states = ai_lib_optional.run(target, app_states)
#
# Requires: packaging>=21.0
# Both present in Debian 13 system Python — no venv needed.
# If missing: pip install --break-system-packages packaging
#
# Usage standalone:
#   python3 ai_lib_optional.py              # check all apps, print result
#   python3 ai_lib_optional.py --app wan2gp # check one app only
#   python3 ai_lib_optional.py --help       # show this help
# =============================================================================

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import ai_lib_github
from packaging.version import Version, InvalidVersion

# =============================================================================
# Known optional packages registry
# =============================================================================
# type     : "github"  — check GitHub releases API via ai_lib_github
# source   : "owner/repo" for github type
# req_names: list of strings to grep for in requirements.txt / pyproject.toml
# fatal_if_missing: False — these are optional, never block installs
#
# action values returned to caller:
#   "install"        — not installed, wheel available, offer to install
#   "update"         — installed but outdated, wheel available, offer to update
#   "current"        — installed and up to date
#   "no_wheel"       — latest release has no compatible wheel yet (e.g. no cp311)
#   "nvcc_mismatch"  — can't build from source (flash-attn specific)
#   "not_needed"     — requirements file does not reference this package
#   "unknown"        — could not determine (network error etc.)

OPTIONAL_REGISTRY: dict[str, dict] = {
    "nunchaku": {
        "type":      "github",
        "source":    "mit-han-lab/nunchaku",
        "req_names": ["nunchaku"],
        "label":     "Nunchaku",
    },
    "flash-attn": {
        "type":      "github",
        "source":    "Dao-AILab/flash-attention",
        "req_names": ["flash-attn", "flash_attn"],
        "label":     "flash-attn",
    },
}

SCRIPT_DIR = Path(__file__).parent

# =============================================================================
# Requirements scanning
# =============================================================================

def app_requires_pkg(app_dir: Path, req_names: list[str]) -> bool:
    """
    Return True if the app's requirements file references any of req_names.
    Checks requirements.txt, requirements_versions.txt, and pyproject.toml.
    """
    candidates = [
        app_dir / "requirements.txt",
        app_dir / "requirements_versions.txt",
        app_dir / "pyproject.toml",
    ]
    pattern = re.compile(
        r"(?i)(" + "|".join(re.escape(n) for n in req_names) + r")"
    )
    for f in candidates:
        if f.exists():
            try:
                if pattern.search(f.read_text()):
                    return True
            except OSError:
                continue
    return False

# =============================================================================
# Installed version detection
# =============================================================================

def _run(cmd: list[str], timeout: int = 15) -> str:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def installed_version(pkg_name: str, venv_python: Path | None) -> str | None:
    """Return installed version of pkg_name in the venv, or None."""
    if not venv_python or not venv_python.exists():
        return None
    raw = _run([str(venv_python), "-m", "pip", "show", pkg_name])
    for line in raw.splitlines():
        if line.lower().startswith("version:"):
            return line.split(":", 1)[1].strip()
    return None

# =============================================================================
# Per-package check
# =============================================================================

def check_package(
    pkg: str,
    reg: dict,
    app_dir: Path,
    venv_python: Path | None,
    py_tag: str,
    nvcc_present: bool,
) -> dict:
    """
    Check one optional package for one app.
    Returns a dict describing the current state and recommended action.
    """
    # Does this app actually reference this package?
    if not app_requires_pkg(app_dir, reg["req_names"]):
        return {
            "action":      "not_needed",
            "installed":   None,
            "latest":      None,
            "installable": False,
            "reason":      "not referenced in requirements",
        }

    # flash-attn specific: blocked by nvcc mismatch
    if pkg == "flash-attn" and not nvcc_present:
        return {
            "action":      "nvcc_mismatch",
            "installed":   None,
            "latest":      None,
            "installable": False,
            "reason":      "nvcc not available — SageAttention covers same ground",
        }

    # Get installed version
    inst_ver = installed_version(pkg, venv_python)

    # Get latest release info via ai_lib_github
    assets  = ai_lib_github.get_release_assets(reg["source"])
    latest_tag = ai_lib_github.get_latest_release(reg["source"])

    if latest_tag is None:
        return {
            "action":      "unknown",
            "installed":   inst_ver,
            "latest":      None,
            "installable": False,
            "reason":      "could not reach GitHub API",
        }

    latest_ver  = latest_tag.lstrip("v")
    installable = ai_lib_github.wheel_available(assets, py_tag)

    if not installable:
        return {
            "action":      "no_wheel",
            "installed":   inst_ver,
            "latest":      latest_ver,
            "installable": False,
            "reason":      f"no {py_tag} wheel in latest release ({latest_ver})",
        }

    if inst_ver is None:
        return {
            "action":      "install",
            "installed":   None,
            "latest":      latest_ver,
            "installable": True,
            "reason":      f"{pkg} not installed — {latest_ver} {py_tag} wheel available",
        }

    try:
        if Version(inst_ver) < Version(latest_ver):
            return {
                "action":      "update",
                "installed":   inst_ver,
                "latest":      latest_ver,
                "installable": True,
                "reason":      f"{inst_ver} → {latest_ver} available",
            }
    except InvalidVersion:
        pass

    return {
        "action":      "current",
        "installed":   inst_ver,
        "latest":      latest_ver,
        "installable": True,
        "reason":      f"up to date ({inst_ver})",
    }

# =============================================================================
# Pure function entry point
# =============================================================================

def run(target: str, app_states: dict) -> dict:
    """
    Pure function — no JSON I/O.

    Args:
        target:     mount point of the active target drive, e.g. "/mnt/BACKUP_4.0_TB"
        app_states: dict returned by ai_lib_apps.run() — keys are app names,
                    values include at minimum {"apps_subdir": str} at the top level
                    OR each app entry has the state fields from ai_lib_apps.

    Returns:
        dict keyed by app name, each value a dict of pkg_name -> check_result.
        Top-level key "probed_at" contains the ISO timestamp.

    Note:
        app_states is expected to have a top-level "apps_subdir" key set by
        ai_installer.py before calling (or default "AI_Apps" is used).
        nvcc presence is detected inline via shutil.which — no probe dict needed.
    """
    from ai_lib_apps import APP_REGISTRY

    apps_subdir  = app_states.get("apps_subdir", "AI_Apps")
    ai_apps_dir  = Path(target) / apps_subdir
    nvcc_present = bool(shutil.which("nvcc"))

    results: dict = {"probed_at": datetime.now(timezone.utc).isoformat()}

    for app, app_state in app_states.items():
        if app == "apps_subdir":
            continue  # skip the metadata key if present
        if not isinstance(app_state, dict):
            continue

        reg = APP_REGISTRY.get(app)
        if not reg:
            print(f"[optional] WARNING: unknown app '{app}' — skipping", file=sys.stderr)
            continue

        app_dir = ai_apps_dir / reg["disk_name"]
        if not app_dir.is_dir():
            results[app] = {}
            continue

        # Find venv python and derive ABI tag
        venv_python: Path | None = None
        py_tag = "cp311"  # fallback
        for rel in reg.get("venv_paths", []):
            candidate = app_dir / rel
            if candidate.exists():
                venv_python = candidate
                raw = _run([str(candidate), "-c",
                            "import sys; print(f'cp{sys.version_info.major}{sys.version_info.minor}')"])
                if raw.startswith("cp"):
                    py_tag = raw
                break

        app_results: dict = {}
        for pkg, pkg_reg in OPTIONAL_REGISTRY.items():
            print(f"[optional]  {app}/{pkg} ...", file=sys.stderr)
            try:
                result = check_package(pkg, pkg_reg, app_dir, venv_python, py_tag, nvcc_present)
            except Exception as e:
                result = {
                    "action":      "unknown",
                    "installed":   None,
                    "latest":      None,
                    "installable": False,
                    "reason":      f"error: {e}",
                }
            app_results[pkg] = result
            print(f"[optional]    → {result['action']}: {result['reason']}", file=sys.stderr)

        results[app] = app_results

    return results

# =============================================================================
# Standalone main — assembles args from JSON, calls run(), prints result
# =============================================================================

def _load_json_standalone() -> dict:
    """Minimal JSON loader for standalone use only."""
    import os
    env = os.environ.get("AI_INSTALLER_JSON")
    path = Path(env) if env else SCRIPT_DIR / "ai_installer.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            print(f"[optional] WARNING: could not read JSON ({e})", file=sys.stderr)
    return {}


def main() -> None:
    if "--help" in sys.argv:
        print(__doc__ or "ai_lib_optional.py — run() for optional package detection")
        sys.exit(0)

    try:
        from ai_lib_apps import APP_REGISTRY
    except ImportError as e:
        print(f"[optional] ERROR: could not import ai_lib_apps: {e}", file=sys.stderr)
        print("[optional] Ensure ai_lib_apps.py is in the same directory.", file=sys.stderr)
        sys.exit(1)

    data   = _load_json_standalone()
    target = data.get("config", {}).get("active_target", "")
    if not target:
        print("[optional] ERROR: no active_target in JSON — run ai_installer.py --init first.",
              file=sys.stderr)
        sys.exit(1)

    apps_subdir = data.get("config", {}).get("apps_subdir", "AI_Apps")

    # Build a minimal app_states dict from APP_REGISTRY keys
    # (same apps ai_installer.py would pass after ai_lib_apps.run())
    target_apps = list(APP_REGISTRY.keys())
    if "--app" in sys.argv:
        idx = sys.argv.index("--app")
        if idx + 1 < len(sys.argv):
            app_key = sys.argv[idx + 1]
            if app_key not in APP_REGISTRY:
                print(f"[optional] ERROR: unknown app '{app_key}'", file=sys.stderr)
                sys.exit(1)
            target_apps = [app_key]

    # Populate app_states from JSON installed records (or empty dicts)
    installed = data.get("targets", {}).get(target, {}).get("installed", {})
    app_states: dict = {"apps_subdir": apps_subdir}
    for app in target_apps:
        app_states[app] = installed.get(app, {})

    print(f"[optional] Checking optional packages for: {', '.join(target_apps)}", file=sys.stderr)

    try:
        results = run(target, app_states)
    except Exception as e:
        print(f"[optional] FATAL: {e}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
