# AI Tools

A personal AI stack management system for Linux — one entry point to install,
update, launch, and maintain multiple local AI applications on a single machine
with a shared model library.

Built for and tested on Debian 13 (Trixie) with an NVIDIA RTX 3060 12GB.
Designed to be distro-portable — see Platform Support below.

---

## What It Does

Manages five AI applications as a coordinated stack:

| App | Purpose | Python |
|-----|---------|--------|
| AUTOMATIC1111 | Stable Diffusion image generation | 3.10 |
| Wan2GP | Video generation | 3.11 |
| FramePack | Video generation / frame interpolation | 3.11 |
| InvokeAI | Stable Diffusion (alternative UI) | 3.12 |
| ComfyUI | Node-based AI workflows | 3.12 |

Each app gets its own Python version (via pyenv) and isolated venv. All share
a common model library via hardlinks — one copy on disk, visible to every app
that needs it.

---

## Key Features

- **Single entry point** — `ai_tools` dispatches everything: install, update, launch, status
- **Auto-detects your hardware** — driver version → CUDA version → correct PyTorch build, automatically
- **Shared model library** — models stored once, hardlinked into each app's expected location
- **Compiled wheel cache** — heavy CUDA extension builds (SageAttention, flash-attn, xformers) cached by Python ABI so rebuilds skip the 20-60 min compile
- **Safe to re-run** — all installers are idempotent; running twice does the right thing
- **Persistent config** — one JSON file (`ai_installer.json`) tracks what's installed, where, and with what versions
- **ComfyUI workflow packs** — ini-driven system for installing curated workflow bundles with their models and custom nodes

---

## Architecture

```
ai_tools.sh                    ← only executable, symlinked to ~/bin/scripts/ai_tools
        ↓
ai_installer.py                ← interactive menu, installs, config, launch
ai_model_manager.py            ← model consolidation and hardlink management
        ↓
installers/
    ai_automatic_install.sh
    ai_wan2gp_install.sh
    ai_frampackstudio_install.sh
    ai_invokeai_install.sh
    ai_comfyui_install.sh
runners/
    ai_automatic  ai_wan2gp  ai_frampackstudio  ai_invokeai  ai_comfy
postinstallers/
    ai_comfyui_postinstall.py  ← ini-driven workflow pack installer
    comfyui_workflows.ini      ← human-editable workflow pack definitions
    ai_a1111_postinstall.sh
        ↓
pylib/
    ai_config.py               ← sole JSON gateway (Python writes, bash reads)
    ai_lib_probe.py            ← hardware/system detection
    ai_lib_apps.py             ← app state logic
    ai_lib_wheels.py           ← wheel cache management
    ai_lib_optional.py         ← optional packages (Nunchaku etc)
    ai_lib_github.py           ← GitHub API helpers
    ai_collect_wheels.py       ← post-install wheel harvesting
    ai_resourcelib/            ← model manager subpackage
        ↓
ai_installer.json              ← runtime state (one file, Python is sole writer)
ai_installer_menu.json         ← menu layout (edit to reorder/rename items)
ai_config.sh                   ← shared bash config, sourced by all installers
```

### Design principles

**Python writes JSON, bash reads it.** `ai_config.py` is the sole gateway to
`ai_installer.json`. Bash installers never call `jq` directly — they call
`ai_config.py get` with a scope and key path.

**One probe per session.** `ai_config.sh` probes hardware on every `ai_tools`
invocation (one `nvidia-smi` call). No `/tmp` cache. Python-side probe results
are stored in JSON and reused if less than 24 hours old and driver version
unchanged.

**Torch auto-resolution.** Driver version → CUDA max → PyTorch index URL, resolved
at install time. No hardcoded CUDA versions in installer logic.

**Menu layout is data.** `ai_installer_menu.json` defines what sections and items
appear in which menu and in what order. Adding, removing, or reordering menu items
does not require touching Python — edit the JSON. Items have `show_if` conditions
that gate visibility based on system state (target mounted, apps installed, etc).

---

## Directory Layout on Disk

```
/mnt/<target_drive>/
├── AI_Apps/
│   ├── AUTOMATIC1111/
│   ├── Wan2GP/
│   ├── FramePack/
│   ├── InvokeAI/
│   └── ComfyUI/
├── AI-Shared-Resources/       ← canonical model library
│   ├── image/
│   │   ├── Checkpoints/
│   │   ├── Lora/
│   │   ├── VAE/
│   │   ├── ControlNet/
│   │   └── Upscalers/
│   └── video/
│       ├── Models/
│       ├── Lora/
│       ├── VAE/
│       ├── TextEncoders/
│       └── ComfyWorkflows/
├── AI_Outputs/                ← generated content (symlinked from each app)
│   ├── AUTOMATIC1111/
│   ├── ComfyUI/
│   └── ...
└── AI_Work/                   ← training data (never touched by scripts)

/mnt/<wheels_drive>/
└── AI_Collected_Wheels/
    └── localbuild/
        ├── cp310/             ← A1111 wheels
        ├── cp311/             ← Wan2GP / FramePack wheels
        ├── cp312/             ← ComfyUI / InvokeAI wheels
        └── nvidia_*.whl       ← py3-none wheels (kept in root)
```

---

## Requirements

- Debian 13 (Trixie) or compatible — system Python 3.11+ for `ai_installer.py` itself
- `pyenv` — for per-app Python version management
- NVIDIA GPU with driver ≥ 510 (driver ≥ 570 recommended for SageAttention v2)
- `git`, `gcc-12` or `gcc-13`, `nvcc` (for CUDA extension builds)
- `packaging`, `requests` Python packages (both in Debian 13 system Python)

The system detects what's available and warns about anything missing. Base
ComfyUI and A1111 run without nvcc — it's only needed for building CUDA
extensions like SageAttention and flash-attn from source.

---

## Driver → CUDA → PyTorch mapping

| Driver | CUDA | PyTorch index |
|--------|------|---------------|
| ≥ 570  | 13.0 | cu130 |
| ≥ 545  | 12.6 | cu126 |
| ≥ 525  | 12.4 | cu124 |
| ≥ 520  | 12.0 | cu121 |
| ≥ 510  | 11.8 | cu118 |

SageAttention v2 requires driver ≥ 570.

---

## SageAttention / Flash Attention status

| App | Python | Status |
|-----|--------|--------|
| Wan2GP | cp311 | ✔ SA 2.2.0+cu130 |
| FramePack | cp311 | ✔ SA 2.2.0+cu130 |
| ComfyUI | cp312 | ✗ SA 2.2.0 incompatible with torch 2.12 — pending SA 2.3 |
| InvokeAI | cp311 | not attempted |
| A1111 | cp310 | not applicable (pinned cu121) |

The installer probes for a compatible SageAttention build (wheel cache → PyPI →
GitHub releases) before selecting a torch version, so the torch stepdown only
happens when actually necessary.

---

## Usage

```bash
ai_tools                      # interactive menu
ai_tools probe                # print system probe summary
ai_tools status               # print app status for all apps
ai_tools target               # show active target drive
ai_tools target /mnt/X        # set active target drive
ai_tools comfyui setup        # ComfyUI workflow pack installer
ai_tools comfyui status       # show installed workflow packs
ai_tools wheels organise      # sort wheel cache into ABI subdirs
ai_tools wheels organise --dry-run
```

First run: no config file is needed. `ai_tools` detects the situation, probes
the system, shows available drives, and walks you through setup before opening
the install menu.

---

## ComfyUI Workflow Packs

`comfyui_workflows.ini` defines curated workflow bundles. Each pack specifies:
- Custom nodes to clone
- Models to download (with HuggingFace URLs and shared-resource destinations)
- Workflow JSON files to install
- `extra_model_paths.yaml` entries

The postinstaller handles downloading, hardlinking models into the shared tree,
symlinking workflows into ComfyUI's workflow directory, and recording everything
in `ai_installer.json` for idempotent re-runs.

Currently available pack: **LTX Director + Sulphur 2** — text-to-video and
image-to-video via the WhatDreamsCost Director node and Sulphur 2 model (LTX 2.3
22B fine-tune). Requires 12GB VRAM minimum. RTX 3060 runs Q5_K_M GGUF comfortably.

---

## Current Status (session 18 — 2026-06-05)

The stack is functional. All five apps install and run. Active development areas:

- **Menu system** — layout driven by `ai_installer_menu.json`; items show/hide
  based on system state via named conditions. In progress this session.
- **Torch constraint probing** — dynamic detection of best torch/SageAttention
  pairing before install, replacing the current hardcoded stepdown. Planned next.
- **Workflow resolver** — parse ComfyUI workflow JSON, detect missing models,
  offer to download and link. Designed, not yet built.
- **Drive discovery** — scan mounted drives for existing AI trees, offer adoption.
  Breadcrumb files (`.ai_stack/breadcrumb.json`) designed, not yet written.

### Known issues

- SageAttention 2.2.0 incompatible with torch 2.12 on cp312 — ComfyUI uses
  SDPA fallback until SageAttention 2.3 releases
- `ai_lib_github` HTTP 422 on some version queries — workaround in place
- `sudo keepalive` not yet wired into installers that use sudo
- InvokeAI outputs/ symlink and A1111 model symlink cleanup deferred

---

## Platform Support

### Linux

Built on Debian 13 Trixie. The only Debian-specific code is the `apt` calls
in `ai_config.sh` and the installers — everything else (pyenv, pip, Python,
CUDA, PyTorch) is distro-agnostic.

| Distro family | Status |
|---|---|
| Debian, Ubuntu, Mint, Pop!_OS, elementary | Works now |
| Fedora, RHEL, Rocky, AlmaLinux | Low effort — `dnf` + package name swap |
| openSUSE | Low effort — `zypper` + package name swap |
| Arch, Manjaro | Moderate effort — `pacman`, excellent NVIDIA support |

Planned: `detect_distro()` in `ai_config.sh` that reads `/etc/os-release`
and selects the right package manager and package names automatically.

### Windows — WSL2 (recommended)

WSL2 runs a real Linux kernel inside Windows 10/11. Under WSL2 the stack
runs almost unchanged — bash, pyenv, NVIDIA CUDA, PyTorch all work.
NVIDIA ships a WSL2-specific driver that exposes the GPU to Linux.

**One constraint:** hardlinks don't cross the WSL2/Windows filesystem boundary.
Models must live inside the WSL2 virtual disk, not on a Windows NTFS drive.
Performance inside the virtual disk is near-native.

### Windows — native

Not viable without a full rewrite of the bash layer. WSL2 covers the use case.

---

## Want to Try It?

This started as a personal project for one machine but is built to be portable.
Hardware detection is dynamic, paths are configurable, and Python versions are
managed via pyenv. The installer probes your system and adapts — it won't
assume your setup matches mine.

If you have an NVIDIA GPU on a Debian-based Linux system (or WSL2 on Windows),
it should work. Other distros are close — see Platform Support above.

**What won't break your system:**
- The installer is non-destructive by default — it won't touch existing apps
- Wheel caching and model centralisation are opt-in (on by default, easily disabled)
- A stock/unmanaged install mode is planned for people who want pip to resolve
  dependencies its own way rather than using our torch/CUDA pinning

**Feedback welcome** — if it works on your hardware, or doesn't, open an issue.
Different GPU, different distro, different driver version — all useful data.

---

## File You Should Not Edit

`ai_installer.json` — written exclusively by `ai_installer.py` via `ai_config.py`.
Hand-editing it will work in a pinch but may be overwritten on next run.

## Files That Are Safe to Edit

`ai_installer_menu.json` — menu layout. Reorder, rename, or comment out items freely.
If you break it, restore with: `git checkout AI_Tools/ai_installer_menu.json`

`comfyui_workflows.ini` — workflow pack definitions. Add your own packs here.
