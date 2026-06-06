# AI Stack Project — Jethro

## What This Is

A suite of scripts that install, configure, update and launch a collection of
AI image and video generation applications on a single Linux machine with an
NVIDIA GPU. Single entry point for everything: `ai_tools`.

**Jethro:** Debian Trixie 13.2, RTX 3060 12GB VRAM, i7-10700K, 32GB RAM.
Driver 610.43.02 → max CUDA 13.0 → torch cu130. SageAttention v2 capable.
Scripts live in `~/bin/scripts/AI_Tools/` which is on PATH.
GitHub: https://github.com/TrickBit/AI_TOOLS

---

## The Apps

| App | Key | Type | Python | Notes |
|---|---|---|---|---|
| AUTOMATIC1111 | `automatic` | git clone | 3.10.6 | Pinned to commit 82a973c0, torch cu121 |
| Wan2GP | `wan2gp` | git clone | 3.11.9 | Video generation |
| FramePack-Studio | `frampackstudio` | git clone | 3.11.9 | Image-to-video |
| InvokeAI | `invokeai` | pip package | 3.12.12 | torch constrained via app pin |
| ComfyUI | `comfyui` | git clone | 3.12.12 | Node-based image/video pipeline |

---

## Directory Layout

```
~/bin/scripts/AI_Tools/           ← SCRIPT_DIR for all scripts
  CLAUDE.md                       ← auto-loaded by Claude Code on startup
  claude_continue.md              ← symlink → docs/ai_continue_session{N}.md
  ai_tools.sh                     ← ONLY executable (symlinked to ~/bin/scripts/ai_tools)
  ai_installer.py                 ← Python entry point (menu, installs, config)
  ai_installer.json               ← single source of truth (Python writes, bash reads)
  ai_installer_menu.json          ← menu layout config (edit to reorder/rename items)
  ai_model_manager.py             ← model manager entry point
  ai_config.sh                    ← shared bash config (sourced by all installers/runners)
  ai_wheels_organise.sh           ← sorts wheel cache into ABI subdirs
  ai_migrate_resources.sh         ← hardlink/verify/prune legacy resource trees
  pylib/
    ai_config.py                  ← sole JSON gateway (Python writes, bash reads via CLI)
    ai_lib_probe.py               ← hardware/system detection
    ai_lib_apps.py                ← app state detection — pure function
    ai_lib_optional.py            ← optional package detection — pure function
    ai_lib_github.py              ← GitHub API comms
    ai_lib_wheels.py              ← wheel cache management
    ai_collect_wheels.py          ← post-install wheel harvesting
    ai_resourcelib/               ← model manager libs subpackage
  installers/
    ai_automatic_install.sh
    ai_wan2gp_install.sh
    ai_frampackstudio_install.sh
    ai_invokeai_install.sh
    ai_comfyui_install.sh
  runners/
    ai_automatic  ai_wan2gp  ai_frampackstudio  ai_invokeai  ai_comfy
  postinstallers/
    ai_comfyui_postinstall.py     ← ini-driven workflow pack installer (real engine)
    ai_comfyui_postinstall.sh     ← stub (SUPERSEDED marker — routes to .py)
    ai_a1111_postinstall.sh
    ai_APP_postinstall.sh         ← template
    comfyui_workflows.ini         ← human-editable workflow pack definitions
  docs/
    claude_about_martin.md
    claude_project.md             ← softlink → ai_project.md (this file)
    claude_conventions.md         ← softlink → ai_conventions.md
    claude_ai_context.md          ← retired from load order, kept for reference
    ai_continue_session{N}.md     ← session continue docs (numbered)
    claude_lastsession.md         ← written by /night in Claude Code
  logs/                           ← timestamped install logs + lastrun symlinks
  backups/

/mnt/<target_drive>/
  AI_Apps/                        ← app installs (one subdir per app)
  AI-Shared-Resources/            ← canonical model library (hardlinked)
    image/  video/  shared/
  AI_Outputs/                     ← generated content (symlinked from each app)
  AI_Work/                        ← training data (never touched by scripts)

/mnt/<wheels_drive>/AI_Collected_Wheels/localbuild/
  cp310/   ← A1111 wheels
  cp311/   ← Wan2GP / FramePack wheels
  cp312/   ← ComfyUI / InvokeAI wheels
  cp313/   ← future
  nvidia_*.whl  ← py3-none, kept in root
```

---

## Script Suite

### Core Python

| Script | Purpose |
|---|---|
| `ai_installer.py` | Main entry point — menu, installs, updates, config, launch |
| `pylib/ai_config.py` | Sole JSON gateway — all reads/writes to ai_installer.json |
| `pylib/ai_lib_probe.py` | System probe — GPU, driver, CUDA, tools, drives |
| `pylib/ai_lib_apps.py` | App state detection — pure function, returns dict |
| `pylib/ai_lib_optional.py` | Optional package detection — pure function, returns dict |
| `pylib/ai_lib_github.py` | GitHub API comms — all external API calls |
| `pylib/ai_lib_wheels.py` | Wheel cache management |
| `pylib/ai_collect_wheels.py` | Post-install wheel harvesting |
| `ai_model_manager.py` | Model consolidation and hardlink management |

### Core Bash

| Script | Purpose |
|---|---|
| `ai_tools.sh` | Single entry point — only executable, symlinked to ~/bin/scripts/ai_tools |
| `ai_config.sh` | Shared bash config — sourced by all installers and runners |
| `ai_wheels_organise.sh` | Sort wheel cache into ABI subdirs |
| `ai_migrate_resources.sh` | Hardlink/verify/prune legacy resource trees |

### Installers / Runners / Postinstallers

One installer, one runner, optionally one postinstaller per app.
Postinstallers require a `# DESCRIPTION:` header line.
Stubs marked with `SUPERSEDED` route to their `.py` replacement.

---

## ai_installer.py — How It Works

### Startup Flow

```
no JSON  → first-run welcome → probe → target select → write JSON → install menu
no args  → load JSON → verify target mounted → check probe staleness → main menu
--init   → backup old JSON → probe → select target → write JSON → main menu
--select → probe → select target → update config → main menu
```

No `--init` needed for normal first-run — the welcome flow handles it interactively.

### Probe Staleness

Stored probe is re-used if less than 24 hours old AND driver version unchanged.
One `nvidia-smi` call to check driver — fast. Stale probe is re-run silently
with one info line.

### Menu System

Layout driven by `ai_installer_menu.json` — edit that file to reorder, rename,
or hide items without touching Python.

**Main menu:**
```
  LAUNCH           (installed apps only — hidden if none installed)
   1. AUTOMATIC1111
   2. Wan2GP  ...

  STACK
   N. Full status
   N. Switch target drive   now: /mnt/1TB_SSD
   N. Run migration

   N. Install / manage apps →   (3 apps need attention)

   q. Quit
```

**Install / manage apps submenu:**
```
  APPS             (installs, updates, or rebuilds as needed)
   1-5. per app

  BATCH
   N. Batch install / update...
   N. View install logs          (hidden if no apps installed)

  POST-INSTALL     (hidden if no postinstall scripts exist)
   N. ComfyUI — workflow packs

   q. Back
```

### show_if Conditions

Items and sections in the menu JSON have optional `show_if` keys.
Conditions are evaluated each render loop from the context dict.

| Condition | Shows when |
|---|---|
| `always` | always (default if show_if missing) |
| `has_target` | active target is set |
| `has_drives` | at least one mountable drive found |
| `has_any_app` | at least one app status == "ok" |
| `has_migration` | ai_migrate_resources.sh exists |

Adding a new condition: one lambda in `_CONDITIONS` dict in `ai_installer.py`,
then reference by name in `ai_installer_menu.json`.

### Menu JSON Validation

On startup, `ai_installer_menu.json` is validated:
- **Tier 1 (fatal):** file missing, unparseable, or required menu id missing.
  Exits with `git checkout` and repo URL remediation message.
- **Tier 2 (warn + continue):** unknown item id, unknown condition, unknown
  dynamic token. Item skipped, execution continues.

Repo URL for remediation: https://github.com/TrickBit/AI_TOOLS

---

## ai_config.py — JSON Gateway

All reads and writes to `ai_installer.json` go through this module.
No other script touches the JSON file directly.

```bash
# Bash reads via CLI
python3 ai_config.py get system gpu torch_cuda
python3 ai_config.py get app wan2gp status
python3 ai_config.py get config port --default 7860
python3 ai_config.py set app wan2gp status ok
python3 ai_config.py record-install --app wan2gp --status ok --python 3.11.9 --torch 2.12.0+cu130
```

Scopes: `system` → probe{}, `app <name>` → targets[target].installed[name],
`config` → config{}, `meta` → meta{}.

---

## ai_config.sh — What It Exports

Sourced at the top of every installer and runner:
```bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${SCRIPT_DIR}/ai_config.sh"
```

Exports: `AI_TARGET`, `AI_APPS`, `AI_SHARED`, `AI_OUTPUTS`, `AI_WORK`,
`HF_HOME`, `TORCH_CUDA`, `TORCH_INDEX`, `CUDA_HOME`, `DRIVER_MAJOR`,
`SAGE_V2_CAPABLE`, `CC`, `CXX`, `AI_PORT`,
`PYTHON_VER_AUTOMATIC`, `PYTHON_VER_WAN2GP`, `PYTHON_VER_COMFYUI` etc.

Helper functions: `require_python`, `resolve_torch`, `resolve_torch_for_app`,
`ensure_build_env`, `getinput`, `sudo_keepalive_start`, `sudo_keepalive_stop`.

Probe runs live on every `ai_tools` invocation (no /tmp cache).
`_AI_CONFIG_LOADED` guard prevents double-sourcing.

---

## Driver → CUDA → PyTorch Mapping

| Driver | CUDA | PyTorch index |
|---|---|---|
| ≥ 570 | 13.0 | cu130 |
| ≥ 545 | 12.6 | cu126 |
| ≥ 525 | 12.4 | cu124 |
| ≥ 520 | 12.0 | cu121 |
| ≥ 510 | 11.8 | cu118 |

Jethro: driver 610 → cu130. SageAttention v2 requires driver ≥ 570.

---

## Wheels Cache

```
/mnt/BACKUP_4.0_TB/AI_Collected_Wheels/localbuild/
  cp310/   ← A1111 (Python 3.10)
  cp311/   ← Wan2GP, FramePack (Python 3.11)
  cp312/   ← ComfyUI, InvokeAI (Python 3.12)
  cp313/   ← future
  nvidia_*.whl  ← py3-none, kept in root
```

Installers use: `--find-links "${WHEELS_DIR}/localbuild/${PYTHON_ABI}"`
Collection: `ai_collect_wheels.py` writes to correct ABI subdir automatically.
Organise: `ai_tools wheels organise [--dry-run]`

---

## SageAttention Status

| App | Python | Status |
|---|---|---|
| Wan2GP | cp311 | ✔ 2.2.0+cu130 cached |
| FramePack | cp311 | ✔ 2.2.0+cu130 cached |
| ComfyUI | cp312 | ✗ incompatible with torch 2.12 — pending SA 2.3 |
| InvokeAI | cp311 | not attempted |
| A1111 | cp310 | not applicable (pinned cu121) |

Torch constraint probing (dynamic detection of best torch/SA pairing before
install) is planned — currently ComfyUI steps down to torch 2.9.1 when SA 2.2.0
is detected as incompatible.

---

## Special Cases

**AUTOMATIC1111:** Pinned to commit `82a973c0`. Torch pinned to cu121 by design —
never offer torch rebuild. `webui.sh` needs `KEEP_GOING=${AI_INSTALLER_MODE:-1}`.

**InvokeAI:** Pip package, no `.git`. Python 3.12. Uses `.venv/` not `venv/`.
No pip binary — use `python -m pip`. Torch constrained below system CUDA via
app's `torch~=x.y.z` pin. `resolve_torch_for_app()` handles this automatically.

**ComfyUI ops.py patch:** `comfy/ops.py` contains a threshold value that causes
NaN/black output on RTX 3060. Patched to `1e-7` after every `git pull`.
Runner checks patch is in place before launch.

**ComfyUI-LTXVideo kornia patch:** `pyramid_blending.py` needs `pad` imported
from `torch.nn.functional` not kornia (removed in kornia 0.8.3). Must survive
`git pull` — pending wire into postinstaller as a recorded patch.

---

## Adding a New App

1. Add entry to `APP_REGISTRY` in `ai_lib_apps.py`
2. Add to `ALL_APPS` in `ai_installer.py`
3. Write `installers/ai_APP_install.sh`
4. Write `runners/ai_APP`
5. Optionally write `postinstallers/ai_APP_postinstall.sh` with `# DESCRIPTION:` header
6. No menu changes needed — apps section renders from `APP_REGISTRY` dynamically

---

## Platform Support

### Current — Debian Linux (native)

Built for and tested on Debian 13 Trixie. Intended to be distro-portable —
see below.

### Linux — Other Distros

The stack is designed to be distro-portable. The only Debian-specific code
is ~20 lines of `apt` calls in `ai_config.sh` and the installers. Everything
above the driver layer — pyenv, pip, Python, CUDA toolkit, PyTorch — is
distro-agnostic.

A `detect_distro()` function reading `/etc/os-release` and branching on
`$ID` / `$ID_LIKE` would cover the package manager differences:

| Distro family | Package manager | Effort |
|---|---|---|
| Debian, Ubuntu, Mint, Pop!_OS, elementary | `apt` | works now |
| Fedora, RHEL, Rocky, AlmaLinux | `dnf` | low — swap ~20 lines + package name table |
| openSUSE | `zypper` | low — same as above |
| Arch, Manjaro | `pacman` | moderate — rolling release, excellent NVIDIA support |

What actually varies per distro: package manager commands, package names
(`gcc-12` vs `gcc12` vs `gcc`), and NVIDIA driver install method. Everything
else is identical.

**Intention:** abstract package management into a distro detection layer in
`ai_config.sh` — `detect_distro()` + per-distro package name maps. Moderate
work, high value for portability.

### Windows — via WSL2 (realistic path)

WSL2 (Windows Subsystem for Linux) runs a real Linux kernel inside Windows
10/11. Ubuntu installs in one step from the Microsoft Store. Under WSL2:

- All bash scripts run as-is — no rewriting needed
- NVIDIA ships a WSL2-specific CUDA driver that exposes the GPU to Linux
- PyTorch CUDA is officially supported under WSL2
- pyenv, apt, hardlinks — all work natively inside the WSL2 virtual disk

**The one constraint:** hardlinks don't work across the WSL2/Windows boundary.
Models must live inside the WSL2 virtual disk (not on an NTFS Windows drive
accessed via `/mnt/c/`). Performance on the virtual disk is near-native.

WSL2 is the recommended path for any Windows user — the stack runs almost
unchanged, the only setup difference is where the target drive lives.

### Windows — native (not currently viable)

Native Windows would require a full rewrite of all bash in PowerShell or
Python, replacement of pyenv, and careful handling of NTFS hardlinks.
Not planned. WSL2 covers the use case without this cost.

### Portability Rule

To keep distro portability and a future WSL2 port easy:
**Avoid subprocess calls to bash tools from Python where avoidable.**
Keep `ai_installer.py` and all `ai_lib_*.py` as OS-agnostic as possible.
Distro-specific work belongs in `ai_config.sh` and the installers, not Python.

---

## Git Rules

**Never run any git write operation without explicitly asking Martin first.**
This includes: `git add`, `git commit`, `git push`, `git pull`, `git merge`,
`git rebase`, `git reset`, `git checkout` (file restore), `git stash`.

Read-only operations are fine without asking: `git status`, `git log`,
`git diff`, `git show`.

One broken push already happened. Code that is not working or not reviewed
does not go to the repo. Martin commits only when things are known-good.
