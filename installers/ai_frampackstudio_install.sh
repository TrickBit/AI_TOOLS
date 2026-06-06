#!/usr/bin/env bash
# =============================================================================
# ai_frampackstudio_install.sh  —  FramePack-Studio installer for Jethro
# =============================================================================
# Installs FramePack-Studio (lllyasviel/FramePack-Studio).
# First-run model download: ~30GB (Hunyuan Video F1) on first launch.
#
# Safe to re-run.
# Usage:
#   ./ai_frampackstudio_install.sh           # install or continue
#   ./ai_frampackstudio_install.sh --update  # git pull + pip sync
#   ./ai_frampackstudio_install.sh --rebuild # wipe venv, reinstall
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.."; pwd)"
source "${SCRIPT_DIR}/ai_config.sh"
# =============================================================================
# Logging — timestamped log in logs/, lastrun symlink for quick access
# =============================================================================
LOGS_DIR="${SCRIPT_DIR}/logs"
mkdir -p "${LOGS_DIR}"
LOG_TIMESTAMP="$(date '+%Y-%m-%dT%H-%M-%S')"
LOG_FILE="${LOGS_DIR}/ai_frampackstudio_install.${LOG_TIMESTAMP}.log"
exec > >(tee -a "${LOG_FILE}") 2>&1
ln -sf "${LOG_FILE}" "${LOGS_DIR}/ai_frampackstudio_install.lastrun.log"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ===== ai_frampackstudio_install started ====="

# =============================================================================
# Paths — needed before --update block and ensure_build_env
# =============================================================================
INSTALL_DIR="${AI_APPS}/FramePack"
VENV_DIR="${INSTALL_DIR}/venv"

# =============================================================================
# Build environment — first call: system checks only (venv may not exist yet)
# =============================================================================
ensure_build_env || exit 1

TARGET_PYTHON="${PYTHON_VER_FRAMPACKSTUDIO}"
PYTHON_ABI="cp$(echo "${TARGET_PYTHON}" | awk -F. '{print $1$2}')"
OUTPUTS_TARGET="${AI_OUTPUTS}/FramePack-Studio"

step()  { echo; echo "==> $*"; }
warn()  { echo "  WARN: $*"; }
pip()   { "${VENV_DIR}/bin/pip" "$@"; }

# =============================================================================
# --rebuild mode: wipe venv before preflight
# =============================================================================
if [[ "${1:-}" == "--rebuild" && -d "${VENV_DIR}" ]]; then
    step "Wiping venv for rebuild"
    rm -rf "${VENV_DIR}"
fi

# =============================================================================
# --update mode: git pull + pip sync only — no nvcc/gcc needed
# =============================================================================
if [[ "${1:-}" == "--update" ]]; then
    step "Updating FramePack-Studio"
    cd "${INSTALL_DIR}" && git pull
    source "${VENV_DIR}/bin/activate"
    pip install -r requirements.txt 2>/dev/null \
        || pip install -r requirements_versions.txt 2>/dev/null \
        || warn "No requirements file found."

    # Record update in conductor JSON
    _torch_ver="$(python -c "import torch; print(torch.__version__)" 2>/dev/null || echo "unknown")"

    # Collect any updated wheels into cache
    if [[ "${AI_INSTALLER_MODE:-}" == "1" ]]; then
        echo "  Wheel collection handled by ai_installer."
    else
        python3 "${SCRIPT_DIR}/pylib/ai_collect_wheels.py" --venv "${VENV_DIR}" \
            && echo "  Wheel cache updated." || true
    fi
    echo; echo "Update complete. Start with: ai_frampackstudio"
    exit 0
fi

# =============================================================================
# Preflight — only needed for fresh install / rebuild
# =============================================================================
step "Preflight"
echo "  Install dir : ${INSTALL_DIR}"
echo "  Python      : ${TARGET_PYTHON}"
echo "  CUDA        : ${TORCH_CUDA}"
echo "  Driver      : ${PROBE_DRIVER_VERSION}"
echo "  HF_HOME     : ${HF_HOME}"

[[ ! -d "${AI_TARGET}" ]] && { echo "ERROR: Drive not mounted? ${AI_TARGET} not found."; exit 1; }

# gcc version check handled by ensure_build_env above

if [[ "${PROBE_NVCC_VERSION}" == "none" ]]; then
    echo "ERROR: nvcc not found. Required for CUDA extension builds."
    exit 1
fi

# =============================================================================
# Python + clone + venv
# =============================================================================
step "Python ${TARGET_PYTHON}"
require_python "${TARGET_PYTHON}"

step "FramePack-Studio repo"
mkdir -p "${AI_APPS}"
if [[ -d "${INSTALL_DIR}/.git" ]]; then
    echo "  Repo exists — pulling"
    cd "${INSTALL_DIR}" && git pull
else
    git clone https://github.com/lllyasviel/FramePack.git "${INSTALL_DIR}"
fi
cd "${INSTALL_DIR}"

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
# Torch
# =============================================================================
step "PyTorch (${TORCH_CUDA})"
resolve_torch "${TORCH_CUDA}"
pip install \
    "torch==${RESOLVED_TORCH}" \
    "torchvision==${RESOLVED_TORCHVISION}" \
    "torchaudio==${RESOLVED_TORCHAUDIO}" \
    --index-url "${RESOLVED_TORCH_INDEX}" \
    --find-links "${WHEELS_DIR}/localbuild/${PYTHON_ABI}"

# Second call — torch now installed, reads torch.__config__ to confirm gcc
ensure_build_env "${VENV_DIR}/bin/python" || true

# =============================================================================
# Triton + requirements
# =============================================================================
step "Triton"
pip install triton || warn "Triton failed — torch.compile unavailable"

step "Pre-installing basicsr (avoids build stall in requirements)"
# basicsr's PEP 517 build backend stalls fetching backend deps when called
# from inside a requirements.txt install. Pre-install its build deps first,
# then install basicsr itself with --no-build-isolation to use what's already
# in the venv rather than spawning an isolated build environment.
pip install "numpy<2" scipy Pillow pyyaml tb-nightly lmdb \
    || warn "basicsr pre-deps partially failed — continuing"
pip install basicsr --no-build-isolation \
    || warn "basicsr pre-install failed — will retry during requirements (may stall)"

step "FramePack-Studio requirements"
if [[ -f requirements_versions.txt ]]; then
    pip install -r requirements_versions.txt
elif [[ -f requirements.txt ]]; then
    pip install -r requirements.txt
else
    warn "No requirements file — installing known dependencies"
    pip install gradio diffusers transformers accelerate huggingface-hub \
        einops safetensors opencv-python imageio imageio-ffmpeg \
        av scipy sentencepiece
fi

# =============================================================================
# SageAttention — wheel cache first, source build only if needed
# =============================================================================
step "SageAttention"
_TORCH_MINOR="$(python -c "import torch; v=torch.__version__.split('+')[0].split('.'); print(v[0]+v[1])" 2>/dev/null || echo "")"
_TORCH_VER="$(python -c "import torch; v=torch.__version__.split('+')[0].split('.'); print(f'{v[0]}.{v[1]}')" 2>/dev/null || echo "2.12")"

if python3 "${SCRIPT_DIR}/pylib/ai_lib_wheels.py" install sageattention \
    --torch "${_TORCH_VER}" --cuda "${TORCH_CUDA}" --python "${PYTHON_ABI:-cp311}" \
    --venv "${VENV_DIR}"; then
    echo "  SageAttention installed from cache."
elif [[ "${SAGE_V2_CAPABLE}" == "true" ]]; then
    echo "  No cached wheel — building SageAttention 2.2.0 from source..."
    pip install git+https://github.com/thu-ml/SageAttention.git@v2.2.0 \
        --no-build-isolation \
        && echo "  OK: SageAttention 2.2.0 built and installed" \
        && python3 "${SCRIPT_DIR}/pylib/ai_collect_wheels.py" --venv "${VENV_DIR}" --pkg sageattention \
        || { warn "SageAttention 2.2.0 build failed"
             python3 "${SCRIPT_DIR}/pylib/ai_config.py" record-wheel-build \
                 --pkg sageattention --status failed --reason "source build failed"; }
else
    echo "  Driver ${PROBE_DRIVER_VERSION} — skipping SageAttention 2.x (requires driver >= 570)"
fi

if ! python -c "import sageattention" 2>/dev/null; then
    pip install sageattention==1.0.6 || warn "SageAttention 1.0.6 also failed — will use SDPA"
fi

SAGE_VER="$(python -c "import sageattention; print(getattr(sageattention, '__version__', '1.0.x'))" 2>/dev/null || echo "not installed")"
echo "  SageAttention: ${SAGE_VER}"

# =============================================================================
# Flash Attention (optional) — wheel cache first, source build only if needed
# =============================================================================
step "Flash Attention (optional)"
_TORCH_VER="$(python -c "import torch; v=torch.__version__.split('+')[0].split('.'); print(f'{v[0]}.{v[1]}')" 2>/dev/null || echo "2.12")"

if python3 "${SCRIPT_DIR}/pylib/ai_lib_wheels.py" install flash_attn \
    --torch "${_TORCH_VER}" --cuda "${TORCH_CUDA}" --python "${PYTHON_ABI:-cp311}" \
    --venv "${VENV_DIR}"; then
    echo "  flash-attn installed from cache."
else
    echo "  No cached wheel — building flash-attn from source (this takes 20-60 min)..."
    pip install flash-attn --no-build-isolation \
        && python3 "${SCRIPT_DIR}/pylib/ai_collect_wheels.py" --venv "${VENV_DIR}" --pkg flash_attn \
        && python3 "${SCRIPT_DIR}/pylib/ai_config.py" record-wheel-build \
               --pkg flash_attn --status ok \
        || { warn "Flash Attention build failed — SageAttention or SDPA will be used"
             python3 "${SCRIPT_DIR}/pylib/ai_config.py" record-wheel-build \
                 --pkg flash_attn --status failed --reason "source build failed"; }
fi

# =============================================================================
# Output symlink
# =============================================================================
step "Output symlink"
mkdir -p "${OUTPUTS_TARGET}"
if [[ ! -e "${INSTALL_DIR}/outputs" ]]; then
    ln -s "${OUTPUTS_TARGET}" "${INSTALL_DIR}/outputs"
    echo "  Linked: ${INSTALL_DIR}/outputs → ${OUTPUTS_TARGET}"
else
    echo "  outputs already exists — skipping"
fi

# =============================================================================
# Verify + record
# =============================================================================
step "Verification"
python - <<PYCHECK
import sys
print(f"  Python   : {sys.version.split()[0]}")
for mod, name in [("torch","PyTorch"),("sageattention","SageAttn"),
                  ("triton","Triton"),("gradio","Gradio"),("diffusers","Diffusers")]:
    try:
        m = __import__(mod)
        v = getattr(m,'__version__','installed')
        if name == "PyTorch":
            import torch
            v += f"  CUDA:{torch.cuda.is_available()}"
            if torch.cuda.is_available():
                v += f"  GPU:{torch.cuda.get_device_name(0)}"
        print(f"  {name:<12}: {v}")
    except ImportError as e:
        print(f"  {name:<12}: MISSING ({e})")
PYCHECK

_torch_ver="$(python -c "import torch; print(torch.__version__)" 2>/dev/null || echo "unknown")"

echo
echo "============================================================"
echo "  FramePack-Studio install complete"
echo "  Dir      : ${INSTALL_DIR}"
echo "  Python   : ${TARGET_PYTHON}"
echo "  PyTorch  : ${_torch_ver}"
echo "  HF cache : ${HF_HOME}"
echo "  Port     : ${AI_PORT}"
echo "  Outputs  : ${OUTPUTS_TARGET}"
echo ""
echo "  First launch downloads ~30GB Hunyuan Video F1 models."
echo "  Ensure drive has space before starting."
echo "  Start with: ai_frampackstudio"
echo "============================================================"
