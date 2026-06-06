#!/usr/bin/env bash
# =============================================================================
# ai_wan2gp_install.sh  —  Wan2GP installer for Jethro
# =============================================================================
# Targets Python 3.11.9 (pyenv) + PyTorch cu124/cu130 (auto-detected).
#
# Optimisation stack (all cp311 — zero software-imposed limitations):
#   SageAttention 2.2.0  — source build, ~40% faster attention
#   Triton               — enables torch.compile
#   Nunchaku             — INT4/INT8 quantised kernels (cp311 wheel)
#   GGUF / llama.cpp     — CUDA GGUF kernels for prompt enhancer (cp311 wheel)
#   Flash Attention      — optional fallback attention backend
#
# CUDA notes:
#   PyTorch cu130 wheels bundle their own CUDA 13.0 runtime — the host nvcc
#   is NOT used to run PyTorch. Host nvcc IS used for source builds
#   (SageAttention2, Flash Attention) — CUDA 12.3 nvcc handles sm86 fine.
#
# Safe to re-run — git pull and pip install are idempotent.
#
# Usage:
#   ./ai_wan2gp_install.sh           # fresh install or continue
#   ./ai_wan2gp_install.sh --update  # git pull + pip sync only
#   ./ai_wan2gp_install.sh --rebuild # wipe venv and reinstall
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
LOG_FILE="${LOGS_DIR}/ai_wan2gp_install.${LOG_TIMESTAMP}.log"
exec > >(tee -a "${LOG_FILE}") 2>&1
ln -sf "${LOG_FILE}" "${LOGS_DIR}/ai_wan2gp_install.lastrun.log"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ===== ai_wan2gp_install started ====="

# =============================================================================
# Build environment
# =============================================================================
# Validate build environment — sets CC, CXX, CUDA_HOME
INSTALL_DIR="${AI_APPS}/Wan2GP"
VENV_DIR="${INSTALL_DIR}/venv"
ensure_build_env "${VENV_DIR}/bin/python" || exit 1

# =============================================================================
# Paths — all derived from config
# =============================================================================


TARGET_PYTHON_VERSION="${PYTHON_VER_WAN2GP}"
OUTPUTS_TARGET="${AI_OUTPUTS}/Wan2GP"

# Python ABI tag for wheel matching (e.g. 3.11.9 → cp311)
PYTHON_ABI="cp$(echo "${TARGET_PYTHON_VERSION}" | awk -F. '{print $1$2}')"
ARCH="linux_x86_64"

# deepbeepmeep/kernels GitHub release base
KERNELS_RELEASE_BASE="https://github.com/deepbeepmeep/kernels/releases/latest/download"

# =============================================================================
# Helpers
# =============================================================================
step() { echo; echo "==> $*"; }
warn() { echo "  WARN: $*"; }
pip()  { "${VENV_DIR}/bin/pip" "$@"; }

# Install a prebuilt wheel from deepbeepmeep/kernels.
install_deepbeep_wheel() {
    local pkg_name="$1"
    local description="$2"
    local tmp_dir
    tmp_dir="$(mktemp -d)"

    step "Installing ${description} (${PYTHON_ABI} wheel from deepbeepmeep/kernels)"

    local api_url="https://api.github.com/repos/deepbeepmeep/kernels/releases/latest"
    local asset_url
    asset_url=$(
        curl -fsSL "${api_url}" 2>/dev/null \
        | grep '"browser_download_url"' \
        | grep "${pkg_name}" \
        | grep "${PYTHON_ABI}" \
        | grep "${ARCH}" \
        | head -1 \
        | sed 's/.*"browser_download_url": *"\([^"]*\)".*/\1/'
    ) || true

    if [[ -z "${asset_url}" ]]; then
        warn "${description}: could not find ${PYTHON_ABI} wheel in deepbeepmeep/kernels releases."
        warn "  Check https://github.com/deepbeepmeep/kernels/releases manually."
        warn "  Skipping — non-fatal; feature will be unavailable."
        rm -rf "${tmp_dir}"
        return 0
    fi

    local wheel_file="${tmp_dir}/$(basename "${asset_url}")"
    echo "  Downloading: ${asset_url}"
    if curl -fsSL -o "${wheel_file}" "${asset_url}"; then
        pip install "${wheel_file}" \
            && echo "  OK: ${description} installed" \
            || warn "${description} wheel install failed — skipping"
    else
        warn "${description}: download failed — skipping"
    fi
    rm -rf "${tmp_dir}"
}


# =============================================================================
# Mode: --update
# =============================================================================
if [[ "${1:-}" == "--update" ]]; then
    step "Pulling latest Wan2GP"
    cd "${INSTALL_DIR}"
    git pull
    step "Syncing pip dependencies"
    source "${VENV_DIR}/bin/activate"
    pip install -r requirements.txt
    # Collect any updated wheels into cache
    if [[ "${AI_INSTALLER_MODE:-}" == "1" ]]; then
        echo "  Wheel collection handled by ai_installer."
    else
        python3 "${SCRIPT_DIR}/pylib/ai_collect_wheels.py" --venv "${VENV_DIR}" \
            && echo "  Wheel cache updated." || true
    fi
    echo; echo "Update complete. Start with: ai_wan2gp"
    exit 0
fi


# =============================================================================
# Preflight
# =============================================================================
step "Preflight checks"
echo "  Install dir :q ${INSTALL_DIR}"
echo "  Python      : ${TARGET_PYTHON_VERSION} (${PYTHON_ABI})"
echo "  CUDA        : ${TORCH_CUDA}"
echo "  Driver      : ${PROBE_DRIVER_VERSION} (max CUDA: ${PROBE_DRIVER_CUDA_MAX})"
echo "  HF_HOME     : ${HF_HOME}"

[[ ! -d "${AI_TARGET}" ]] && { echo "ERROR: Drive not mounted? ${AI_TARGET} not found."; exit 1; }

if [[ -z "${GCC_VER:-}" ]]; then
    echo "ERROR: No versioned gcc found. Required for CUDA extension source builds."
    echo "  Install with: sudo apt install gcc-13 g++-13"
    exit 1
fi
echo "  gcc         : ${CC} ($(${CC} --version | head -1))"

if [[ "${PROBE_NVCC_VERSION}" == "none" ]]; then
    echo "ERROR: nvcc not found. Required for CUDA extension source builds."
    exit 1
fi
echo "  nvcc        : ${PROBE_NVCC_VERSION}"

# =============================================================================
# Mode: --rebuild
# =============================================================================
if [[ "${1:-}" == "--rebuild" && -d "${VENV_DIR}" ]]; then
    step "Removing existing venv for rebuild"
    rm -rf "${VENV_DIR}"
    echo "  Removed: ${VENV_DIR}"
fi


# =============================================================================
# Python via pyenv
# =============================================================================
step "Python ${TARGET_PYTHON_VERSION}"
require_python "${TARGET_PYTHON_VERSION}"

# =============================================================================
# Clone / pull
# =============================================================================
step "Wan2GP repo"
mkdir -p "${AI_APPS}"
if [[ -d "${INSTALL_DIR}/.git" ]]; then
    echo "  Repo exists — pulling"
    cd "${INSTALL_DIR}" && git pull
else
    git clone https://github.com/deepbeepmeep/Wan2GP.git "${INSTALL_DIR}"
fi
cd "${INSTALL_DIR}"

# =============================================================================
# Venv
# =============================================================================
step "Virtual environment"
if [[ ! -d "${VENV_DIR}" ]]; then
    "${REQUIRED_PYTHON}" -m venv "${VENV_DIR}"
    echo "  Created: ${VENV_DIR}"
else
    echo "  venv exists — skipping (use --rebuild to wipe)"
fi
source "${VENV_DIR}/bin/activate"
pip install --upgrade pip setuptools wheel

# =============================================================================
# Torch — dynamic resolution with fallback
# =============================================================================
step "PyTorch (${TORCH_CUDA})"
resolve_torch "${TORCH_CUDA}"

_cur_torch="$(python -c "import torch; print(torch.__version__)" 2>/dev/null || echo "none")"
if [[ "${_cur_torch}" == "${RESOLVED_TORCH}" ]]; then
    echo "  torch ${RESOLVED_TORCH} already installed — skipping."
else
    pip install \
        "torch==${RESOLVED_TORCH}" \
        "torchvision==${RESOLVED_TORCHVISION}" \
        "torchaudio==${RESOLVED_TORCHAUDIO}" \
        --index-url "${RESOLVED_TORCH_INDEX}" \
        --find-links "${WHEELS_DIR}/localbuild/${PYTHON_ABI}"
fi

# =============================================================================
# Triton
# =============================================================================
step "Triton"
pip install triton || warn "Triton install failed — torch.compile unavailable"

# =============================================================================
# Wan2GP requirements
# =============================================================================
step "Wan2GP requirements"
pip install -r requirements.txt

# =============================================================================
# SageAttention — wheel cache first, source build only if needed
# =============================================================================
step "SageAttention"
_TORCH_VER="$(python -c "import torch; v=torch.__version__.split('+')[0].split('.'); print(f'{v[0]}.{v[1]}')" 2>/dev/null || echo "2.12")"

if python3 "${SCRIPT_DIR}/pylib/ai_lib_wheels.py" install sageattention \
    --torch "${_TORCH_VER}" --cuda "${TORCH_CUDA}" --python "${PYTHON_ABI}" \
    --venv "${VENV_DIR}"; then
    echo "  SageAttention installed from cache."
elif [[ "${SAGE_V2_CAPABLE}" == "true" ]]; then
    echo "  No cached wheel — building SageAttention 2.2.0 from source..."
    pip install git+https://github.com/thu-ml/SageAttention.git@v2.2.0 \
        --no-build-isolation \
        && echo "  OK: SageAttention 2.2.0 built and installed" \
        && python3 "${SCRIPT_DIR}/pylib/ai_collect_wheels.py" --venv "${VENV_DIR}" --pkg sageattention \
        && python3 "${SCRIPT_DIR}/pylib/ai_config.py" record-wheel-build \
               --pkg sageattention --status ok \
        || { warn "SageAttention 2.2.0 build failed"
             python3 "${SCRIPT_DIR}/pylib/ai_config.py" record-wheel-build \
                 --pkg sageattention --status failed --reason "source build failed"; }
else
    echo "  Driver ${PROBE_DRIVER_VERSION} — skipping SageAttention 2.x (requires driver >= 570)"
    echo "  (Re-run --rebuild after upgrading driver to get SageAttention 2.x)"
fi

if ! python -c "import sageattention" 2>/dev/null; then
    pip install sageattention==1.0.6 \
        || warn "SageAttention 1.0.6 also failed — will use SDPA"
fi

SAGE_VER="$(python -c "import sageattention; print(getattr(sageattention, '__version__', '1.0.x'))" 2>/dev/null || echo "not installed")"
echo "  SageAttention: ${SAGE_VER}"

# =============================================================================
# Flash Attention (optional) — wheel cache first, source build only if needed
# =============================================================================
step "Flash Attention (optional)"
_TORCH_VER="$(python -c "import torch; v=torch.__version__.split('+')[0].split('.'); print(f'{v[0]}.{v[1]}')" 2>/dev/null || echo "2.12")"

if python3 "${SCRIPT_DIR}/pylib/ai_lib_wheels.py" install flash_attn \
    --torch "${_TORCH_VER}" --cuda "${TORCH_CUDA}" --python "${PYTHON_ABI}" \
    --venv "${VENV_DIR}"; then
    echo "  flash-attn installed from cache."
elif [[ "${SAGE_V2_CAPABLE}" == "true" ]]; then
    echo "  No cached wheel — building flash-attn from source (this takes 20-60 min)..."
    pip install flash-attn --no-build-isolation \
        && python3 "${SCRIPT_DIR}/pylib/ai_collect_wheels.py" --venv "${VENV_DIR}" --pkg flash_attn \
        && python3 "${SCRIPT_DIR}/pylib/ai_config.py" record-wheel-build \
               --pkg flash_attn --status ok \
        || { warn "Flash Attention build failed — SageAttention or SDPA will be used"
             python3 "${SCRIPT_DIR}/pylib/ai_config.py" record-wheel-build \
                 --pkg flash_attn --status failed --reason "source build failed"; }
else
    echo "  Skipped (requires driver >= 570, found ${PROBE_DRIVER_VERSION})"
fi

# =============================================================================
# Deepbeep kernel wheels (cp311, non-fatal if unavailable)
# =============================================================================
install_deepbeep_wheel "nunchaku"        "Nunchaku INT4/INT8 kernels"
install_deepbeep_wheel "llama_cpp_python" "GGUF llama.cpp CUDA kernels"

# =============================================================================
# Output symlink
# =============================================================================
step "Output symlink"
mkdir -p "${OUTPUTS_TARGET}"
if [[ ! -e "${INSTALL_DIR}/outputs" ]]; then
    ln -s "${OUTPUTS_TARGET}" "${INSTALL_DIR}/outputs"
    echo "  Linked: ${INSTALL_DIR}/outputs → ${OUTPUTS_TARGET}"
else
    echo "  outputs already exists — skipping symlink"
fi

# =============================================================================
# Verification
# =============================================================================
step "Verification"
python - <<'PYCHECK'
import sys
print(f"  Python      : {sys.version.split()[0]}")
try:
    import torch
    print(f"  PyTorch     : {torch.__version__}")
    print(f"  CUDA avail  : {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"  GPU         : {torch.cuda.get_device_name(0)}")
except ImportError as e:
    print(f"  PyTorch     : MISSING ({e})")
for mod, name in [("sageattention","SageAttn"),("triton","Triton"),
                  ("nunchaku","Nunchaku"),("llama_cpp","llama.cpp")]:
    try:
        m = __import__(mod)
        print(f"  {name:<12}: {getattr(m,'__version__','installed')}")
    except ImportError:
        print(f"  {name:<12}: not installed")
PYCHECK

_torch_ver="$(python -c "import torch; print(torch.__version__)" 2>/dev/null || echo "unknown")"

# =============================================================================
# Record in conductor JSON
# =============================================================================

# =============================================================================
# Done
# =============================================================================
echo
echo "============================================================"
echo "  Wan2GP install complete"
echo "  Install dir : ${INSTALL_DIR}"
echo "  Python      : ${TARGET_PYTHON_VERSION}"
echo "  PyTorch     : ${_torch_ver}"
echo "  SageAttn    : ${SAGE_VER}"
echo "  HF cache    : ${HF_HOME}"
echo "  Port        : ${AI_PORT}"
echo "  Outputs     : ${OUTPUTS_TARGET}"
echo "  Start with  : ai_wan2gp"
echo "============================================================"
