#!/usr/bin/env bash
# =============================================================================
# ai_invokeai_install.sh  —  InvokeAI installer for Jethro
# =============================================================================
# Installs InvokeAI as a pip package into its own venv under AI_Apps/invokeai.
#
# InvokeAI differs from the other apps in one key way: it is a pip-installed
# package (not a cloned repo). Its own entry points (invokeai-configure,
# invokeai-web) set up internal structure on first run.
#
# This script:
#   - Ensures Python (via pyenv) and the venv are correct
#   - Installs the correct torch for the detected GPU driver
#   - Installs InvokeAI with xformers
#   - Runs invokeai-configure to initialise the directory structure
#   - Sets up the output symlink into AI_Outputs/
#   - Records the install in ai_conductor.json
#
# Safe to re-run. Use --update to upgrade, --rebuild to wipe venv.
#
# Usage:
#   ./ai_invokeai_install.sh           # install or continue
#   ./ai_invokeai_install.sh --update  # pip upgrade only
#   ./ai_invokeai_install.sh --rebuild # wipe venv, reinstall
# =============================================================================

set -euo pipefail

# =============================================================================
# Source shared config — co-located with this script
# =============================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.."; pwd)"
source "${SCRIPT_DIR}/ai_config.sh"
# =============================================================================
# Logging — timestamped log in logs/, lastrun symlink for quick access
# =============================================================================
LOGS_DIR="${SCRIPT_DIR}/logs"
mkdir -p "${LOGS_DIR}"
LOG_TIMESTAMP="$(date '+%Y-%m-%dT%H-%M-%S')"
LOG_FILE="${LOGS_DIR}/ai_invokeai_install.${LOG_TIMESTAMP}.log"
exec > >(tee -a "${LOG_FILE}") 2>&1
ln -sf "${LOG_FILE}" "${LOGS_DIR}/ai_invokeai_install.lastrun.log"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ===== ai_invokeai_install started ====="

# =============================================================================
# Build environment
# =============================================================================
# No source builds needed for this app
ensure_build_env  # no source builds needed — no-op

# =============================================================================
# Paths
# =============================================================================
INSTALL_DIR="${AI_APPS}/invokeai"
VENV_DIR="${INSTALL_DIR}/.venv"
VENV_PYTHON="${VENV_DIR}/bin/python"
VENV_PIP="${VENV_DIR}/bin/pip"
pip() { "${VENV_PIP}" "$@"; }
TARGET_PYTHON="${PYTHON_VER_INVOKEAI}"
OUTPUTS_TARGET="${AI_OUTPUTS}/Invoke"

# =============================================================================
# Logging
# =============================================================================
mkdir -p "${INSTALL_DIR}"

log()  { local m="[$(date '+%Y-%m-%d %H:%M:%S')] $*"; echo "${m}"; echo "${m}" >> "${LOG_FILE}"; }
step() { echo; echo "==> $*"; log "STEP: $*"; }
warn() { echo "  WARN: $*"; log "WARN: $*"; }

# =============================================================================
# Mode
# =============================================================================
case "${1:-}" in
    --update)  MODE="update"  ;;
    --rebuild) MODE="rebuild" ;;
    "")        MODE="install" ;;
    *) echo "Usage: $(basename "$0") [--update | --rebuild]"; exit 1 ;;
esac

# =============================================================================
# Preflight
# =============================================================================
step "Preflight"
echo "  Install dir : ${INSTALL_DIR}"
echo "  Python      : ${TARGET_PYTHON}"
echo "  CUDA        : ${TORCH_CUDA}"
echo "  Driver      : ${PROBE_DRIVER_VERSION} (max CUDA: ${PROBE_DRIVER_CUDA_MAX})"
echo "  HF_HOME     : ${HF_HOME}"
echo "  Output dir  : ${OUTPUTS_TARGET}"
echo "  Port        : ${AI_PORT}"

[[ ! -d "${AI_TARGET}" ]] && { echo "ERROR: Drive not mounted? ${AI_TARGET} not found."; exit 1; }

# Optional but useful: offer gcc if missing
if [[ -z "${GCC_VER:-}" ]]; then
    ai_offer_install_apt "gcc-13" "gcc-13 (improves optional CUDA extension builds)" || true
    ai_offer_install_apt "g++-13" "g++-13" || true
fi

# =============================================================================
# --rebuild: wipe venv
# =============================================================================
if [[ "${MODE}" == "rebuild" && -d "${VENV_DIR}" ]]; then
    step "Wiping venv for rebuild"
    rm -rf "${VENV_DIR}"
    log "Removed: ${VENV_DIR}"
fi

# =============================================================================
# --update: upgrade package only
# =============================================================================
if [[ "${MODE}" == "update" ]]; then
    step "Updating InvokeAI"
    [[ ! -f "${VENV_PYTHON}" ]] && { echo "ERROR: No venv found. Run without --update first."; exit 1; }
    # Ensure pip binary exists in venv — InvokeAI's own installer doesn't always create it
    if [[ ! -x "${VENV_PIP}" ]]; then
        log "Installing pip into venv..."
        "${VENV_PYTHON}" -m ensurepip --upgrade
        "${VENV_PYTHON}" -m pip install --upgrade pip
    fi
    source "${VENV_DIR}/bin/activate"
    pip install --upgrade "invokeai[xformers]"
    log "Updated."

    # Record update in conductor JSON
    _torch_ver="$(python -c "import torch; print(torch.__version__)" 2>/dev/null || echo "unknown")"

    # Collect any updated wheels into cache
    if [[ "${AI_INSTALLER_MODE:-}" == "1" ]]; then
        echo "  Wheel collection handled by ai_installer."
    else
        python3 "${SCRIPT_DIR}/pylib/ai_collect_wheels.py" --venv "${INSTALL_DIR}/.venv" \
            && echo "  Wheel cache updated." || true
    fi
    echo; echo "Done. Start with: ai_invokeai"
    exit 0
fi

# =============================================================================
# Python via pyenv
# =============================================================================
step "Python ${TARGET_PYTHON}"
require_python "${TARGET_PYTHON}"

# =============================================================================
# Venv
# =============================================================================
step "Virtual environment"

_need_venv=false
if [[ ! -d "${VENV_DIR}" ]]; then
    _need_venv=true; log "No venv — creating."
elif [[ ! -x "${VENV_PYTHON}" ]]; then
    rm -rf "${VENV_DIR}"; _need_venv=true; log "Broken venv — rebuilding."
else
    _cur="$("${VENV_PYTHON}" --version 2>&1 | awk '{print $2}')"
    if [[ "${_cur}" != "${TARGET_PYTHON}" ]]; then
        rm -rf "${VENV_DIR}"; _need_venv=true
        log "Version mismatch (${_cur} != ${TARGET_PYTHON}) — rebuilding."
    else
        log "Existing venv OK: ${_cur}"
    fi
fi

if [[ "${_need_venv}" == true ]]; then
    "${REQUIRED_PYTHON}" -m venv "${VENV_DIR}"
    "${VENV_PIP}" install --upgrade pip setuptools wheel
    log "Created: $("${VENV_PYTHON}" --version)"
fi
# Ensure pip binary exists in venv — InvokeAI's own installer doesn't always create it
if [[ ! -x "${VENV_PIP}" ]]; then
    log "Installing pip into venv..."
    "${VENV_PYTHON}" -m ensurepip --upgrade
    "${VENV_PYTHON}" -m pip install --upgrade pip
fi

source "${VENV_DIR}/bin/activate"

# =============================================================================
# InvokeAI + Torch
# Strategy:
#   1. Install InvokeAI first — let pip resolve torch freely so we know
#      what version InvokeAI actually needs (declared as torch~=2.7.0 etc)
#   2. Read the torch version pip installed
#   3. Find the highest CUDA tag that has a wheel for that torch version,
#      not exceeding system max — may be lower than TORCH_CUDA if InvokeAI
#      hasn't caught up with the latest torch release
#   4. Re-install torch at that CUDA tag
#   5. Report to the user if we had to step down
# =============================================================================
step "InvokeAI (initial install — torch will be re-pinned after)"

_cur_invoke="$(python -c "import importlib.metadata; print(importlib.metadata.version('invokeai'))" 2>/dev/null || echo "none")"

if [[ "${_cur_invoke}" != "none" && "${MODE}" == "install" ]]; then
    log "InvokeAI ${_cur_invoke} already installed."
    read -r -p "  Re-install / upgrade? [y/N]: " _ans
    [[ "${_ans,,}" == "y" ]] && pip install --upgrade "invokeai[xformers]"
else
    # rebuild or fresh install — always install without prompting
    # Use --extra-index-url so pip can find CUDA wheels but still resolves
    # InvokeAI's own torch version constraint from pyproject.toml
    pip install "invokeai[xformers]"         --extra-index-url "https://download.pytorch.org/whl/${TORCH_CUDA}"
fi

_invoke_ver="$(python -c "import importlib.metadata; print(importlib.metadata.version('invokeai'))" 2>/dev/null || echo "unknown")"

# Read what torch version InvokeAI's resolver actually chose (base version only)
_invoke_torch_base="$(python -c "import torch; v=torch.__version__; print(v.split('+')[0])" 2>/dev/null || echo "")"

step "PyTorch CUDA re-pin"
if [[ -n "${_invoke_torch_base}" ]]; then
    log "InvokeAI resolved torch ${_invoke_torch_base} — finding best CUDA tag..."
    resolve_torch_for_app "invokeai" "${_invoke_torch_base}" "${TORCH_CUDA}"
    print_torch_constraint_notice "invokeai"

    # Re-install torch at the best available CUDA tag
    _cur_torch="$(python -c "import torch; print(torch.__version__)" 2>/dev/null || echo "none")"
    if [[ "${_cur_torch}" != "${RESOLVED_TORCH}" ]]; then
        log "Re-pinning torch: ${_cur_torch} → ${RESOLVED_TORCH}"
        pip install             "torch==${RESOLVED_TORCH}"             "torchvision==${RESOLVED_TORCHVISION}"             "torchaudio==${RESOLVED_TORCHAUDIO}"             --index-url "${RESOLVED_TORCH_INDEX}"             --find-links "${WHEELS_DIR}/localbuild/${PYTHON_ABI}"
    else
        log "torch already at ${RESOLVED_TORCH} — no re-pin needed."
    fi
else
    warn "Could not determine InvokeAI torch version — falling back to system CUDA."
    resolve_torch "${TORCH_CUDA}"
    pip install         "torch==${RESOLVED_TORCH}"         "torchvision==${RESOLVED_TORCHVISION}"         "torchaudio==${RESOLVED_TORCHAUDIO}"         --index-url "${RESOLVED_TORCH_INDEX}"         --find-links "${WHEELS_DIR}/localbuild/${PYTHON_ABI}"
fi

_torch_ver="$(python -c "import torch; print(torch.__version__)" 2>/dev/null || echo "unknown")"
log "InvokeAI ${_invoke_ver} | torch ${_torch_ver}"

# =============================================================================
# Initialise InvokeAI root
# --yes skips interactive prompts
# --skip-sd-weights avoids pulling a large default model at install time;
#   the user downloads models via the UI after first launch.
# =============================================================================
step "InvokeAI root init"

if [[ ! -f "${INSTALL_DIR}/invokeai.yaml" ]]; then
    log "Running invokeai-configure --root ${INSTALL_DIR} ..."
    invokeai-configure \
        --root "${INSTALL_DIR}" \
        --yes \
        --skip-sd-weights \
    || warn "invokeai-configure reported warnings — usually non-fatal. Check above."
else
    log "Already configured (invokeai.yaml exists)."
fi

# =============================================================================
# Output symlink
# AI_Outputs/Invoke/ ← INSTALL_DIR/outputs
# =============================================================================
step "Output symlink"
mkdir -p "${OUTPUTS_TARGET}"
_link="${INSTALL_DIR}/outputs"

if [[ -L "${_link}" ]]; then
    _cur_tgt="$(readlink -f "${_link}" 2>/dev/null || true)"
    _want_tgt="$(readlink -f "${OUTPUTS_TARGET}" 2>/dev/null || echo "${OUTPUTS_TARGET}")"
    if [[ "${_cur_tgt}" == "${_want_tgt}" ]]; then
        log "Symlink already correct."
    else
        log "Updating symlink → ${OUTPUTS_TARGET}"
        rm "${_link}"; ln -s "${OUTPUTS_TARGET}" "${_link}"
    fi
elif [[ -d "${_link}" ]]; then
    _n="$(find "${_link}" -type f 2>/dev/null | wc -l)"
    if [[ "${_n}" -gt 0 ]]; then
        warn "outputs/ has ${_n} file(s) — NOT replacing with symlink to avoid data loss."
        warn "  Run ai_migrate_resources.sh --migrate-outputs to move them first."
    else
        rmdir "${_link}"; ln -s "${OUTPUTS_TARGET}" "${_link}"
        log "Replaced empty dir with symlink → ${OUTPUTS_TARGET}"
    fi
else
    ln -s "${OUTPUTS_TARGET}" "${_link}"
    log "Created: ${_link} → ${OUTPUTS_TARGET}"
fi

# =============================================================================
# Verify
# =============================================================================
step "Verification"
python - <<PYCHECK
import sys
print(f"  Python   : {sys.version.split()[0]}")
try:
    import torch
    print(f"  torch    : {torch.__version__}")
    avail = torch.cuda.is_available()
    print(f"  CUDA     : {avail}")
    if avail:
        print(f"  GPU      : {torch.cuda.get_device_name(0)}")
        gb = torch.cuda.get_device_properties(0).total_memory / 1024**3
        print(f"  VRAM     : {gb:.1f} GB")
except ImportError as e:
    print(f"  torch    : MISSING ({e})")
try:
    import invokeai
    import importlib.metadata
    print(f"  invokeai : {importlib.metadata.version('invokeai')}")
except ImportError as e:
    print(f"  invokeai : MISSING ({e})")
try:
    import xformers
    print(f"  xformers : {xformers.__version__}")
except ImportError:
    print("  xformers : not installed (optional)")
PYCHECK

# =============================================================================
# Record in conductor JSON
# =============================================================================

# =============================================================================
# Done
# =============================================================================
echo
echo "============================================================"
echo "  InvokeAI install complete"
echo "  Dir      : ${INSTALL_DIR}"
echo "  Python   : ${TARGET_PYTHON}"
echo "  torch    : ${_torch_ver}"
echo "  InvokeAI : ${_invoke_ver}"
echo "  HF cache : ${HF_HOME}"
echo "  Port     : ${AI_PORT}"
echo "  Outputs  : ${OUTPUTS_TARGET}"
echo ""
echo "  First launch completes initialisation."
echo "  Download models via the InvokeAI UI after launch."
echo "  Start with: ai_invokeai"
echo "============================================================"
log "Complete: InvokeAI ${_invoke_ver}"
