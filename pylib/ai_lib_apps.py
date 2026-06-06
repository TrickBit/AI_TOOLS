#!/usr/bin/env python3
# =============================================================================
# ai_lib_apps.py  —  App state detection for the Jethro AI stack
# =============================================================================
# Pure function module — takes args, returns dict, no JSON reads or writes.
# ai_installer.py owns all JSON I/O.
#
# Called by ai_installer.py at startup:
#   import ai_lib_apps
#   app_states = ai_lib_apps.run(target, config, probe)
#
# Also provides the single canonical app registry (app key → disk name,
# venv paths, etc). Bash reads disk names from JSON — never duplicates them.
#
# Requires: packaging>=21.0  (Debian 13 system Python — no venv needed)
# If missing: pip install --break-system-packages packaging
#
# Usage (standalone):
#   python3 ai_lib_apps.py              # detect all apps, print result
#   python3 ai_lib_apps.py --dry-run    # same (alias for clarity)
#   python3 ai_lib_apps.py --app wan2gp # detect one app only
#   python3 ai_lib_apps.py --probe-torch # include torch import health check (slow)
#   python3 ai_lib_apps.py --help       # show this help
#
# When run standalone, reads ai_installer.json to assemble args for run().
# =============================================================================

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import ai_config
from packaging.version import Version, InvalidVersion

import ai_lib_github

# =============================================================================
# App registry — single source of truth
# =============================================================================
# disk_name : directory name under AI_Apps/
# venv_path : path to venv python relative to install dir (tried in order)
# pip_pkg   : pip package name for pip-based apps (None for git-based)
# git_based : True if installed via git clone

APP_REGISTRY: dict[str, dict] = {
    "automatic": {
        "label":      "AUTOMATIC1111",
        "disk_name":  "stable-diffusion-webui",
        "venv_paths": ["venv/bin/python"],
        "pip_pkg":    None,
        "git_based":  True,
        # A1111 is pinned to cu121 by design — never offer torch rebuild
        "torch_pinned": True,
        "torch_pin_reason": "torch pinned to cu121 by design",
        # Fresh install estimates (approximate — labelled as such in UI)
        "est_disk_gb":     8,
        "est_download_gb": 4,
        "est_min":         10,
        "est_note":        None,
    },
    "wan2gp": {
        "label":      "Wan2GP",
        "disk_name":  "Wan2GP",
        "venv_paths": ["venv/bin/python"],
        "pip_pkg":    None,
        "git_based":  True,
        "torch_pinned": False,
        "torch_pin_reason": None,
        "est_disk_gb":     5,
        "est_download_gb": 2,
        "est_min":         8,
        "est_note":        None,
    },
    "frampackstudio": {
        "label":      "FramePack-Studio",
        "disk_name":  "FramePack",
        "venv_paths": ["venv/bin/python"],
        "pip_pkg":    None,
        "git_based":  True,
        "torch_pinned": False,
        "torch_pin_reason": None,
        "est_disk_gb":     6,
        "est_download_gb": 2,
        "est_min":         10,
        "est_note":        "+30GB models on first launch",
    },
    "invokeai": {
        "label":      "InvokeAI",
        "disk_name":  "invokeai",
        "venv_paths": [".venv/bin/python", "venv/bin/python"],
        "pip_pkg":    "invokeai",
        "git_based":  False,
        "torch_pinned": False,      # constrained dynamically, not pinned
        "torch_pin_reason": None,
        "est_disk_gb":     6,
        "est_download_gb": 3,
        "est_min":         12,
        "est_note":        None,
    },
    "comfyui": {
        "label":      "ComfyUI",
        "disk_name":  "ComfyUI",
        "venv_paths": ["venv/bin/python"],
        "pip_pkg":    None,
        "git_based":  True,
        "torch_pinned": False,
        "torch_pin_reason": None,
        "est_disk_gb":     5,
        "est_download_gb": 2,
        "est_min":         8,
        "est_note":        None,
    },
}

SCRIPT_DIR  = Path(__file__).parent

# =============================================================================
# JSON helper — used by main() only when run standalone
# =============================================================================

def _load_json_standalone() -> dict:
    """Load ai_installer.json for standalone use — routes through ai_config API."""
    return ai_config.load_all()

# =============================================================================
# Git helpers
# =============================================================================

def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 10) -> str:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, cwd=cwd
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def git_local_info(app_dir: Path) -> dict:
    """Return local git hash and date without network access."""
    if not (app_dir / ".git").is_dir():
        return {"hash": None, "date": None}
    return {
        "hash": _run(["git", "-C", str(app_dir), "rev-parse", "--short", "HEAD"]) or None,
        "date": _run(["git", "-C", str(app_dir), "log", "-1", "--format=%cs"]) or None,
    }

# =============================================================================
# Torch health check
# =============================================================================

def torch_import_ok(venv_python: Path) -> bool:
    """
    Try importing torch in the venv. Returns True if import succeeds.
    Slow — only called when --probe-torch is passed.
    """
    if not venv_python.exists():
        return True     # can't check — assume ok, installer will catch it
    try:
        result = subprocess.run(
            [str(venv_python), "-c",
             "import torch; torch.cuda.is_available()"],
            capture_output=True, timeout=30
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return True     # timeout is not a broken install signal


# =============================================================================
# Version comparison helpers
# =============================================================================

def parse_torch_ver(torch_str: str | None) -> tuple[Version | None, str | None]:
    """
    Parse a torch version string like "2.7.1+cu128".
    Returns (Version("2.7.1"), "cu128") or (None, None) on failure.
    """
    if not torch_str:
        return None, None
    parts = torch_str.split("+")
    try:
        ver = Version(parts[0])
    except InvalidVersion:
        return None, None
    cuda = parts[1] if len(parts) > 1 else None
    return ver, cuda


def torch_is_constrained(inst_torch: str, system_cuda: str) -> tuple[bool, str]:
    """
    Returns (is_constrained, reason).
    InvokeAI may be on a lower CUDA tag than system max due to its torch~= pin.
    """
    _, inst_cuda = parse_torch_ver(inst_torch)
    if inst_cuda and inst_cuda != system_cuda:
        return True, f"torch constrained to {inst_cuda} — app requires torch~=2.7.x, system max {system_cuda}"
    return False, ""

# =============================================================================
# Core state detection
# =============================================================================

def detect_app_state(
    app: str,
    reg: dict,
    installed: dict,
    cfg_python: str,
    system_cuda: str,
    ai_apps_dir: Path,
    probe_torch: bool = False,
) -> dict:
    """
    Detect the current state of one app.

    Returns a dict with:
      state       : fresh | update | rebuild_torch | rebuild_python | constrained
      label       : human-readable verb (Install / Update / Rebuild / Reinstall torch)
      reason      : explanation string (empty if all ok)
      disk_name   : directory name under AI_Apps/
      label_long  : app display name
      git         : {hash, date} or {hash: null, date: null}
      venv_python : path to venv python or null
    """
    disk_name = reg["disk_name"]
    app_dir   = ai_apps_dir / disk_name

    # Find venv python
    venv_python: Path | None = None
    for rel in reg["venv_paths"]:
        candidate = app_dir / rel
        if candidate.exists():
            venv_python = candidate
            break

    base = {
        "disk_name":   disk_name,
        "label_long":  reg["label"],
        "git":         {"hash": None, "date": None},
        "venv_python": str(venv_python) if venv_python else None,
    }

    inst_status = installed.get("status", "unknown")
    inst_python = installed.get("python") or ""
    inst_torch  = installed.get("torch")  or ""

    # -------------------------------------------------------------------------
    # 0. Disk reality check — JSON record is irrelevant if venv is gone
    # -------------------------------------------------------------------------
    # After a wipe or failed install, JSON may still say "ok" but the venv
    # no longer exists on disk. Always trust disk over JSON.
    if inst_status == "ok" and inst_python and venv_python is None:
        has_git = (app_dir / ".git").is_dir()
        if has_git:
            git_info = git_local_info(app_dir)
            return {**base, "state": "fresh", "label": "Install",
                    "reason": "JSON says installed but venv missing — reinstall needed",
                    "git": git_info}
        return {**base, "state": "fresh", "label": "Install",
                "reason": "JSON says installed but venv missing — reinstall needed",
                "git": {"hash": None, "date": None}}

    # -------------------------------------------------------------------------
    # 1. No JSON record — check disk
    # -------------------------------------------------------------------------
    if inst_status in ("unknown", "fail") or not inst_python:
        has_git  = (app_dir / ".git").is_dir()
        has_venv = venv_python is not None

        if app_dir.is_dir():
            git_info = git_local_info(app_dir) if has_git else {"hash": None, "date": None}

            if has_git and has_venv:
                return {**base, "state": "update", "label": "Update",
                        "reason": "git repo + venv found — not in records",
                        "git": git_info}
            if has_git:
                return {**base, "state": "fresh", "label": "Reinstall",
                        "reason": "git repo found but no venv — may need reinstall",
                        "git": git_info}
            if has_venv:
                reason = ("pip package — venv found, no git expected"
                          if not reg["git_based"] else
                          "venv found but no git repo — unusual")
                return {**base, "state": "update", "label": "Update",
                        "reason": reason, "git": {"hash": None, "date": None}}

            return {**base, "state": "fresh", "label": "Install",
                    "reason": "dir exists but incomplete — will reinstall",
                    "git": {"hash": None, "date": None}}

        return {**base, "state": "fresh", "label": "Install",
                "reason": "", "git": {"hash": None, "date": None}}

    # -------------------------------------------------------------------------
    # 2. Python version changed
    # -------------------------------------------------------------------------
    if cfg_python and inst_python != cfg_python:
        return {**base, "state": "rebuild_python", "label": "Rebuild",
                "reason": f"Python changed ({inst_python} → {cfg_python})",
                "git": git_local_info(app_dir) if reg["git_based"] else {"hash": None, "date": None}}

    # -------------------------------------------------------------------------
    # 3. CUDA / torch mismatch
    # -------------------------------------------------------------------------
    if inst_torch and system_cuda not in inst_torch:
        if reg["torch_pinned"]:
            # A1111 — intentionally pinned, never rebuild
            git_info = git_local_info(app_dir)
            return {**base, "state": "update", "label": "Update",
                    "reason": reg["torch_pin_reason"],
                    "git": git_info}

        if app == "invokeai":
            constrained, reason = torch_is_constrained(inst_torch, system_cuda)
            if constrained:
                return {**base, "state": "update", "label": "Update",
                        "reason": reason,
                        "git": {"hash": None, "date": None}}

        git_info = git_local_info(app_dir) if reg["git_based"] else {"hash": None, "date": None}
        return {**base, "state": "rebuild_torch", "label": "Reinstall torch",
                "reason": f"CUDA changed (was {inst_torch}, now {system_cuda})",
                "git": git_info}

    # -------------------------------------------------------------------------
    # 4. Optional: torch health check
    # -------------------------------------------------------------------------
    if probe_torch and venv_python:
        if not torch_import_ok(venv_python):
            git_info = git_local_info(app_dir) if reg["git_based"] else {"hash": None, "date": None}
            return {**base, "state": "rebuild_torch", "label": "Rebuild",
                    "reason": "torch import failed — broken install detected",
                    "git": git_info}

    # -------------------------------------------------------------------------
    # 5. All good
    # -------------------------------------------------------------------------
    git_info = git_local_info(app_dir) if reg["git_based"] else {"hash": None, "date": None}
    return {**base, "state": "update", "label": "Update",
            "reason": "", "git": git_info}

# =============================================================================
# Main
# =============================================================================

def run(
    target: str,
    config: dict,
    probe: dict,
    apps: list[str] | None = None,
    probe_torch: bool = False,
) -> dict:
    """
    Detect the current state of all (or specified) apps.

    Args:
        target      : active target mount point, e.g. "/mnt/BACKUP_4.0_TB"
        config      : config{} section from ai_installer.json
        probe       : probe{} section from ai_installer.json (output of ai_lib_probe.run())
        apps        : list of app keys to check; defaults to all in APP_REGISTRY
        probe_torch : if True, run slow torch import health check

    Returns dict keyed by app name, plus "probed_at" timestamp.
    No JSON reads or writes — caller owns all I/O.
    """
    if apps is None:
        apps = list(APP_REGISTRY.keys())

    system_cuda  = probe.get("gpu", {}).get("torch_cuda") or "cu118"
    apps_subdir  = config.get("apps_subdir", "AI_Apps")
    ai_apps_dir  = Path(target) / apps_subdir

    # installed records live under targets[target].installed{}
    installed_db = config.get("_installed", {})   # pre-extracted by caller

    results: dict = {"probed_at": datetime.now(timezone.utc).isoformat()}

    for app in apps:
        reg = APP_REGISTRY.get(app)
        if not reg:
            print(f"[apps] WARNING: unknown app '{app}' — skipping", file=sys.stderr)
            continue

        installed  = installed_db.get(app, {})
        cfg_python = ai_lib_github.get_required_python(app)

        try:
            state = detect_app_state(
                app, reg, installed, cfg_python,
                system_cuda, ai_apps_dir, probe_torch
            )
        except Exception as e:
            print(f"[apps] ERROR detecting state for {app}: {e}", file=sys.stderr)
            state = {
                "disk_name":   reg["disk_name"],
                "label_long":  reg["label"],
                "state":       "unknown",
                "label":       "?",
                "reason":      f"detection error: {e}",
                "git":         {"hash": None, "date": None},
                "venv_python": None,
            }

        results[app] = state
        git = state["git"]
        git_str = f" [{git['hash']} · {git['date']}]" if git.get("hash") else ""
        print(f"[apps]  {reg['label']:20s}  {state['label']:20s}  {state['reason']}{git_str}",
              file=sys.stderr)

    return results


def main() -> None:
    if "--help" in sys.argv:
        print(__doc__)
        sys.exit(0)

    probe_torch = "--probe-torch" in sys.argv

    # --app <key> to run a single app
    target_apps = None   # None → all apps
    if "--app" in sys.argv:
        idx = sys.argv.index("--app")
        if idx + 1 < len(sys.argv):
            app_key = sys.argv[idx + 1]
            if app_key not in APP_REGISTRY:
                print(f"[apps] ERROR: unknown app '{app_key}'", file=sys.stderr)
                print(f"[apps] Known apps: {', '.join(APP_REGISTRY)}", file=sys.stderr)
                sys.exit(1)
            target_apps = [app_key]

    # Assemble args from JSON — standalone use only
    data = _load_json_standalone()

    probe  = data.get("probe", {})
    config = data.get("config", {})

    # Determine active target
    active_target = (
        os.environ.get("AI_TARGET")
        or config.get("active_target")
        or ""
    )
    # Pre-extract installed records into config for run()
    installed_db = {}
    if active_target and "targets" in data:
        installed_db = data.get("targets", {}).get(active_target, {}).get("installed", {})
    config["_installed"] = installed_db

    if not probe:
        print("[apps] WARNING: no probe data in JSON — run ai_lib_probe.py first", file=sys.stderr)
    if not active_target:
        print("[apps] WARNING: no active target — set AI_TARGET or run ai_installer.py --init",
              file=sys.stderr)

    apps_label = ', '.join(target_apps) if target_apps else 'all'
    print(f"[apps] Detecting state for: {apps_label}", file=sys.stderr)
    if probe_torch:
        print("[apps] --probe-torch enabled (slow)", file=sys.stderr)

    try:
        results = run(active_target, config, probe,
                      apps=target_apps, probe_torch=probe_torch)
    except Exception as e:
        print(f"[apps] FATAL: {e}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
