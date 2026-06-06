#!/usr/bin/env bash
# =============================================================================
# ai_automatic_install.sh  —  AUTOMATIC1111 installer for Jethro
# =============================================================================
# Key decisions baked in:
#   - Python 3.10.6 via pyenv (A1111 is not yet fully compatible with 3.11+)
#   - Torch cu121 pinned (stable for A1111; launch_utils.py handles it well)
#   - CLIP pre-installed with --no-build-isolation (workaround for setuptools
#     pkg_resources issue with newer pip build isolation)
#   - xformers pre-installed for RTX performance
#   - webui.sh called with --reinstall-torch to force TORCH_COMMAND is used
#     (CLIP install drags in torch as dependency, causing A1111 to think torch
#     is already installed and skip TORCH_COMMAND without this flag)
#   - Shared AI-Shared-Resources tree created and symlinked
#   - HF_HOME pointed at shared huggingface cache
#
# WHY WE ARE PINNED TO COMMIT 82a973c0 (v1.10.1):
#   A1111's launch_utils.py (~line 349) clones the Stability-AI/stablediffusion
#   repo as a dependency. That repo has moved/died and returns 404. We pin to
#   v1.10.1 because that is the last known-good commit with our TrickBit mirror
#   workaround in place (STABLE_DIFFUSION_REPO / STABLE_DIFFUSION_COMMIT_HASH
#   env vars, set below).
#
#   If you want to check whether upstream has fixed this:
#     # 1. grep the repo reference out of launch_utils.py
#     grep "STABLE_DIFFUSION_REPO" stable-diffusion-webui/modules/launch_utils.py
#     # 2. if it still says Stability-AI/stablediffusion.git — still broken
#     # 3. if it says something else, check if that remote + commit is reachable:
#     git ls-remote --exit-code <new_repo_url> <commit_hash>
#     # returns 0 if reachable, non-zero if 404 — if 0, try removing our overrides
#
#   Quick manual check (run from the stable-diffusion-webui dir):
#     cat modules/launch_utils.py | grep -n -e "stable_diffusion_repo" -e "stable_diffusion_commit_hash"
#   If line ~349 still says Stability-AI/stablediffusion.git — still broken.
#
#   As of 2026-05, A1111 appears to be in maintenance mode. Not worth unpinning
#   until there is a specific reason to do so.
#
# Safe to re-run.
#
# Usage:
#   ./ai_automatic_install.sh           # install or continue (auto-launches)
#   ./ai_automatic_install.sh --update  # git pin + exit (no launch)
#   ./ai_automatic_install.sh --rebuild # wipe venv, reinstall (auto-launches)
#
# NOTE: Install and rebuild always launch the app automatically via webui.sh.
#   The browser will open when the server is ready. Ctrl+C to stop.
# =============================================================================

set -euo pipefail

# =============================================================================
# Source shared config
# =============================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.."; pwd)"
source "${SCRIPT_DIR}/ai_config.sh"
# =============================================================================
# Logging — timestamped log in logs/, lastrun symlink for quick access
# =============================================================================
LOGS_DIR="${SCRIPT_DIR}/logs"
mkdir -p "${LOGS_DIR}"
LOG_TIMESTAMP="$(date '+%Y-%m-%dT%H-%M-%S')"
LOG_FILE="${LOGS_DIR}/ai_automatic_install.${LOG_TIMESTAMP}.log"
exec > >(tee -a "${LOG_FILE}") 2>&1
ln -sf "${LOG_FILE}" "${LOGS_DIR}/ai_automatic_install.lastrun.log"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ===== ai_automatic_install started ====="

# =============================================================================
# Helpers — defined early so --update block can use them
# =============================================================================
log()  { local m="[$(date '+%Y-%m-%d %H:%M:%S')] $*"; echo "${m}"; echo "${m}" >> "${LOG_FILE}"; }
step() { echo; echo "==> $*"; log "STEP: $*"; }
warn() { echo "  WARN: $*"; log "WARN: $*"; }

# =============================================================================
# Build environment
# =============================================================================
# No source builds needed for this app
ensure_build_env  # no source builds needed — no-op

# =============================================================================
# Paths
# =============================================================================
WEBUI_DIR="${AI_APPS}/stable-diffusion-webui"
REPO_URL="https://github.com/AUTOMATIC1111/stable-diffusion-webui"
WEBUI_COMMIT="82a973c04367123ae98bd9abdf80d9eda9b910e2"   # v1.10.1

TARGET_PY="${PYTHON_VER_AUTOMATIC}"
PYTHON_ABI="cp$(echo "${TARGET_PY}" | awk -F. '{print $1$2}')"
# Stable Diffusion repo override (original Stability-AI repo is 404)
export STABLE_DIFFUSION_REPO="https://github.com/TrickBit/Stability-AI-stablediffusion.git"
export STABLE_DIFFUSION_COMMIT_HASH="cf1d67a6fd5ea1aa600c4df58e5b47da45f6bdbf"

# A1111 uses TORCH_COMMAND env var to install torch — we set it from config.
# We target cu121 for A1111 regardless of driver; it's stable and A1111's
# launch_utils.py handles it well. Override here if needed.
export TORCH_COMMAND="pip install torch==2.4.1+cu121 torchvision==0.19.1+cu121 --index-url https://download.pytorch.org/whl/cu121"

# Force A1111 to use our pyenv python, not system python3
export python_cmd="${HOME}/.pyenv/versions/${TARGET_PY}/bin/python3"

# =============================================================================
# --update mode: pin to commit only — webui.sh handles deps on next launch
# =============================================================================
if [[ "${1:-}" == "--update" ]]; then
    step "Updating AUTOMATIC1111"
    [[ ! -d "${WEBUI_DIR}/.git" ]] && {
        echo "ERROR: ${WEBUI_DIR} not found. Run installer first."
        exit 1
    }
    cd "${WEBUI_DIR}"
    echo "  Pinning to ${WEBUI_COMMIT} (v1.10.1)..."
    git fetch --tags origin
    git checkout "${WEBUI_COMMIT}"
    git reset --hard "${WEBUI_COMMIT}"
    echo "  Pinned: $(git rev-parse HEAD)"

    # Record update in conductor JSON
    _torch_ver="$(venv/bin/python -c "import torch; print(torch.__version__)" 2>/dev/null || echo "unknown")"

    # Collect any updated wheels into cache
    if [[ "${AI_INSTALLER_MODE:-}" == "1" ]]; then
        echo "  Wheel collection handled by ai_installer."
    else
        python3 "${SCRIPT_DIR}/pylib/ai_collect_wheels.py" --venv "${WEBUI_DIR}/venv" \
            && echo "  Wheel cache updated." || true
    fi
    echo ""
    echo "Update complete. Dependencies will be checked on next launch."
    echo "Start with: ai_automatic"
    exit 0
fi

# =============================================================================
# --rebuild mode: wipe venv so webui.sh recreates it cleanly
# =============================================================================
if [[ "${1:-}" == "--rebuild" ]]; then
    step "Rebuild: wiping venv"
    VENV_DIR="${WEBUI_DIR}/venv"
    if [[ -d "${VENV_DIR}" ]]; then
        rm -rf "${VENV_DIR}"
        echo "  Removed: ${VENV_DIR}"
    fi
fi

# =============================================================================
# Preflight
# =============================================================================
step "Preflight"
echo "  Install dir : ${WEBUI_DIR}"
echo "  Python      : ${TARGET_PY}"
echo "  CUDA        : cu121 (A1111 pinned)"
echo "  Driver      : ${PROBE_DRIVER_VERSION}"
echo "  HF_HOME     : ${HF_HOME}"

[[ ! -d "${AI_TARGET}" ]] && { log "ERROR: Drive not mounted? ${AI_TARGET} not found."; exit 1; }

# =============================================================================
# Python via pyenv
# =============================================================================
step "Python ${TARGET_PY}"
require_python "${TARGET_PY}"

# =============================================================================
# Clone A1111 at pinned commit
# =============================================================================
step "Cloning stable-diffusion-webui"
if [[ ! -d "${WEBUI_DIR}/.git" ]]; then
    mkdir -p "$(dirname "${WEBUI_DIR}")"
    git clone "${REPO_URL}" "${WEBUI_DIR}"
else
    log "Already cloned."
fi
cd "${WEBUI_DIR}"
log "Pinning to ${WEBUI_COMMIT} (v1.10.1)..."
git fetch --tags origin
git checkout "${WEBUI_COMMIT}"
git reset --hard "${WEBUI_COMMIT}"
log "Pinned: $(git rev-parse HEAD)"

# Patch webui.sh to exit cleanly when called from installer.
# KEEP_GOING=1 causes an infinite loop — replace with env var so
# AI_INSTALLER_MODE=0 (set by installer) makes it exit after one run.
# Re-applied after every git checkout since the file is managed by git.
sed -i 's/^KEEP_GOING=1$/KEEP_GOING=${AI_INSTALLER_MODE:-1}/' "${WEBUI_DIR}/webui.sh"
log "webui.sh patched: KEEP_GOING=${AI_INSTALLER_MODE:-1}"

# =============================================================================
# Venv
# =============================================================================
step "Virtual environment"
VENV_DIR="${WEBUI_DIR}/venv"
VENV_PYTHON="${VENV_DIR}/bin/python"
VENV_PIP="${VENV_DIR}/bin/pip"
pip() { "${VENV_PIP}" "$@"; }

_need_venv=false
if [[ ! -d "${VENV_DIR}" ]]; then
    _need_venv=true
elif [[ ! -x "${VENV_PYTHON}" ]]; then
    rm -rf "${VENV_DIR}"; _need_venv=true
else
    _cur="$("${VENV_PYTHON}" --version 2>&1 | awk '{print $2}')"
    [[ "${_cur}" != "${TARGET_PY}" ]] && { rm -rf "${VENV_DIR}"; _need_venv=true; }
fi

if [[ "${_need_venv}" == true ]]; then
    log "Creating venv..."
    "${REQUIRED_PYTHON}" -m venv "${VENV_DIR}"
    "${VENV_PYTHON}" -m pip install --upgrade pip
    log "Installing setuptools (pinned <70 for pkg_resources compatibility)..."
    "${VENV_PIP}" install "setuptools<70" wheel

    log "Pre-installing torch (cu121) — must be before CLIP to prevent pip pulling wrong version..."
    # Install torch first so CLIP's dependency resolution sees it already satisfied.
    # Without this, pip grabs latest torch (cu130) when resolving CLIP's deps,
    # then --reinstall-torch has to replace it — wasting 500MB+ of downloads.
    "${VENV_PIP}" install \
        --find-links "${WHEELS_DIR}/localbuild/${PYTHON_ABI}" \
        torch==2.4.1+cu121 torchvision==0.19.1+cu121 \
        --index-url https://download.pytorch.org/whl/cu121

    log "Pre-installing CLIP with --no-build-isolation..."
    "${VENV_PIP}" install --no-build-isolation \
        --find-links "${WHEELS_DIR}/localbuild/${PYTHON_ABI}" \
        https://github.com/openai/CLIP/archive/d50d76daa670286dd6cacf3bcd80b5e4823fc8e1.zip

    log "Pre-installing xformers from wheel cache..."
    _xformers_whl="$(ls "${WHEELS_DIR}/localbuild/cp310/xformers-"*.whl 2>/dev/null | head -1)"
    if [[ -n "${_xformers_whl}" ]]; then
        "${VENV_PIP}" install "${_xformers_whl}" \
            && log "xformers installed from cache: $(basename "${_xformers_whl}")" \
            || warn "xformers cache install failed — A1111 will run without it"
    else
        warn "xformers not in wheel cache — skipping (A1111 runs without it)"
        warn "  To cache: ai_collect_wheels.py --venv <a1111_venv> --pkg xformers"
    fi
    log "Venv ready: $("${VENV_PYTHON}" --version)"
else
    log "Existing venv OK: $("${VENV_PYTHON}" --version)"
fi

# =============================================================================
# Shared resource tree + output symlink
# =============================================================================
# Only outputs are redirected — consistent with all other apps.
# Models stay in A1111's own dirs (stock standard install).
step "Output symlink"
mkdir -p "${AI_OUTPUTS}/A1111"
if [[ ! -e "${WEBUI_DIR}/outputs" ]]; then
    ln -s "${AI_OUTPUTS}/A1111" "${WEBUI_DIR}/outputs"
    log "  Linked: ${WEBUI_DIR}/outputs → ${AI_OUTPUTS}/A1111"
elif [[ ! -L "${WEBUI_DIR}/outputs" ]]; then
    _bak="${WEBUI_DIR}/outputs.bak.$(date +%s)"
    log "  Backing up outputs → ${_bak}"
    mv "${WEBUI_DIR}/outputs" "${_bak}"
    ln -s "${AI_OUTPUTS}/A1111" "${WEBUI_DIR}/outputs"
    log "  Linked: ${WEBUI_DIR}/outputs → ${AI_OUTPUTS}/A1111"
else
    log "  outputs symlink already in place"
fi

# =============================================================================
# Record + launch
# =============================================================================

echo ""
warn "Running webui.sh to complete dependency install (will not stay running)."
warn "Start the server afterwards with: ai_automatic"
echo ""
step "Launching webui.sh"
cd "${WEBUI_DIR}"

# Use local git mirrors if available — avoids network clones on reinstall.
# Create mirrors with: git clone --mirror <repo> AI-Shared-Resources/git-mirrors/<name>.git
# Falls back to network URLs if mirror not present.
_MIRRORS="${AI_SHARED}/git-mirrors"
_use_mirror() {
    local name="$1" var="$2" default="$3"
    local path="${_MIRRORS}/${name}.git"
    if [[ -d "${path}" ]]; then
        export "${var}"="file://${path}"
        log "Mirror: ${var} → file://${path}"
    else
        export "${var}"="${default}"
    fi
}
_use_mirror "stablediffusion"               STABLE_DIFFUSION_REPO    "${STABLE_DIFFUSION_REPO}"
_use_mirror "generative-models"             STABLE_DIFFUSION_XL_REPO "https://github.com/Stability-AI/generative-models.git"
_use_mirror "k-diffusion"                   K_DIFFUSION_REPO         "https://github.com/crowsonkb/k-diffusion.git"
_use_mirror "BLIP"                          BLIP_REPO                "https://github.com/salesforce/BLIP.git"
_use_mirror "stable-diffusion-webui-assets" ASSETS_REPO              "https://github.com/AUTOMATIC1111/stable-diffusion-webui-assets.git"
# --reinstall-torch forces TORCH_COMMAND even if CLIP dragged torch in already
# AI_INSTALLER_MODE=0 suppresses the KEEP_GOING loop in webui.sh so the
# installer exits cleanly instead of blocking. webui.sh must have the
# matching change: KEEP_GOING=${AI_INSTALLER_MODE:-1}
AI_INSTALLER_MODE=0 ./webui.sh --reinstall-torch

echo
echo "============================================================"
echo "  A1111 install complete"
echo "  Dir      : ${WEBUI_DIR}"
echo "  Python   : ${TARGET_PY}"
echo "  HF cache : ${HF_HOME}"
echo "  Port     : ${AI_PORT}"
echo "  Start    : ai_automatic"
echo "============================================================"
