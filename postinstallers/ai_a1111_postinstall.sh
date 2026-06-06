#!/usr/bin/env bash
# =============================================================================
# ai_a1111_postinstall.sh  —  Post-install for AUTOMATIC1111
# =============================================================================
# DESCRIPTION: Install ControlNet, ADetailer, Civitai Helper, Ultimate Upscale
# =============================================================================
# Installs four extensions into stable-diffusion-webui/extensions/:
#
#   ControlNet        — Guided image generation using depth/pose/canny maps.
#                       Models are already in AI-Shared-Resources/image/ControlNet/
#                       and symlinked into A1111's models/ControlNet/ by the
#                       main installer — no extra model setup needed.
#
#   ADetailer         — After-Detailer. Runs a second inpainting pass over
#                       faces and hands after main generation. Essential for
#                       realistic human subjects at normal resolutions.
#
#   Civitai Helper    — Browse and download models from CivitAI directly
#                       inside the A1111 UI. Maintained fork by zixaphir.
#
#   Ultimate Upscale  — Better tiled upscaling than A1111's built-in.
#                       Works with ESRGAN models already in shared tree.
#
# Extensions are installed by git clone. pip dependencies are handled
# automatically by webui.sh on next launch — no manual pip install needed.
#
# Safe to re-run: existing extensions are git-pulled rather than re-cloned.
# Use --force to re-run even if already recorded in ai_conductor.json.
#
# Naming convention: ai_<appname>_postinstall.sh
# Called by: ai_conductor.sh (after fresh install or rebuild, or from menu)
# Safe to run standalone: yes
#
# Usage:
#   ./ai_a1111_postinstall.sh
#   ./ai_a1111_postinstall.sh --force
# =============================================================================

set -euo pipefail

# =============================================================================
# Source shared config
# =============================================================================
source "$(dirname "${BASH_SOURCE[0]}")/ai_config.sh"

# =============================================================================
# Paths
# =============================================================================
APP_DIR="${AI_APPS}/stable-diffusion-webui"
EXTENSIONS_DIR="${APP_DIR}/extensions"

# =============================================================================
# Helpers
# =============================================================================
step() { echo; echo "==> $*"; }
warn() { echo "  WARN: $*"; }
good() { echo -e "\033[32m  ✔\033[0m $*"; }

# =============================================================================
# _clone_or_pull <name> <url>
# =============================================================================
# Purpose: Clone an extension repo if not present, or pull if it is.
#   Idempotent — safe to call on an already-installed extension.
# Pre:  EXTENSIONS_DIR exists, git on PATH.
# Post: Extension repo present and up to date under EXTENSIONS_DIR/<name>.
# =============================================================================
_clone_or_pull() {
    local name="$1"
    local url="$2"
    local dest="${EXTENSIONS_DIR}/${name}"

    if [[ -d "${dest}/.git" ]]; then
        echo "  ${name}: already installed — pulling"
        git -C "${dest}" pull --quiet \
            && good "${name} up to date" \
            || warn "${name}: git pull failed — non-fatal, continuing"
    else
        echo "  ${name}: cloning"
        git clone --quiet "${url}" "${dest}" \
            && good "${name} cloned" \
            || { warn "${name}: clone failed"; return 1; }
    fi
}

# =============================================================================
# Preflight
# =============================================================================
step "Preflight"

[[ ! -d "${APP_DIR}" ]] && {
    echo "ERROR: A1111 not found at ${APP_DIR}"
    echo "  Run the main installer first: ai_automatic_install.sh"
    exit 1
}
[[ ! -d "${APP_DIR}/webui.sh" && ! -f "${APP_DIR}/webui.sh" ]] && {
    echo "ERROR: webui.sh not found — A1111 install may be incomplete"
    echo "  Run: ai_automatic_install.sh"
    exit 1
}
good "A1111 found: ${APP_DIR}"

mkdir -p "${EXTENSIONS_DIR}"
good "Extensions dir: ${EXTENSIONS_DIR}"

# =============================================================================
# Extensions
# =============================================================================
step "Installing extensions"
echo "  pip dependencies will be resolved by webui.sh on next launch"
echo ""

# ControlNet — guided generation using conditioning images
# Models already in: AI-Shared-Resources/image/ControlNet/
# Symlinked by installer to: stable-diffusion-webui/models/ControlNet/
_clone_or_pull \
    "sd-webui-controlnet" \
    "https://github.com/Mikubill/sd-webui-controlnet.git"

# ADetailer — second-pass face and hand refinement
# Detects faces/hands in output, inpaints at higher resolution, composites back
_clone_or_pull \
    "adetailer" \
    "https://github.com/Bing-su/adetailer.git"

# Civitai Helper — browse and download models from CivitAI inside the UI
# Maintained fork — the original repo is abandoned
_clone_or_pull \
    "Stable-Diffusion-Webui-Civitai-Helper" \
    "https://github.com/zixaphir/Stable-Diffusion-Webui-Civitai-Helper.git"

# Ultimate SD Upscale — tiled upscaling, works with ESRGAN models
# Better than A1111's built-in SD upscale for large images
_clone_or_pull \
    "ultimate-upscale-for-automatic1111" \
    "https://github.com/Coyote-A/ultimate-upscale-for-automatic1111.git"

# =============================================================================
# Done
# =============================================================================
echo
echo "============================================================"
echo "  A1111 post-install complete"
echo "  Extensions installed:"
echo "    - sd-webui-controlnet    (ControlNet guided generation)"
echo "    - adetailer              (face + hand detail refinement)"
echo "    - Civitai Helper         (model browser and downloader)"
echo "    - ultimate-upscale       (tiled upscaling)"
echo ""
echo "  Next launch of A1111 will install pip dependencies."
echo "  Start with: ai_automatic"
echo "============================================================"
