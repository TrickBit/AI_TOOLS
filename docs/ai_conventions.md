# AI Stack — Coding Conventions

## Purpose

Conventions for the AI_Tools script suite on Jethro. Follow these when adding
new scripts, extending existing ones, or porting logic between bash and Python.
The goal is readable, maintainable, extensible code without tribal knowledge.

Reference: `claude_project.md` for project overview and architecture.

---

## Git Rules — Read This First

**Never run any git write operation without explicitly asking Martin first.**

This means never: `git add`, `git commit`, `git push`, `git pull`, `git merge`,
`git rebase`, `git reset`, `git checkout` (file restore), `git stash`.

Read-only is fine without asking: `git status`, `git log`, `git diff`, `git show`.

Code that is not working or not reviewed does not go to the repo.
Martin commits only when things are known-good.
Repo: https://github.com/TrickBit/AI_TOOLS

---

## Language Split

**Python owns:**
- All intelligence — system probe, app state detection, version comparison, API calls
- `ai_installer.json` — sole writer, all sections, via `ai_config.py`
- GitHub API calls — all go through `ai_lib_github.py`
- Optional package detection (release info, wheel availability)
- Any logic requiring real data structures, semver comparison, or network calls
- Menu layout rendering — driven by `ai_installer_menu.json`

**Bash owns:**
- Process launching — installers, runners, venv activation
- Environment setup — env vars exported for child processes
- `ai_config.sh` — reads JSON via `ai_config.py` CLI, exports vars
- `ai_*_install.sh` — install/update/rebuild logic
- `ai_*` runners — thin launch wrappers

**The JSON file is the interface between them.**
Python writes. Bash reads via `ai_config.py get`. They never both write.

---

## JSON Structure

Single file: `ai_installer.json`

```json
{
  "_comment": "<hostname> — ai_installer — generated <date>",
  "meta":    { "version": "2.0", "approved": true, "approved_at": "..." },
  "config":  {
    "port": 7860,
    "apps_subdir":       "AI_Apps",
    "resources_subdir":  "AI-Shared-Resources",
    "outputs_subdir":    "AI_Outputs",
    "work_subdir":       "AI_Work",
    "wheels_drive":      "/mnt/BACKUP_4.0_TB",
    "active_target":     "/mnt/1TB_SSD",
    "python": {
      "automatic": "3.10.6",
      "wan2gp": "3.11.9",
      "frampackstudio": "3.11.9",
      "invokeai": "3.12.12",
      "comfyui": "3.12.12"
    },
    "torch_fallbacks": {}
  },
  "probe": {
    "probed_at": "...",
    "gpu":   { "name": "...", "vram_gb": 12, "driver": "610.43.02",
               "driver_major": 610, "cuda_max": "13.0",
               "torch_cuda": "cu130", "torch_index": "...",
               "sage_v2_capable": true },
    "tools": { "nvcc": "13.3.33", "nvcc_path": "/usr/local/cuda-13/bin/nvcc",
               "gcc12": true, "git": true, "jq": true,
               "pyenv": true, "pyenv_root": "..." },
    "os":    { "debian": "13.2", "hostname": "Jethro" },
    "drives": [ { "mount": "/mnt/...", "fs_type": "ext4", "has_ai": true } ],
    "probe_cache": {
      "torch_constraints_at": null,
      "torch_cuda": null,
      "driver": null,
      "sage_max_torch": null,
      "flash_max_torch": null,
      "torch_candidate": null,
      "stepdown_needed": null,
      "stepdown_reason": ""
    }
  },
  "targets": {
    "/mnt/1TB_SSD": {
      "installed": {
        "comfyui": { "status": "ok", "installed_at": "...",
                     "python": "3.12.12", "torch": "2.12.0+cu130" }
      },
      "runs": [ { "timestamp": "...", "label": "...", "duration_min": 8.6 } ]
    }
  },
  "wheel_builds": {
    "sageattention": { "attempted_at": "...", "status": "ok", "wheel_name": "..." }
  }
}
```

**Rules:**
- `probe{}` — written by `ai_installer.py` from `ai_lib_probe.run()` result
- `probe.probe_cache{}` — written when torch constraint probe runs (install menu entry)
- `targets[mp].installed{}` — written by `ai_installer.py` after successful installs
- `targets[mp].runs[]` — written by `ai_installer.py` only
- `config{}` and `meta{}` — written by `ai_installer.py` on init/select/first-run
- Free space NOT stored in `probe.drives[]` — dynamic, read live from df
- `config.python` = configured/required versions (not what's installed —
  that's in `targets[mp].installed[app].python`)

---

## File Naming

| Pattern | Purpose |
|---|---|
| `ai_installer.py` | Main entry point — menu, dispatch, config, target selection |
| `ai_installer.json` | Single source of truth — written by Python, read by bash |
| `ai_installer_menu.json` | Menu layout — edit to reorder/rename without touching Python |
| `ai_config.sh` | Shared bash config — sourced by all installers and runners |
| `pylib/ai_config.py` | JSON gateway — sole writer, CLI for bash reads |
| `pylib/ai_lib_*.py` | Library modules — pure functions, no JSON writes |
| `installers/ai_*_install.sh` | App installers — called by ai_installer.py via subprocess |
| `postinstallers/ai_*_postinstall.sh` | Per-app post-install hooks — `# DESCRIPTION:` header required |
| `postinstallers/ai_*_postinstall.py` | Python postinstall engine — when .sh is superseded |
| `runners/ai_*` | App runners — thin launch wrappers |

All scripts co-located in `~/bin/scripts/AI_Tools/`. Each finds its siblings via:
- Python: `SCRIPT_DIR = Path(__file__).parent`
- Bash installers: `SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"`

---

## Menu System

Menu layout lives in `ai_installer_menu.json` — not in Python.
Python owns: rendering, input handling, function registries.

### Extending the menu

**New static item:**
1. Add function to `_build_item_registry()` in `ai_installer.py`
2. Add `{ "id": "your_id", "label": "...", "show_if": "..." }` to the JSON

**New dynamic section:**
1. Write a `build_*_items()` function returning `list[MenuItem]`
2. Add token to `_build_section_builders()` in `ai_installer.py`
3. Use `"items": "your_token"` in the JSON section

**New show_if condition:**
1. Add one lambda to `_CONDITIONS` dict in `ai_installer.py`
2. Reference by name in JSON `show_if` fields

**New pre/post hook:**
1. Write the function: `def my_hook(target, config, probe) -> None`
2. Add to `_PRE_POST_REGISTRY` in `ai_installer.py`
3. Set `"pre": "my_hook"` on the menu in `ai_installer_menu.json`

### Section label annotation
Labels starting with `CMNT:` are treated as null — no header printed.
Use for human-readable notes in the JSON without affecting rendering.

---

## Python Conventions

### Module header

```python
#!/usr/bin/env python3
# =============================================================================
# ai_lib_NAME.py  —  brief one-line description
# =============================================================================
# What this module does, what calls it, what it returns.
#
# Requires: packaging>=21.0, requests>=2.28.0
# Both present in Debian 13 system Python — no venv needed.
# =============================================================================
```

### Pure function pattern

Library modules are pure functions — take arguments, return dicts, no JSON writes.
Only `ai_installer.py` writes to JSON, always via `ai_config.py`.

```python
# ai_lib_probe.py — pure function
def run() -> dict: ...

# ai_lib_apps.py — pure function
# config must have "_installed" key pre-populated by caller
def run(target: str, config: dict, probe: dict) -> dict: ...

# ai_installer.py — owns all JSON writes
probe_data = ai_lib_probe.run()
app_states = ai_lib_apps.run(target, config, probe_data)
ai_config.write_probe(probe_data)
```

### Error handling

- `try/except` around all subprocess calls and file I/O
- Non-fatal: log to stderr, continue
- Fatal: `err(message)`, `sys.exit(1)`
- Never let exceptions propagate uncaught to the user

### Semver comparison

Always use `packaging.version.Version`. Never compare version strings directly.

```python
from packaging.version import Version
if Version(inst_torch.split("+")[0]) < Version("2.7.0"):
    ...
```

### GitHub API

All GitHub API calls go through `ai_lib_github.py`. Never call directly from
other modules. Token from `$GITHUB_TOKEN` env var.

### Stub functions

```python
def get_required_python(app: str) -> str:
    # STUB — replace with real fetch when ai_lib_github is complete
    return {"automatic": "3.10.6", "comfyui": "3.12.12", ...}.get(app, "3.11.9")
```

---

## Bash Conventions

### Sourcing ai_config.sh

Installers (in installers/ subdir — one level down from SCRIPT_DIR):
```bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${SCRIPT_DIR}/ai_config.sh"
```

Runners (in runners/ subdir — same pattern):
```bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${SCRIPT_DIR}/ai_config.sh"
```

### Reading JSON from bash

Always use `ai_config.py get` — never raw `jq` directly:
```bash
# Preferred
TORCH_CUDA="$(python3 "${SCRIPT_DIR}/pylib/ai_config.py" get system gpu torch_cuda)"
APP_STATUS="$(python3 "${SCRIPT_DIR}/pylib/ai_config.py" get app comfyui status --default unknown)"

# Avoid
port="$(jq -r '.config.port' "${AI_INSTALLER_JSON}")"
```

`AI_INSTALLER_JSON` is exported by `ai_config.sh`.

### pip() alias pattern

```bash
VENV_PIP="${VENV_DIR}/bin/pip"
pip() { "${VENV_PIP}" "$@"; }
```

### Error handling

- `set -euo pipefail` at top of every script
- `set -e` / `set +e` **never** inside functions — use `if`/`||` instead
- `|| true` only for genuinely optional commands

### --update before preflight

`--update` block appears before preflight in all installers. Preflight (nvcc,
gcc, pyenv checks) only needed for fresh installs and rebuilds.

### sudo keepalive

Installers that use sudo should add after sourcing `ai_config.sh`:
```bash
sudo_keepalive_start
trap sudo_keepalive_stop EXIT
```

### Interactive prompts

Use `getinput` (defined in `ai_config.sh`) instead of raw `read`:
```bash
getinput "Proceed? [y/N]: " confirm
```
Plays a terminal bell before the prompt so long builds get attention.

---

## App Registry

Defined once in `ai_lib_apps.py` — never duplicated in bash:

```python
APP_REGISTRY = {
    "automatic":      { "disk_name": "stable-diffusion-webui",
                        "torch_pinned": True, "est_disk_gb": 8, "est_min": 10 },
    "wan2gp":         { "disk_name": "Wan2GP", ... },
    "frampackstudio": { "disk_name": "FramePack-Studio", ... },
    "invokeai":       { "disk_name": "invokeai", "pip_pkg": "invokeai", ... },
    "comfyui":        { "disk_name": "ComfyUI", ... },
}
```

---

## Special Cases

### AUTOMATIC1111
Pinned to commit `82a973c0`. Torch pinned to cu121 by design — never offer
torch rebuild. `webui.sh` needs `KEEP_GOING=${AI_INSTALLER_MODE:-1}`.

### InvokeAI
Pip package, no `.git`. Python 3.12. Uses `.venv/`. No pip binary — use
`python -m pip`. Torch constrained below system CUDA via `torch~=x.y.z` pin.
`resolve_torch_for_app()` handles this — never hardcode.

### ComfyUI ops.py patch
`comfy/ops.py` threshold patched to `1e-7` for RTX 3060 (prevents NaN/black
output). Re-applied after every `git pull`. Runner checks before launch.

### ComfyUI-LTXVideo kornia patch
`pyramid_blending.py` imports `pad` from `torch.nn.functional` (removed from
kornia 0.8.3). Must survive `git pull` — pending wire into postinstaller.

### Flash-attn / Nunchaku / llama.cpp
Non-fatal expected failures. Managed by `ai_lib_optional.py`.

---

## Adding a New App

1. Add entry to `APP_REGISTRY` in `ai_lib_apps.py`
2. Add to `ALL_APPS` in `ai_installer.py`
3. Write `installers/ai_APP_install.sh`
4. Write `runners/ai_APP`
5. Optionally write `postinstallers/ai_APP_postinstall.sh` with `# DESCRIPTION:` header
6. No menu JSON changes needed — apps section renders from `APP_REGISTRY` dynamically

## Adding a New Python Module

1. Name it `pylib/ai_lib_NAME.py`
2. Follow module header template
3. Pure function — args in, dict out, no JSON write
4. GitHub API calls → import `ai_lib_github`, never direct
5. Import in `ai_installer.py`, call in startup sequence
