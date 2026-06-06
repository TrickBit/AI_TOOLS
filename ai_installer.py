#!/usr/bin/env python3
# =============================================================================
# ai_installer.py  —  AI stack entry point (replaces ai_conductor.sh)
# =============================================================================
# Interactive installer, updater, and launcher for the Jethro AI stack.
# Single entry point for all stack operations.
#
# Usage:
#   ai_installer.py                    # interactive menu (normal use)
#   ai_installer.py --init             # force reinit: backup old JSON, pick target, write config
#   ai_installer.py --select           # change active target drive
#   ai_installer.py probe              # probe system and print summary, then exit
#   ai_installer.py status             # print app status for all apps, then exit
#   ai_installer.py target             # show active target
#   ai_installer.py target /mnt/X      # set active target
#   ai_installer.py comfyui setup      # ComfyUI workflow pack installer (interactive picker)
#   ai_instG928aller.py comfyui reinstall <id>  # reinstall a workflow pack from JSON record
#   ai_installer.py comfyui status     # show installed ComfyUI workflow state
#
# Startup flow:
#   no JSON  → first-run welcome → target select → write JSON → install menu
#   no args  → load JSON → verify target mounted → check probe staleness → menu
#   --init   → backup old JSON → probe → select target → write JSON → menu
#   --select → probe → select target → update JSON → menu
#
# Menu layout:
#   Driven by ai_installer_menu.json — edit that file to reorder, rename or
#   hide items without touching Python. Section labels starting with "CMNT:"
#   are treated as null (no header printed) — human-readable annotation only.
#
# JSON file: ai_installer.json — all access via ai_config module.
# Python owns all JSON writes. Bash reads via ai_config.py CLI.
#
# Directory layout (relative to SCRIPT_DIR = AI_Tools/):
#   installers/       — bash install scripts per app
#   runners/          — bash/python runner scripts per app
#   postinstallers/   — post-install scripts per app
#                       .sh stubs point to .py replacements where applicable
#   pylib/            — shared Python libraries
#
# Requires: packaging>=21.0, requests>=2.28.0
# Both present in Debian 13 system Python — no venv needed.
# =============================================================================

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Callable

os.environ.setdefault("AI_INSTALLER_JSON", str(Path(__file__).parent / "ai_installer.json"))

# Shared Python library — moved to pylib/ during project restructure
_PYLIB = Path(__file__).parent / "pylib"
if str(_PYLIB) not in sys.path:
    sys.path.insert(0, str(_PYLIB))

import ai_config
import ai_lib_probe
import ai_lib_apps
import ai_lib_optional
import ai_lib_github
import ai_collect_wheels

# =============================================================================
# Paths and constants
# =============================================================================

SCRIPT_DIR         = Path(__file__).parent
JSON_PATH          = SCRIPT_DIR / "ai_installer.json"
MENU_JSON_PATH     = SCRIPT_DIR / "ai_installer_menu.json"
INSTALLERS_DIR     = SCRIPT_DIR / "installers"
RUNNERS_DIR        = SCRIPT_DIR / "runners"
POSTINSTALLERS_DIR = SCRIPT_DIR / "postinstallers"

ALL_APPS = ["automatic", "wan2gp", "frampackstudio", "invokeai", "comfyui"]

PROBE_MAX_AGE_HOURS = 24

# Default config values written on --init / first-run
DEFAULT_CONFIG = {
    "port":              7860,
    "apps_subdir":       "AI_Apps",
    "resources_subdir":  "AI-Shared-Resources",
    "outputs_subdir":    "AI_Outputs",
    "work_subdir":       "AI_Work",
    "wheels_drive":      "/mnt/BACKUP_4.0_TB",   # hosts AI_Collected_Wheels/
}

# =============================================================================
# Colours — thin wrappers, nothing fancier than needed
# =============================================================================

CYAN   = "\033[36m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
NC     = "\033[0m"

def cyan(s):   return f"{CYAN}{s}{NC}"
def green(s):  return f"{GREEN}{s}{NC}"
def yellow(s): return f"{YELLOW}{s}{NC}"
def red(s):    return f"{RED}{s}{NC}"
def bold(s):   return f"{BOLD}{s}{NC}"
def dim(s):    return f"{DIM}{s}{NC}"

def info(msg):  print(f"  {cyan('>')} {msg}")
def good(msg):  print(f"  {green('✔')} {msg}")
def warn(msg):  print(f"  {yellow('⚠')} {msg}")
def err(msg):   print(f"  {red('✘')} {msg}", file=sys.stderr)
def header(msg):
    print()
    print(bold(msg))
    print("─" * 62)

# =============================================================================
# JSON access — all routes through ai_config
# =============================================================================

def load_json() -> dict:
    """Load full JSON via ai_config API."""
    return ai_config.load_all()


def write_json(data: dict) -> None:
    """Write full JSON via ai_config API."""
    ok = ai_config.save_all(data)
    if not ok:
        raise OSError("ai_config.save_all failed")


def update_json(updates: dict) -> None:
    """Merge updates into existing JSON via ai_config API."""
    data = ai_config.load_all()
    _deep_merge(data, updates)
    ai_config.save_all(data)


def _deep_merge(base: dict, overlay: dict) -> None:
    """Merge overlay into base in-place, recursing into nested dicts."""
    for key, val in overlay.items():
        if key in base and isinstance(base[key], dict) and isinstance(val, dict):
            _deep_merge(base[key], val)
        else:
            base[key] = val

# =============================================================================
# Postinstall helpers
# =============================================================================

def _postinstall_script(app: str) -> Path | None:
    """
    Purpose: Return path to postinstall .sh for an app, or None if not found.
    Looks in postinstallers/ only — not the AI_Tools root.
    """
    p = POSTINSTALLERS_DIR / f"ai_{app}_postinstall.sh"
    return p if p.exists() else None


def _postinstall_is_stub(script: Path) -> bool:
    """
    Purpose: Return True if script is a no-op stub pointing to a Python replacement.
    Detected by the word SUPERSEDED in the first 20 lines of the file.
    Stubs are used when a bash postinstall has been replaced by a Python script
    but we want the .sh to remain as a human-readable signpost.
    """
    try:
        for line in script.read_text().splitlines()[:20]:
            if "SUPERSEDED" in line:
                return True
    except OSError:
        pass
    return False


def _postinstall_py(app: str) -> Path | None:
    """
    Purpose: Return path to Python postinstall for an app in postinstallers/, or None.
    Used when a bash stub has been superseded by a Python replacement.
    """
    p = POSTINSTALLERS_DIR / f"ai_{app}_postinstall.py"
    return p if p.exists() else None

# =============================================================================
# MenuItem
# =============================================================================

@dataclass
class MenuItem:
    label: str
    action: Callable
    detail: str = ""
    number: int = 0         # assigned at display time
    no_pause: bool = False  # True for actions that own their own loop/screen

# =============================================================================
# Drive selection
# =============================================================================

def select_target(drives: list[dict], known_targets: dict) -> str | None:
    """
    Show a drive selection menu and return the chosen mount point.
    Returns None if the user quits.

    drives        : list of dicts from probe["drives"] — {mount, fs_type, has_ai}
    known_targets : targets{} dict from JSON — keyed by mount point
    """
    if not drives:
        warn("No valid target drives detected.")
        try:
            path = input("  Enter path manually (or q to quit): ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        return path if path and path != "q" else None

    print()
    print(bold("  Select target drive:"))
    print()

    known_mounts = set(known_targets.keys())

    def app_count(mount: str) -> int:
        installed = known_targets.get(mount, {}).get("installed", {})
        return sum(1 for v in installed.values() if v.get("status") == "ok")

    mounted_known = [d["mount"] for d in drives if d["mount"] in known_mounts]
    default_mount = mounted_known[0] if len(mounted_known) == 1 else None

    for i, drive in enumerate(drives, 1):
        mount   = drive["mount"]
        fstype  = drive.get("fs_type", "")
        has_ai  = drive.get("has_ai", False)

        known_marker   = f"  {green('*')}" if mount in known_mounts else "   "
        default_marker = f"  {green('[Enter]')}" if mount == default_mount else ""

        size_str = _disk_usage_str(mount)

        note = ""
        if mount in known_mounts:
            ac = app_count(mount)
            note = dim(f"  previously used — {ac} app(s) installed")

        print(f"  {cyan(f'{i:2d}')}.{known_marker} {mount:<36} {fstype:<6}  "
              f"{size_str}{note}{default_marker}")

    print()
    print(f"  {cyan(' q')}. Quit")
    print()

    if default_mount:
        prompt = f"  [Enter] to select {default_mount}, number, or q: "
    else:
        prompt = "  Number + Enter, or q to quit: "

    while True:
        try:
            choice = input(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return None

        if choice == "q":
            return None

        if choice == "" and default_mount:
            return default_mount

        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(drives):
                return drives[idx - 1]["mount"]

        if choice == "":
            continue

        warn(f"Enter a number 1–{len(drives)} or q.")


def _disk_usage_str(mount: str) -> str:
    """Return 'X free of Y' string for a mount point, read live from df."""
    try:
        result = subprocess.run(
            ["df", "-h", "--output=size,avail", mount],
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.strip().splitlines()
        if len(lines) >= 2:
            parts = lines[1].split()
            if len(parts) >= 2:
                return f"{parts[1]} free of {parts[0]}"
    except (subprocess.TimeoutExpired, OSError):
        pass
    return ""

# =============================================================================
# Probe
# =============================================================================

def run_probe(write: bool = True) -> dict:
    """
    Run the system probe. If write=True, persist results to JSON.
    Always returns the probe dict.
    """
    info("Probing system...")
    probe = ai_lib_probe.run()

    gpu = probe.get("gpu", {})
    if gpu.get("name"):
        good(f"{gpu['name']} | driver {gpu['driver']} | "
             f"{gpu['torch_cuda']} | sage_v2={gpu['sage_v2_capable']}")
    else:
        warn("No GPU detected")

    if write:
        ai_config.write_probe(probe)

    return probe


def _probe_is_stale(probe: dict) -> tuple[bool, str]:
    """
    Check whether stored probe data needs refreshing.
    Returns (stale: bool, reason: str).
    Checks age first (free), then driver version (one nvidia-smi call).
    """
    probed_at_str = probe.get("probed_at", "")
    if not probed_at_str:
        return True, "no probe timestamp"

    try:
        probed_at = datetime.fromisoformat(probed_at_str)
        age = datetime.now(timezone.utc) - probed_at
        if age > timedelta(hours=PROBE_MAX_AGE_HOURS):
            hours = age.total_seconds() / 3600
            return True, f"cached probe is {hours:.0f}h old"
    except ValueError:
        return True, "unparseable probe timestamp"

    # Age fine — check driver version (fast: one nvidia-smi call)
    stored_driver = probe.get("gpu", {}).get("driver", "")
    if stored_driver:
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                live_driver = result.stdout.strip().splitlines()[0].strip()
                if live_driver and live_driver != stored_driver:
                    return True, f"driver changed ({stored_driver} → {live_driver})"
        except (OSError, subprocess.TimeoutExpired, IndexError):
            pass

    return False, ""

# =============================================================================
# Config assembly
# =============================================================================

def build_config(target: str) -> dict:
    """
    Build the config{} section. Merges DEFAULT_CONFIG with python versions
    from ai_lib_github (stub for now). Does not write — caller decides.
    """
    python_versions = {
        app: ai_lib_github.get_required_python(app) for app in ALL_APPS
    }
    return {
        **DEFAULT_CONFIG,
        "active_target":  target,
        "python":         python_versions,
        "torch_fallbacks": {},
    }

# =============================================================================
# App state helpers
# =============================================================================

def get_installed(data: dict, target: str) -> dict:
    """Extract installed{} records for the active target from JSON data."""
    return data.get("targets", {}).get(target, {}).get("installed", {})


def refresh_app_states(target: str, config: dict, probe: dict) -> dict:
    """
    Run ai_lib_apps.run() with pre-extracted installed records injected
    into config under the _installed key.
    """
    data = load_json()
    config_with_installed = dict(config)
    config_with_installed["_installed"] = get_installed(data, target)
    return ai_lib_apps.run(target, config_with_installed, probe)

# =============================================================================
# Status line (shown at top of every menu)
# =============================================================================

def print_status_line(target: str, probe: dict) -> None:
    gpu   = probe.get("gpu", {})
    tools = probe.get("tools", {})
    os_   = probe.get("os", {})

    gpu_str   = gpu.get("name", "no GPU")
    cuda_str  = gpu.get("torch_cuda", "?")
    debian    = os_.get("debian", "?")
    hostname  = os_.get("hostname", "?")
    nvcc      = tools.get("nvcc") or "none"

    print(f"  {dim(hostname)}:  {dim(gpu_str)}  {dim(cuda_str)}  "
          f"{dim(f'nvcc {nvcc}')}  {dim(f'Debian {debian}')}")
    print(f"  {dim('target:')} {dim(target)}  {cyan('[c]')} {dim('change')}")

# =============================================================================
# Menu item builders  — called by the renderer for dynamic section tokens
# =============================================================================

def build_app_menu_items(app_states: dict, opt_states: dict,
                         target: str, data: dict) -> list[MenuItem]:
    """Build MenuItem list for the Apps section."""
    items = []

    for app in ALL_APPS:
        state  = app_states.get(app, {})
        label  = state.get("label_long", app)
        action = state.get("label", "?")
        reason = state.get("reason", "")
        git    = state.get("git", {})

        git_str = ""
        if git.get("hash"):
            git_str = f"{git['hash']} · {git['date']}"

        opt_hint = ""
        opt = opt_states.get(app, {}).get("nunchaku", {})
        if opt.get("action") in ("install", "update"):
            latest = opt.get("latest", "")
            inst   = opt.get("installed", "")
            if opt["action"] == "update":
                opt_hint = yellow(f"  Nunchaku: {inst} → {latest}")
            else:
                opt_hint = yellow(f"  Nunchaku: {latest} available")

        pi_script = _postinstall_script(app)
        pi_run    = (data.get("targets", {}).get(target, {})
                        .get("installed", {}).get(app, {})
                        .get("postinstall_at", ""))
        pi_marker = ""
        if pi_script and not pi_run:
            pi_marker = yellow("  [+post]")
        elif pi_script and pi_run:
            pi_marker = dim(f"  [post✔ {pi_run[:10]}]")

        inst_rec  = (data.get("targets", {}).get(target, {})
                        .get("installed", {}).get(app, {}))
        dur       = inst_rec.get("duration_min", 0)
        dur_str   = dim(f"  last: {dur:.0f}min") if dur else ""

        detail_parts = []
        if reason:   detail_parts.append(reason)
        if git_str:  detail_parts.append(git_str)
        detail = "  ".join(detail_parts)

        display = (f"{label:<22} {green(action):<10}"
                   f"{opt_hint}{pi_marker}{dur_str}")

        items.append(MenuItem(
            label=display,
            detail=detail,
            action=lambda a=app, s=state: dispatch_app(a, s),
        ))

    return items


def build_launch_items(app_states: dict, target: str, config: dict) -> list[MenuItem]:
    """Build MenuItem list for the Launch section — installed apps only."""
    items = []

    for app in ALL_APPS:
        state   = app_states.get(app, {})
        venv_py = state.get("venv_python")
        if not venv_py or not Path(venv_py).exists():
            continue

        label = state.get("label_long", app)
        items.append(MenuItem(
            label=f"{label}",
            action=lambda a=app: launch_app(a),
            no_pause=True,   # launch runs its own process, no output to read
        ))

    return items


def build_postinstall_items(target: str, data: dict) -> list[MenuItem]:
    """
    Build MenuItem list for the Post-install section.
    Looks in postinstallers/ for .sh scripts.
    Stubs (SUPERSEDED marker) are included but routed to their Python replacement.
    """
    items = []
    for app in ALL_APPS:
        pi_script = _postinstall_script(app)
        if not pi_script:
            continue

        desc = "no description"
        try:
            for line in pi_script.read_text().splitlines():
                if line.strip().startswith("# DESCRIPTION:"):
                    desc = line.split("DESCRIPTION:", 1)[1].strip()
                    break
        except OSError:
            pass

        if _postinstall_is_stub(pi_script):
            stub_note = dim("  [→ py]")
        else:
            stub_note = ""

        pi_run  = (data.get("targets", {}).get(target, {})
                      .get("installed", {}).get(app, {})
                      .get("postinstall_at", ""))
        run_str = dim(f"  (last run {pi_run[:10]})") if pi_run else ""

        label_long = ai_lib_apps.APP_REGISTRY.get(app, {}).get("label", app)
        items.append(MenuItem(
            label=f"{label_long:<22} {desc}{stub_note}{run_str}",
            action=lambda a=app: run_postinstall(a),
        ))

    return items

# =============================================================================
# Menu renderer
# =============================================================================
#
# Loads ai_installer_menu.json and renders menus by id.
# Keeps all layout decisions in the JSON — Python only owns the render loop
# and the function registries below.
#
# Section label rules:
#   null or missing      → no header printed
#   starts with "CMNT:"  → treated as null (human annotation only)
#   any other string     → printed as section header
#
# Dynamic section tokens (string value for "items" key):
#   "launch"      → build_launch_items()
#   "apps"        → build_app_menu_items()
#   "postinstall" → build_postinstall_items()
#
# Static items (list value for "items" key):
#   each dict must have "id" matching a key in ITEM_REGISTRY
#
# show_if conditions:
#   Each section and each static item may have a "show_if" key naming a
#   condition from _CONDITIONS. Missing show_if = "always". Unknown condition
#   name → warn once and show the item (fail open).
#
# Detail strings may contain {token} placeholders substituted from ctx.
# =============================================================================

# =============================================================================
# Visibility conditions
# =============================================================================
# Each entry: condition_name → callable(ctx: dict) -> bool
# ctx is built fresh each render loop iteration — see run_menu_by_id().
#
# To add a new condition: one line here, reference by name in the JSON.
# =============================================================================

_CONDITIONS: dict[str, Callable[[dict], bool]] = {
    "always":          lambda ctx: True,
    "has_target":      lambda ctx: bool(ctx.get("target")),
    "has_drives":      lambda ctx: len(ctx.get("drives", [])) > 0,
    "has_any_app":     lambda ctx: ctx.get("n_installed", 0) > 0,
    "has_migration":   lambda ctx: ctx.get("migration_script_exists", False),
}


def _eval_condition(name: str | None, ctx: dict) -> bool:
    """
    Evaluate a show_if condition name against ctx.
    Missing name → True (always show).
    Unknown name → warn once, return True (fail open).
    """
    if not name:
        return True
    fn = _CONDITIONS.get(name)
    if fn is None:
        warn(f"Unknown show_if condition '{name}' in menu JSON — showing item anyway")
        return True
    return fn(ctx)


# =============================================================================
# Menu JSON load + validation
# =============================================================================

# Required menu ids — these must exist in the JSON or startup fails hard.
_REQUIRED_MENU_IDS = {"main", "install"}


def _load_and_validate_menu_json(item_registry_keys: set[str],
                                 section_builder_keys: set[str]) -> dict:
    """
    Load ai_installer_menu.json and validate it.

    Tier 1 — unrecoverable (exits with remediation message):
      - File missing or unparseable
      - No 'menus' array
      - A required menu id is missing

    Tier 2 — recoverable (warns, item/section skipped at render time):
      - Unknown item id
      - Unknown show_if condition
      - Unknown dynamic section token
      - Static item missing 'id' or 'label'

    Validation is purely advisory for Tier 2 — the renderer handles
    missing/unknown entries gracefully at runtime.
    """
    repo = "https://github.com/TrickBit/AI_TOOLS"  # fallback if not in JSON

    # ── Load ─────────────────────────────────────────────────────────────────
    if not MENU_JSON_PATH.exists():
        err(f"{MENU_JSON_PATH.name} not found.")
        print()
        print("  To restore it:")
        print(f"    git checkout AI_Tools/ai_installer_menu.json")
        print(f"  Or re-download from:")
        print(f"    {repo}/raw/main/AI_Tools/ai_installer_menu.json")
        sys.exit(1)

    try:
        data = json.loads(MENU_JSON_PATH.read_text())
    except json.JSONDecodeError as e:
        err(f"{MENU_JSON_PATH.name} is not valid JSON: {e}")
        print()
        print("  To restore it:")
        print(f"    git checkout AI_Tools/ai_installer_menu.json")
        print(f"  Or re-download from:")
        print(f"    {repo}/raw/main/AI_Tools/ai_installer_menu.json")
        sys.exit(1)

    repo = data.get("_repo", repo)

    # ── Tier 1: structural checks ─────────────────────────────────────────────
    menus = data.get("menus")
    if not menus or not isinstance(menus, list):
        err(f"{MENU_JSON_PATH.name}: no 'menus' array found.")
        print()
        print(f"  git checkout AI_Tools/ai_installer_menu.json")
        print(f"  or: {repo}/raw/main/AI_Tools/ai_installer_menu.json")
        sys.exit(1)

    found_ids = {m.get("id") for m in menus if isinstance(m, dict)}
    missing   = _REQUIRED_MENU_IDS - found_ids
    if missing:
        err(f"{MENU_JSON_PATH.name}: required menu id(s) missing: {', '.join(sorted(missing))}")
        print()
        print(f"  git checkout AI_Tools/ai_installer_menu.json")
        print(f"  or: {repo}/raw/main/AI_Tools/ai_installer_menu.json")
        sys.exit(1)

    # ── Tier 2: advisory checks ───────────────────────────────────────────────
    _warnings: list[str] = []

    for menu in menus:
        menu_id = menu.get("id", "?")
        for section in menu.get("sections", []):
            # Section-level show_if
            sec_cond = section.get("show_if")
            if sec_cond and sec_cond not in _CONDITIONS:
                _warnings.append(
                    f"menu '{menu_id}': unknown show_if '{sec_cond}' on section"
                )

            raw_items = section.get("items")
            if isinstance(raw_items, str):
                if raw_items not in section_builder_keys:
                    _warnings.append(
                        f"menu '{menu_id}': unknown dynamic token '{raw_items}'"
                    )
            elif isinstance(raw_items, list):
                for item in raw_items:
                    item_id   = item.get("id", "")
                    item_cond = item.get("show_if")
                    if not item_id:
                        _warnings.append(
                            f"menu '{menu_id}': static item missing 'id'"
                        )
                    elif item_id not in item_registry_keys:
                        _warnings.append(
                            f"menu '{menu_id}': unknown item id '{item_id}'"
                        )
                    if item_cond and item_cond not in _CONDITIONS:
                        _warnings.append(
                            f"menu '{menu_id}': unknown show_if '{item_cond}' on item '{item_id}'"
                        )

    for w in _warnings:
        warn(f"menu JSON: {w}")

    return data


def _label_is_visible(label: str | None) -> bool:
    """Return True if a section label should be printed."""
    if not label:
        return False
    if label.strip().startswith("CMNT:"):
        return False
    return True


def _fmt(text: str | None, ctx: dict) -> str:
    """Substitute {tokens} in text from ctx. Returns '' for None."""
    if not text:
        return ""
    try:
        return text.format_map(ctx)
    except (KeyError, ValueError):
        return text


def _build_item_registry(app_states: dict, opt_states: dict,
                         target: str, config: dict, probe: dict,
                         data: dict) -> dict[str, tuple[Callable, bool]]:
    """
    Return the static item registry: id → (callable, no_pause).
    no_pause=True for actions that own their own interactive loop —
    these redraw the screen themselves so no "Press Enter" needed after.
    Called once per menu render so lambdas close over current state.
    To add a new static item: one entry here + matching id in the JSON.
    """
    return {
        #                                                          no_pause
        "status":       (lambda: show_full_status(target, probe, app_states, opt_states, interactive=False), False),
        "switch":       (lambda: switch_target(config, probe),    True),
        "migration":    (run_migration,                           False),
        "install_menu": (lambda: run_menu_by_id("install", target, config, probe), True),
        "batch":        (lambda: batch_install(app_states),       True),
        "logs":         (lambda: view_logs(target),               False),
    }


def _build_section_builders(app_states: dict, opt_states: dict,
                             target: str, config: dict, probe: dict,
                             data: dict) -> dict[str, Callable[[], list[MenuItem]]]:
    """
    Return the dynamic section builder registry: token → zero-arg callable
    returning a list of MenuItems.
    To add a new dynamic section: one entry here + matching token string in JSON.
    """
    return {
        "launch":      lambda: build_launch_items(app_states, target, config),
        "apps":        lambda: build_app_menu_items(app_states, opt_states, target, data),
        "postinstall": lambda: build_postinstall_items(target, data),
    }


def _render_menu(menu_cfg: dict, ctx: dict,
                 item_registry: dict[str, Callable],
                 section_builders: dict[str, Callable]) -> list[MenuItem]:
    """
    Render a single menu config into a flat list of MenuItems with section
    headers printed as a side effect.
    Returns the ordered list — caller handles input and dispatch.

    Sections and items with show_if conditions that evaluate False are
    silently omitted. Empty sections (after filtering) are also omitted
    so their headers never appear without content.
    """
    items: list[MenuItem] = []
    i = 1

    for section in menu_cfg.get("sections", []):
        raw_label   = section.get("label")
        raw_detail  = section.get("detail")
        raw_items   = section.get("items")
        sec_show_if = section.get("show_if")

        # Section-level condition — skip entire section if false
        if not _eval_condition(sec_show_if, ctx):
            continue

        section_items: list[MenuItem] = []

        if isinstance(raw_items, str):
            # Dynamic token — builder returns its own filtered list
            builder = section_builders.get(raw_items)
            if builder:
                section_items = builder()
            else:
                warn(f"Unknown section token '{raw_items}' — skipping")

        elif isinstance(raw_items, list):
            # Static item list — filter by per-item show_if
            for item_cfg in raw_items:
                item_show_if = item_cfg.get("show_if")
                if not _eval_condition(item_show_if, ctx):
                    continue
                item_id     = item_cfg.get("id", "")
                item_label  = _fmt(item_cfg.get("label", item_id), ctx)
                item_detail = _fmt(item_cfg.get("detail", ""), ctx)
                entry = item_registry.get(item_id)
                if entry is None:
                    warn(f"No registry entry for item id '{item_id}' — skipping")
                    continue
                action, no_pause = entry
                section_items.append(MenuItem(
                    label=item_label,
                    detail=item_detail,
                    action=action,
                    no_pause=no_pause,
                ))

        # Skip empty sections (e.g. Launch when no apps installed,
        # Post-install when no postinstall scripts exist)
        if not section_items:
            continue

        # Print section header
        if _label_is_visible(raw_label):
            label_str  = _fmt(raw_label, ctx)
            detail_str = f"  {dim(_fmt(raw_detail, ctx))}" if raw_detail else ""
            print()
            print(f"  {bold(label_str)}{detail_str}")

        # Print items
        for item in section_items:
            item.number = i
            det = f"  {dim(item.detail)}" if item.detail else ""
            print(f"  {cyan(f'{i:2d}')}. {item.label}{det}")
            i += 1
            items.append(item)

    return items


def run_menu_by_id(menu_id: str, target: str, config: dict, probe: dict) -> None:
    """
    Main menu loop for a given menu id from ai_installer_menu.json.
    Validates JSON on first call, refreshes all state on each iteration.
    Pre-hook (if set in JSON) is called once before the loop.
    """
    # Build placeholder registries just for validation key sets
    _item_keys    = {"status", "switch", "migration", "install_menu", "batch", "logs"}
    _builder_keys = {"launch", "apps", "postinstall"}

    menu_data   = _load_and_validate_menu_json(_item_keys, _builder_keys)
    menus_by_id = {m["id"]: m for m in menu_data.get("menus", [])}

    if menu_id not in menus_by_id:
        err(f"Menu id '{menu_id}' not found in {MENU_JSON_PATH.name}")
        return

    menu_cfg = menus_by_id[menu_id]

    # Pre-hook — called once before the loop
    pre_hook_name = menu_cfg.get("pre")
    if pre_hook_name:
        pre_fn = _PRE_POST_REGISTRY.get(pre_hook_name)
        if pre_fn:
            pre_fn(target, config, probe)
        else:
            warn(f"Pre-hook '{pre_hook_name}' not in registry — skipping")

    back_label = menu_cfg.get("back_label", "Back")

    while True:
        # Refresh all state every iteration
        app_states = refresh_app_states(target, config, probe)
        opt_states = ai_lib_optional.run(target, app_states)
        data       = load_json()

        # Count installed apps for conditions and hint
        n_installed = sum(
            1 for app in ALL_APPS
            if data.get("targets", {}).get(target, {})
                   .get("installed", {}).get(app, {}).get("status") == "ok"
        )
        actionable_states = {"fresh", "update", "rebuild_torch", "rebuild_python",
                             "rebuild", "missing", "unknown"}
        n_actionable = sum(
            1 for app in ALL_APPS
            if app_states.get(app, {}).get("state", "unknown") in actionable_states
        )
        install_hint = (
            f"{n_actionable} app{'s' if n_actionable != 1 else ''} need attention"
            if n_actionable else "all apps up to date"
        )

        # Context dict — all {token} substitutions + all condition inputs
        ctx = {
            "target":                   target,
            "hostname":                 probe.get("os", {}).get("hostname", "Jethro"),
            "install_hint":             install_hint,
            "probe_age_str":            "",
            "n_installed":              n_installed,
            "drives":                   probe.get("drives", []),
            "migration_script_exists":  (SCRIPT_DIR / "ai_migrate_resources.sh").exists(),
        }

        # Build registries closed over current state
        item_registry    = _build_item_registry(app_states, opt_states,
                                                target, config, probe, data)
        section_builders = _build_section_builders(app_states, opt_states,
                                                   target, config, probe, data)

        # Clear screen and print header
        os.system("clear")
        page_title = _fmt(menu_cfg.get("title", menu_id), ctx)
        _app_title = "ai_installer.py  —  Jethro AI stack"
        _inner = 60
        _pad_l = max(0, (_inner - len(_app_title)) // 2)
        _pad_r = max(0, _inner - len(_app_title) - _pad_l)
        print()
        print(bold(f"  ╔{'═' * _inner}╗"))
        print(bold(f"  ║{' ' * _pad_l}{_app_title}{' ' * _pad_r}║"))
        print(bold(f"  ╚{'═' * _inner}╝"))
        print_status_line(target, probe)
        print()
        print(f"  {bold(page_title.title())}")

        # Render sections — prints headers and items as side effect
        # print()
        items = _render_menu(menu_cfg, ctx, item_registry, section_builders)

        # Footer
        print()
        print(f"  {cyan(' q')}. {back_label}")
        print()

        # Input
        try:
            choice = input("  Choice: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if choice == "q":
            break

        if choice == "c":
            print()
            switch_target(config, probe)
            continue

        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(items):
                print()
                item = items[idx - 1]
                item.action()
                if not item.no_pause:
                    try:
                        input("\n  Press Enter to continue...")
                    except (EOFError, KeyboardInterrupt):
                        pass
                continue

        warn(f"Enter a number 1–{len(items)} or q.")
        try:
            input("  Press Enter to continue...")
        except (EOFError, KeyboardInterrupt):
            pass

    # Post-hook
    post_hook_name = menu_cfg.get("post")
    if post_hook_name:
        post_fn = _PRE_POST_REGISTRY.get(post_hook_name)
        if post_fn:
            post_fn(target, config, probe)


# =============================================================================
# Pre/post hook registry — name → callable(target, config, probe)
# To add a hook: one entry here, reference by name in ai_installer_menu.json.
# =============================================================================
_PRE_POST_REGISTRY: dict[str, Callable] = {
    # "probe_torch_constraints": probe_torch_constraints,   # session 18+
}

# =============================================================================
# App dispatch — calls bash installers via subprocess
# =============================================================================

def dispatch_app(app: str, state: dict) -> None:
    """Run the appropriate bash installer for an app based on its state."""
    app_state = state.get("state", "unknown")

    if app_state == "fresh":
        _run_installer(app)
    elif app_state == "update":
        _run_installer(app, "--update")
    elif app_state == "rebuild_torch":
        print()
        warn(f"This will rebuild torch for {app}.")
        warn(state.get("reason", ""))
        try:
            confirm = input("  Proceed? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return
        if confirm == "y":
            _run_installer(app, "--rebuild-torch")
    elif app_state == "rebuild_python":
        print()
        warn(f"This will rebuild {app} with a different Python version.")
        warn(state.get("reason", ""))
        try:
            confirm = input("  Proceed? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return
        if confirm == "y":
            _run_installer(app)
    else:
        warn(f"Unknown state '{app_state}' for {app} — nothing to do.")


def _record_install_from_venv(app: str, started_at: str = "",
                              duration_min: float = 0.0) -> None:
    """
    Read actual python and torch versions from the app's venv and write
    the install record via ai_config. Called after a successful installer run.
    """
    from ai_lib_apps import APP_REGISTRY
    data   = ai_config.load_all()
    target = data.get("config", {}).get("active_target", "")
    if not target:
        warn(f"No active target — cannot record install for {app}")
        return

    reg     = APP_REGISTRY.get(app, {})
    app_dir = Path(target) / data.get("config", {}).get("apps_subdir", "AI_Apps") / reg.get("disk_name", app)

    python_ver = ""
    torch_ver  = ""
    for rel in reg.get("venv_paths", []):
        py = app_dir / rel
        if py.exists():
            try:
                r = subprocess.run(
                    [str(py), "-c",
                     "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"],
                    capture_output=True, text=True, timeout=10
                )
                python_ver = r.stdout.strip()
                r2 = subprocess.run(
                    [str(py), "-c", "import torch; print(torch.__version__)"],
                    capture_output=True, text=True, timeout=10
                )
                torch_ver = r2.stdout.strip()
            except (OSError, subprocess.TimeoutExpired):
                pass
            break

    ok = ai_config.record_install(app, status="ok", python=python_ver,
                                  torch=torch_ver, started_at=started_at,
                                  duration_min=duration_min)
    if ok:
        info(f"Install record written: {app} python={python_ver} torch={torch_ver}")
    else:
        warn(f"Could not write install record for {app}")


def _collect_wheels_from_venv(app: str) -> None:
    """
    After a successful install, scan the app venv for heavy compiled packages
    and cache them into AI_Collected_Wheels/localbuild/.
    Non-fatal — logged but does not affect install record.
    """
    from ai_lib_apps import APP_REGISTRY
    from ai_lib_wheels import localbuild_dir, HEAVY_PACKAGES
    data    = ai_config.load_all()
    target  = data.get("config", {}).get("active_target", "")
    if not target:
        return

    reg     = APP_REGISTRY.get(app, {})
    app_dir = (Path(target)
               / data.get("config", {}).get("apps_subdir", "AI_Apps")
               / reg.get("disk_name", app))

    venv_dir = None
    for rel in reg.get("venv_paths", []):
        py = app_dir / rel
        if py.exists():
            venv_dir = py.parent.parent
            break

    if not venv_dir or not venv_dir.exists():
        return

    info(f"Collecting heavy wheels from {app} venv...")
    try:
        results = ai_collect_wheels.collect_auto_from_venv(venv_dir, verbose=False)
        ok_count = sum(1 for v in results.values() if v)
        if ok_count:
            good(f"Collected {ok_count} wheel(s) → localbuild/")
        for pkg, ok in results.items():
            if ok:
                lb = localbuild_dir()
                wheels = sorted(lb.glob(f"{pkg.replace('-', '_')}-*.whl"))
                whl_name = wheels[-1].name if wheels else ""
                ai_config.record_wheel_build(pkg, status="ok", wheel_name=whl_name)
    except Exception as e:
        warn(f"Wheel collection failed (non-fatal): {e}")


def _run_installer(app: str, flag: str = "") -> None:
    """
    Call the bash installer for an app via subprocess.
    Installers live in installers/ — not the AI_Tools root.
    """
    script = INSTALLERS_DIR / f"ai_{app}_install.sh"
    if not script.exists():
        err(f"Installer not found: {script}")
        return

    cmd = [str(script)]
    if flag:
        cmd.append(flag)

    if not flag:
        from ai_lib_apps import APP_REGISTRY
        reg     = APP_REGISTRY.get(app, {})
        data    = ai_config.load_all()
        target  = data.get("config", {}).get("active_target", "")
        appdir  = (Path(target)
                   / data.get("config", {}).get("apps_subdir", "AI_Apps")
                   / reg.get("disk_name", app))
        if target and not appdir.exists():
            try:
                appdir.mkdir(parents=True, exist_ok=True)
                info(f"Created {appdir}")
            except OSError as e:
                warn(f"Could not create {appdir}: {e}")

    info(f"Running {script.name} {flag}".strip())
    print()

    import time
    t_start    = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()

    try:
        result = subprocess.run(cmd, env={**os.environ})
        duration_min = (time.monotonic() - t_start) / 60
        print()
        if result.returncode == 0:
            good(f"{app} installer finished.  ({duration_min:.1f} min)")
            _record_install_from_venv(app, started_at=started_at,
                                      duration_min=duration_min)
            _collect_wheels_from_venv(app)
        else:
            err(f"{app} installer exited with code {result.returncode}.")
    except OSError as e:
        err(f"Could not run installer: {e}")


def launch_app(app: str) -> None:
    """
    Launch an app via its runner script.
    Runners live in runners/ — not the AI_Tools root.
    Runner name for comfyui is ai_comfy (historical).
    """
    runner_name = "ai_comfy" if app == "comfyui" else f"ai_{app}"
    runner = RUNNERS_DIR / runner_name
    if not runner.exists():
        err(f"Runner not found: {runner}")
        return

    info(f"Launching {app}...")
    try:
        subprocess.run([str(runner)], env={**os.environ})
    except OSError as e:
        err(f"Could not launch {app}: {e}")


def run_postinstall(app: str) -> None:
    """
    Run the post-install script for an app.
    If the .sh is a stub (SUPERSEDED marker), routes to the Python replacement.
    Records postinstall_at timestamp in JSON on success.
    """
    script = _postinstall_script(app)
    if not script:
        err(f"Post-install script not found for {app} in postinstallers/")
        return

    if _postinstall_is_stub(script):
        py_script = _postinstall_py(app)
        if not py_script:
            err(f"Stub postinstall found for {app} but no .py replacement in postinstallers/")
            return
        info(f"Running Python post-install for {app}...")
        try:
            result = subprocess.run(
                [sys.executable, str(py_script), "setup"],
                env={**os.environ}
            )
        except OSError as e:
            err(f"Could not run Python post-install: {e}")
            return
    else:
        info(f"Running post-install for {app}...")
        try:
            result = subprocess.run(["bash", str(script)], env={**os.environ})
        except OSError as e:
            err(f"Could not run post-install: {e}")
            return

    if result.returncode == 0:
        good(f"Post-install complete for {app}.")
        now = datetime.now(timezone.utc).isoformat()
        data = load_json()
        target = data.get("config", {}).get("active_target", "")
        if target:
            (data.setdefault("targets", {})
                 .setdefault(target, {})
                 .setdefault("installed", {})
                 .setdefault(app, {})
                 ["postinstall_at"]) = now
            write_json(data)
    else:
        err(f"Post-install exited with code {result.returncode}.")


_ACTION_LABELS = {
    "fresh":          "Install",
    "missing":        "Install",
    "update":         "Update",
    "rebuild_torch":  "Rebuild torch",
    "rebuild_python": "Rebuild",
    "rebuild":        "Rebuild",
    "current":        "Up to date",
    "ok":             "Up to date",
    "unknown":        "Install",
    "constrained":    "Update",
}


def batch_install(app_states: dict) -> None:
    """
    Batch install / update — interactive checkbox picker.
    Defaults: all ticked on fresh system, only actionable apps ticked otherwise.
    """
    from ai_lib_apps import APP_REGISTRY

    ACTIONABLE = {"fresh", "update", "rebuild_torch", "rebuild_python", "rebuild", "missing", "unknown"}
    fresh_system = all(
        app_states.get(a, {}).get("state", "unknown") in ("unknown", "fresh", "missing")
        for a in ALL_APPS
    )

    candidates = [a for a in ALL_APPS if a in APP_REGISTRY]
    ticked = []
    for app in candidates:
        state = app_states.get(app, {}).get("state", "unknown")
        ticked.append(True if fresh_system else state in ACTIONABLE)

    def _free_gb(tgt: str) -> float:
        try:
            import shutil
            return shutil.disk_usage(tgt).free / 1024 ** 3
        except OSError:
            return 0.0

    def _est_str(app: str) -> str:
        reg   = APP_REGISTRY[app]
        state = app_states.get(app, {}).get("state", "unknown")
        disk  = reg.get("est_disk_gb", 0)
        mins  = reg.get("est_min", 0)
        note  = reg.get("est_note")
        if state == "update":
            est = "~2-5 min"
        elif state.startswith("rebuild"):
            est = f"~{mins} min (rebuild)"
        else:
            est = f"~{disk}GB  ~{mins} min"
        return est + (f"  {note}" if note else "")

    def _totals(sel: list) -> str:
        total_disk = sum(
            APP_REGISTRY[a].get("est_disk_gb", 0)
            for a, s in zip(candidates, sel)
            if s and app_states.get(a, {}).get("state", "unknown")
               not in ("update", "current", "ok")
        )
        total_min = sum(APP_REGISTRY[a].get("est_min", 0)
                        for a, s in zip(candidates, sel) if s)
        n = sum(sel)
        return f"Selected: {n} app{'s' if n != 1 else ''}  ~{total_disk}GB disk  ~{total_min} min estimated"

    data   = ai_config.load_all()
    target = data.get("config", {}).get("active_target", "")

    while True:
        os.system("clear")
        print()
        print(bold("  Batch install / update"))
        print(dim("  ─────────────────────────────────────────────────────────"))
        print(dim("  space/number = toggle  a = all  n = none  enter = run  q = cancel"))
        print()

        for i, app in enumerate(candidates):
            reg       = APP_REGISTRY[app]
            state     = app_states.get(app, {}).get("state", "unknown")
            lbl       = reg.get("label", app)
            action    = _ACTION_LABELS.get(state, state)
            check     = green("✔") if ticked[i] else dim("○")
            est       = _est_str(app)
            print(f"  {check}  {bold(str(i+1))}.  {lbl:<22} {action:<16}{dim(est)}")

        print()
        free = _free_gb(target) if target else 0.0
        print(f"  {dim(_totals(ticked))}")
        if target:
            print(f"  {dim(f'Free on {target}: {free:.0f}GB')}")
        print()

        try:
            key = input("  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return

        if key == "q":
            return
        elif key == "a":
            ticked = [True] * len(candidates)
        elif key == "n":
            ticked = [False] * len(candidates)
        elif key == "":
            selected = [app for app, t in zip(candidates, ticked) if t]
            if not selected:
                warn("Nothing selected.")
                input("  Press enter to go back...")
                return
            print()
            info(f"Running batch for: {', '.join(selected)}")
            print()
            for app in selected:
                dispatch_app(app, app_states.get(app, {}))
                print()
            good("Batch complete.")
            input("  Press enter to continue...")
            return
        else:
            try:
                idx = int(key) - 1
                if 0 <= idx < len(candidates):
                    ticked[idx] = not ticked[idx]
            except ValueError:
                pass


def run_migration() -> None:
    """
    Run resource migration — scan first, then offer to act.
    Scan (no args) shows what would change. User chooses to run or cancel.
    """
    script = SCRIPT_DIR / "ai_migrate_resources.sh"
    if not script.exists():
        err(f"Migration script not found: {script.name}")
        return

    # Step 1 — scan (read-only, shows report)
    info("Scanning — no changes yet...")
    print()
    try:
        result = subprocess.run(["bash", str(script)], env={**os.environ})
    except OSError as e:
        err(f"Could not run migration: {e}")
        return

    if result.returncode != 0:
        err(f"Scan exited with code {result.returncode}.")
        return

    # Step 2 — offer to act
    print()
    try:
        confirm = input("  Run migration now? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    if confirm != "y":
        return

    # Step 3 — migrate
    print()
    info("Running migration...")
    print()
    try:
        subprocess.run(["bash", str(script), "--migrate"], env={**os.environ})
    except OSError as e:
        err(f"Could not run migration: {e}")


def show_full_status(target: str, probe: dict, app_states: dict,
                     opt_states: dict, interactive: bool = True) -> None:
    """Print a full status dashboard."""
    header("Full status")

    gpu   = probe.get("gpu", {})
    tools = probe.get("tools", {})
    os_   = probe.get("os", {})

    print(f"  {'GPU:':<22} {gpu.get('name', 'not found')}")
    print(f"  {'VRAM:':<22} {gpu.get('vram_gb', 0)} GB")
    print(f"  {'Driver:':<22} {gpu.get('driver', '?')}")
    print(f"  {'Max CUDA:':<22} {gpu.get('cuda_max', '?')} → torch {gpu.get('torch_cuda', '?')}")
    print(f"  {'nvcc:':<22} {tools.get('nvcc') or 'none'}")
    print(f"  {'gcc-12:':<22} {tools.get('gcc12', False)}")
    print(f"  {'pyenv:':<22} {tools.get('pyenv', False)}")
    print(f"  {'Debian:':<22} {os_.get('debian', '?')}")
    print(f"  {'Active target:':<22} {target}")

    drives = probe.get("drives", [])
    if drives:
        print()
        print("  Mounted filesystems:")
        for d in drives:
            mount    = d["mount"]
            active   = green(" ← active") if mount == target else ""
            size_str = _disk_usage_str(mount)
            print(f"    {mount:<36} {size_str}{active}")

    print()
    header("App states")
    for app in ALL_APPS:
        state  = app_states.get(app, {})
        label  = state.get("label_long", app)
        action = state.get("label", "?")
        reason = state.get("reason", "")
        git    = state.get("git", {})
        git_str = f"{git['hash']} · {git['date']}" if git.get("hash") else ""
        reason_str = dim(f"  {reason}") if reason else ""
        git_str2   = dim(f"  [{git_str}]") if git_str else ""
        print(f"  {label:<22}  {action:<18}{reason_str}{git_str2}")

    if interactive:
        try:
            input("\n  Press Enter to continue...")
        except (EOFError, KeyboardInterrupt):
            pass

# =============================================================================
# Target switching (mid-session)
# =============================================================================

def switch_target(config: dict, probe: dict) -> None:
    """Change active target drive mid-session."""
    data       = load_json()
    drives     = probe.get("drives", [])
    targets    = data.get("targets", {})
    new_target = select_target(drives, targets)

    if not new_target:
        info("Target unchanged.")
        return

    config["active_target"] = new_target
    update_json({"config": {"active_target": new_target}})
    good(f"Active target: {new_target}")

# =============================================================================
# Log viewer
# =============================================================================

def view_logs(target: str) -> None:
    """Browse install logs for the active target."""
    data = load_json()
    runs = data.get("targets", {}).get(target, {}).get("runs", [])

    if not runs:
        info("No run logs found for this target.")
        return

    header("Install logs")
    for i, run in enumerate(reversed(runs[-20:]), 1):
        ts    = run.get("timestamp", "?")[:19].replace("T", " ")
        label = run.get("label", "?")
        dur   = run.get("duration_min", 0)
        dur_str = f"  {dim(f'{dur:.1f}min')}" if dur else ""
        print(f"  {dim(f'{i:2d}.')} {ts}  {label}{dur_str}")

    print()
    info("(Showing last 20 entries)")

# =============================================================================
# First-run flow  (no JSON exists)
# =============================================================================

def _first_run_flow(probe: dict) -> None:
    """
    First-run welcome: no JSON exists.
    Shows GPU/drives, lists apps, offers Install or Quit.
    On Install: target select → write JSON → enter install menu.
    """
    os.system("clear")
    print()
    print(bold("  ╔════════════════════════════════════════════════════════════╗"))
    print(bold("  ║                   Welcome to AI Tools                     ║"))
    print(bold("  ╚════════════════════════════════════════════════════════════╝"))
    print()

    gpu = probe.get("gpu", {})
    if gpu.get("name"):
        good(f"{gpu['name']}  |  driver {gpu['driver']}  |  {gpu['torch_cuda']}")
    else:
        warn("No GPU detected — check nvidia-smi")

    drives = probe.get("drives", [])
    if drives:
        print()
        info("Drives found:")
        for d in drives:
            ai_marker = green("  [AI dirs found]") if d.get("has_ai") else ""
            size_str  = _disk_usage_str(d["mount"])
            print(f"    {d['mount']:<36} {d.get('fs_type',''):<6}  {size_str}{ai_marker}")

    print()
    print(bold("  No apps installed yet."))
    print()
    print("  Apps available to install:")
    from ai_lib_apps import APP_REGISTRY
    for app in ALL_APPS:
        reg  = APP_REGISTRY.get(app, {})
        lbl  = reg.get("label", app)
        disk = reg.get("est_disk_gb", "?")
        mins = reg.get("est_min", "?")
        print(f"    {lbl:<30}  ~{disk}GB  ~{mins} min")

    print()
    print(f"  {cyan(' 1')}. Install apps")
    print(f"  {cyan(' 2')}. Quit")
    print()

    while True:
        try:
            choice = input("  Choice: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)

        if choice in ("2", "q", "quit"):
            print()
            good("Bye.")
            sys.exit(0)

        if choice in ("1", ""):
            break

        warn("Enter 1 or 2.")

    # Select target
    target = select_target(drives, known_targets={})
    if not target:
        err("No target selected.")
        sys.exit(1)

    good(f"Target: {target}")

    # Write fresh JSON
    config = build_config(target)
    now    = datetime.now(timezone.utc).isoformat()
    data = {
        "_comment": f"{probe.get('os', {}).get('hostname', 'Jethro')} — ai_installer — generated {now[:10]}",
        "meta":     {"version": "2.0", "approved": True, "approved_at": now},
        "config":   config,
        "probe":    probe,
        "targets":  {
            target: {
                "installed": {
                    app: {"status": "unknown", "installed_at": None,
                          "python": None, "torch": None}
                    for app in ALL_APPS
                },
                "runs": [],
            }
        },
    }
    write_json(data)
    good("Config written.")
    ai_config.write_probe(probe)

    run_menu_by_id("install", target, config, probe)

# =============================================================================
# --init flow
# =============================================================================

def cmd_init() -> None:
    """
    Force reinit: back up old JSON, probe, select target, write clean v2 JSON.
    For scripted or force-reinit use. Normal first-run uses _first_run_flow().
    """
    header("ai_installer — initial setup")

    old_conductor = SCRIPT_DIR / "ai_conductor.json"
    if old_conductor.exists():
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = old_conductor.with_name(f"ai_conductor.json.bak.{ts}")
        old_conductor.rename(bak)
        good(f"Backed up ai_conductor.json → {bak.name}")

    if JSON_PATH.exists():
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = JSON_PATH.with_name(f"ai_installer.json.bak.{ts}")
        JSON_PATH.rename(bak)
        good(f"Backed up ai_installer.json → {bak.name}")

    probe = run_probe(write=False)

    drives  = probe.get("drives", [])
    target  = select_target(drives, known_targets={})
    if not target:
        err("No target selected. Run ai_installer.py --init again.")
        sys.exit(1)

    good(f"Target: {target}")

    config = build_config(target)
    now    = datetime.now(timezone.utc).isoformat()

    data = {
        "_comment":  f"{probe.get('os', {}).get('hostname', 'Jethro')} — ai_installer — generated {now[:10]}",
        "meta":      {"version": "2.0", "approved": True, "approved_at": now},
        "config":    config,
        "probe":     probe,
        "targets":   {
            target: {
                "installed": {
                    app: {"status": "unknown", "installed_at": None,
                          "python": None, "torch": None}
                    for app in ALL_APPS
                },
                "runs": [],
            }
        },
    }
    write_json(data)
    good(f"Written {JSON_PATH.name}")
    print()

    run_menu_by_id("main", target, config, probe)

# =============================================================================
# --select flow
# =============================================================================

def cmd_select() -> None:
    """Change active target drive, then open menu."""
    probe  = run_probe(write=True)
    data   = load_json()
    drives = probe.get("drives", [])

    target = select_target(drives, data.get("targets", {}))
    if not target:
        err("No target selected.")
        sys.exit(1)

    good(f"Target: {target}")

    data   = load_json()
    config = data.get("config", build_config(target))
    config["active_target"] = target

    if target not in data.get("targets", {}):
        data.setdefault("targets", {})[target] = {
            "installed": {
                app: {"status": "unknown", "installed_at": None,
                      "python": None, "torch": None}
                for app in ALL_APPS
            },
            "runs": [],
        }

    data["config"] = config
    write_json(data)

    run_menu_by_id("main", target, config, probe)

# =============================================================================
# probe subcommand
# =============================================================================

def cmd_probe() -> None:
    """Probe system and print summary, then exit."""
    probe = run_probe(write=True)

    print()
    header("System probe summary")
    gpu   = probe.get("gpu", {})
    tools = probe.get("tools", {})
    os_   = probe.get("os", {})

    print(f"  {'GPU:':<22} {gpu.get('name', 'not found')}")
    print(f"  {'VRAM:':<22} {gpu.get('vram_gb', 0)} GB")
    print(f"  {'Driver:':<22} {gpu.get('driver', '?')}")
    print(f"  {'Max CUDA:':<22} {gpu.get('cuda_max', '?')} → torch {gpu.get('torch_cuda', '?')}")
    print(f"  {'SageAttention v2:':<22} {gpu.get('sage_v2_capable', False)}")
    print(f"  {'nvcc:':<22} {tools.get('nvcc') or 'none'}")
    print(f"  {'nvcc path:':<22} {tools.get('nvcc_path') or 'none'}")
    print(f"  {'gcc-12:':<22} {tools.get('gcc12', False)}")
    print(f"  {'git:':<22} {tools.get('git', False)}")
    print(f"  {'pyenv:':<22} {tools.get('pyenv', False)}")
    print(f"  {'Debian:':<22} {os_.get('debian', '?')}")
    print(f"  {'Hostname:':<22} {os_.get('hostname', '?')}")

    drives = probe.get("drives", [])
    if drives:
        print()
        print("  Drives (hardlink-capable /mnt/* mounts):")
        for d in drives:
            ai_str   = green(" [AI dirs found]") if d.get("has_ai") else ""
            size_str = _disk_usage_str(d["mount"])
            print(f"    {d['mount']:<36} {d.get('fs_type',''):<8} {size_str}{ai_str}")

# =============================================================================
# Normal startup (no flags)
# =============================================================================

def cmd_normal() -> None:
    """
    Normal startup: load JSON, verify target, check probe staleness, open menu.
    If no JSON: first-run welcome flow (no --init needed for interactive use).
    If target not mounted: warn and suggest --select.
    """
    data = load_json()

    # ── First run: no JSON ────────────────────────────────────────────────────
    if not data:
        info("First run — probing system...")
        probe = ai_lib_probe.run()
        gpu   = probe.get("gpu", {})
        if gpu.get("name"):
            good(f"{gpu['name']}  |  driver {gpu['driver']}  |  {gpu['torch_cuda']}")
        _first_run_flow(probe)
        return

    # ── Existing JSON — verify target ─────────────────────────────────────────
    config = data.get("config", {})
    target = config.get("active_target", "")

    if not target:
        err("No active target set in config.")
        info("Run:  ai_installer.py --select")
        sys.exit(1)

    if not Path(target).is_mount():
        warn(f"Target drive not mounted: {target}")
        info("Run:  ai_installer.py --select  to choose a different drive")
        sys.exit(1)

    # ── Probe staleness check ─────────────────────────────────────────────────
    probe = data.get("probe") or {}
    stale, reason = _probe_is_stale(probe)
    if stale:
        info(f"Re-probing ({reason})...")
        probe = run_probe(write=True)

    run_menu_by_id("main", target, config, probe)


def cmd_target(mount: str | None = None) -> None:
    """Show or set the active target drive."""
    data    = ai_config.load_all()
    config  = data.get("config", {})
    current = config.get("active_target", "none")

    if mount is None:
        print(f"  Active target: {current}")
        return

    probe  = run_probe(write=False)
    drives = probe.get("drives", [])
    mounts = [d["mount"] for d in drives]

    if mount not in mounts:
        err(f"{mount} is not a mounted hardlink-capable filesystem.")
        info(f"Available: {', '.join(mounts) if mounts else 'none found'}")
        sys.exit(1)

    config["active_target"] = mount
    if mount not in data.get("targets", {}):
        data.setdefault("targets", {})[mount] = {
            "installed": {
                app: {"status": "unknown", "installed_at": None,
                      "python": None, "torch": None}
                for app in ALL_APPS
            },
            "runs": [],
        }
    data["config"] = config
    write_json(data)
    good(f"Active target set to: {mount}")


def cmd_status() -> None:
    """Print app status for all apps, then exit."""
    probe      = run_probe(write=False)
    config     = ai_config.load_all()
    target     = config.get("config", {}).get("active_target", "")
    app_states = ai_lib_apps.run(target, config, probe)
    opt_states = ai_lib_optional.run(target, app_states)
    show_full_status(target, probe, app_states, opt_states, interactive=False)


def cmd_comfyui(args: list) -> None:
    """
    Dispatch ComfyUI workflow pack subcommands to ai_comfyui_postinstall.py.
    Commands: setup, reinstall <id>, status
    """
    py_script = POSTINSTALLERS_DIR / "ai_comfyui_postinstall.py"
    if not py_script.exists():
        err(f"ComfyUI postinstall not found: {py_script}")
        info("Expected: AI_Tools/postinstallers/ai_comfyui_postinstall.py")
        sys.exit(1)

    cmd = [sys.executable, str(py_script)] + args
    try:
        result = subprocess.run(cmd, env={**os.environ})
        sys.exit(result.returncode)
    except OSError as e:
        err(f"Could not run ComfyUI postinstall: {e}")
        sys.exit(1)

# =============================================================================
# Entry point
# =============================================================================

def main() -> None:
    args = sys.argv[1:]

    if not args:
        cmd_normal()

    elif args[0] == "--init":
        cmd_init()

    elif args[0] == "--select":
        cmd_select()

    elif args[0] == "probe":
        cmd_probe()

    elif args[0] == "status":
        cmd_status()

    elif args[0] == "target":
        cmd_target(args[1] if len(args) > 1 else None)

    elif args[0] == "comfyui":
        cmd_comfyui(args[1:])

    elif args[0] == "--target":
        err("--target is not yet implemented.")
        info("Use --select to change the active target interactively.")
        sys.exit(1)

    elif args[0] in ("--help", "-h"):
        print(__doc__)

    else:
        err(f"Unknown argument: {args[0]}")
        print("Usage: ai_installer.py [--init | --select | probe | status | target | comfyui]")
        sys.exit(1)


if __name__ == "__main__":
    main()
