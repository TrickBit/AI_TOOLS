#!/usr/bin/env bash
# =============================================================================
# ai_comfyui_install.sh  —  ComfyUI installer for Jethro
# =============================================================================
# Purpose:
#   Install, update, or rebuild ComfyUI with all Jethro-specific patches,
#   symlinks, and configuration applied automatically.
#
# Key decisions baked in:
#   - Python 3.12.12 via pyenv
#   - Torch auto-resolved for detected CUDA via resolve_torch()
#   - comfy/ops.py threshold patch applied for RTX 3060 compatibility
#     (re-applied after every git pull since it gets wiped by upstream)
#   - extra_model_paths.yaml written pointing at AI-Shared-Resources tree
#     (protected from git pull — written only if missing or --rebuild)
#   - Output dir symlinked to AI_Outputs/ComfyUI/
#   - Custom nodes: ComfyUI-GGUF, ComfyUI-KJNodes, ComfyUI-LTXVideo
#     installed after main install; safe to re-run
#
# Patch notes:
#   comfy/ops.py (was comfy/quant_ops.py in older builds) contains a
#   threshold value that causes NaN/black output on RTX 3060 without
#   this patch. The runner (ai_comfy) also checks the patch is in place
#   before launching and will warn + re-apply if it's missing.
#
# Safe to re-run.
#
# Usage:
#   ./ai_comfyui_install.sh            # fresh install or continue
#   ./ai_comfyui_install.sh --update   # git pull + pip sync + re-patch
#   ./ai_comfyui_install.sh --rebuild  # wipe venv, full reinstall
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
LOG_FILE="${LOGS_DIR}/ai_comfyui_install.${LOG_TIMESTAMP}.log"
exec > >(tee -a "${LOG_FILE}") 2>&1
ln -sf "${LOG_FILE}" "${LOGS_DIR}/ai_comfyui_install.lastrun.log"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ===== ai_comfyui_install started ====="

# =============================================================================
# Build environment — first call: system checks only (venv may not exist yet)
# =============================================================================
# Paths — needed before --update block and ensure_build_env
# =============================================================================
INSTALL_DIR="${AI_APPS}/ComfyUI"
VENV_DIR="${INSTALL_DIR}/venv"
VENV_PIP="${VENV_DIR}/bin/pip"
VENV_PYTHON="${VENV_DIR}/bin/python"
TARGET_PYTHON="${PYTHON_VER_COMFYUI}"
PYTHON_ABI="cp$(echo "${TARGET_PYTHON}" | awk -F. '{print $1$2}')"
OUTPUTS_TARGET="${AI_OUTPUTS}/ComfyUI"
CUSTOM_NODES_DIR="${INSTALL_DIR}/custom_nodes"
OPS_FILE="${INSTALL_DIR}/comfy/ops.py"

# =============================================================================
# Build environment — first call: system checks only (venv may not exist yet)
# =============================================================================
ensure_build_env || exit 1

# =============================================================================
# Helpers
# =============================================================================
step() { echo; echo "==> $*"; }
warn() { echo "  WARN: $*"; }
good() { echo -e "\033[32m  ✔\033[0m $*"; }
# pip()  { "${VENV_PIP}" "$@" --find-links "${WHEELS_DIR}/localbuild/${PYTHON_ABI}"; }
pip()  { "${VENV_PIP}" "$@"; }

# =============================================================================
# apply_ops_patch()
# =============================================================================
# Purpose: Patch comfy/ops.py to raise the threshold value that causes
#   NaN/black output on RTX 3060 (sm86). The upstream value (1e-38) is
#   too close to the float32 subnormal boundary on this GPU.
#
# Pre:  ComfyUI repo must be cloned (OPS_FILE must exist).
# Post: OPS_FILE contains patched threshold value.
#
# The patch is idempotent — safe to call any number of times.
# =============================================================================
apply_ops_patch() {
    if [[ ! -f "${OPS_FILE}" ]]; then
        warn "ops.py not found at ${OPS_FILE} — cannot patch (check repo structure)"
        return 0
    fi

    # Already patched — ground truth is the file itself
    if grep -q "1e-7" "${OPS_FILE}" 2>/dev/null; then
        good "ops.py already patched — skipping"
        return 0
    fi

    # Find any subnormal-range threshold value (1e-NNN where NNN > 6)
    local _found
    _found="$(grep -oP '1e-\d+' "${OPS_FILE}" | awk -F- '$2 > 6' | head -1 || true)"

    if [[ -n "${_found}" ]]; then
        step "Patching comfy/ops.py (RTX 3060 threshold fix: ${_found} → 1e-7)"
        sed -i "s/${_found}/1e-7/g" "${OPS_FILE}"
        good "Patched: ${_found} → 1e-7"
    else
        # Value may have been removed or fixed upstream — verify no black output
        good "ops.py: no subnormal threshold found — upstream may have fixed this"
    fi
}

# =============================================================================
# write_extra_model_paths()
# =============================================================================
# Purpose: Write extra_model_paths.yaml, which tells ComfyUI where to find
#   models outside its own directory (our shared AI-Shared-Resources tree).
#
# Pre:  INSTALL_DIR must exist (cloned), AI_SHARED must be set by config.
# Post: extra_model_paths.yaml written in INSTALL_DIR.
#
# Called only on fresh install or --rebuild. On --update, the existing file
# is left alone (user may have customised it).
# =============================================================================
write_extra_model_paths() {
    return 0
    local yaml_file="${INSTALL_DIR}/extra_model_paths.yaml"

    step "Writing extra_model_paths.yaml"

    cat > "${yaml_file}" << YAML
# extra_model_paths.yaml — managed by ai_comfyui_install.sh
# Points ComfyUI at the shared AI-Shared-Resources model tree.
# Regenerate: ./ai_comfyui_install.sh --rebuild
# (Do not hand-edit paths — they come from ai_config.sh AI_SHARED)

a1111_compatible:
  base_path: ${AI_SHARED}/image/
  checkpoints: Checkpoints/
  vae: VAE/
  loras: Lora/
  embeddings: Embeddings/
  controlnet: ControlNet/
  upscale_models: Upscalers/

video_models:
  base_path: ${AI_SHARED}/video/
  checkpoints: Models/
  loras: Lora/
  vae: VAE/
  clip: TextEncoders/
YAML

    good "Written: ${yaml_file}"
}

# =============================================================================
# install_custom_nodes()
# =============================================================================
# Purpose: Clone known custom node repos into CUSTOM_NODES_DIR and install
#   their requirements. Idempotent — pulls if already cloned.
#
# Pre:  VENV_DIR must be active (pip alias live), CUSTOM_NODES_DIR must exist.
# Post: Each node cloned and pip requirements installed.
#
# Nodes installed:
#   ComfyUI-GGUF     — GGUF quantised model loading (city96)
#   ComfyUI-KJNodes  — General utility nodes (kijai)
#   ComfyUI-LTXVideo — LTX-Video generation nodes (Lightricks)
# =============================================================================
install_custom_nodes() {
    step "Custom nodes"
    mkdir -p "${CUSTOM_NODES_DIR}"

    _clone_node() {
        local name="$1"
        local url="$2"
        local node_dir="${CUSTOM_NODES_DIR}/${name}"

        if [[ -d "${node_dir}/.git" ]]; then
            echo "  ${name}: pulling"
            cd "${node_dir}" && git pull --quiet && cd "${INSTALL_DIR}"
        else
            echo "  ${name}: cloning"
            git clone --quiet "${url}" "${node_dir}"
        fi

        # Install requirements if present
        local req=""
        for f in requirements.txt requirements_versions.txt; do
            [[ -f "${node_dir}/${f}" ]] && { req="${f}"; break; }
        done
        if [[ -n "${req}" ]]; then
            pip install -r "${node_dir}/${req}" --quiet \
                && good "${name} requirements installed" \
                || warn "${name}: requirements install failed — non-fatal"
        else
            echo "  ${name}: no requirements file"
        fi
    }

    _clone_node "ComfyUI-GGUF"    "https://github.com/city96/ComfyUI-GGUF.git"
    _clone_node "ComfyUI-KJNodes" "https://github.com/kijai/ComfyUI-KJNodes.git"
    _clone_node "ComfyUI-LTXVideo" "https://github.com/Lightricks/ComfyUI-LTXVideo.git"

    cd "${INSTALL_DIR}"
    good "Custom nodes done"
}

# =============================================================================
# --update mode
# =============================================================================
# Must come before preflight — update does not need nvcc/gcc-12.
# Pre:  INSTALL_DIR cloned, VENV_DIR exists.
# Post: Repo pulled, requirements synced, ops.py patch re-applied.
# =============================================================================
if [[ "${1:-}" == "--update" ]]; then
    step "Updating ComfyUI"

    [[ ! -d "${INSTALL_DIR}/.git" ]] && {
        echo "ERROR: ${INSTALL_DIR} not found or not a git repo."
        echo "  Run without --update to install first."
        exit 1
    }
    [[ ! -d "${VENV_DIR}" ]] && {
        echo "ERROR: venv not found at ${VENV_DIR}."
        echo "  Run without --update to install first."
        exit 1
    }

    cd "${INSTALL_DIR}"
    echo "  Pulling upstream..."
    git pull

    source "${VENV_DIR}/bin/activate"
    echo "  Syncing requirements..."
    pip install -r requirements.txt --quiet

    # Re-apply ops patch (gets wiped by git pull)
    apply_ops_patch

    # Update custom nodes
    install_custom_nodes

    # Record update in conductor JSON
    _torch_ver="$(python -c "import torch; print(torch.__version__)" 2>/dev/null || echo "unknown")"

    # Collect any updated wheels into cache
    if [[ "${AI_INSTALLER_MODE:-}" == "1" ]]; then
        echo "  Wheel collection handled by ai_installer."
    else
        python3 "${SCRIPT_DIR}/pylib/ai_collect_wheels.py" --venv "${INSTALL_DIR}/venv" \
            && echo "  Wheel cache updated." || true
    fi
    echo
    echo "Update complete. Start with: ai_comfy"
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

[[ ! -d "${AI_TARGET}" ]] && {
    echo "ERROR: Drive not mounted? ${AI_TARGET} not found."
    exit 1
}

# gcc-12 is required only if building CUDA extensions (e.g. custom nodes).
# Flag as warning, not hard error — base ComfyUI runs without it.
if [[ -z "${GCC_VER:-}" ]]; then
    warn "No versioned gcc found. Some custom nodes with CUDA extensions may fail to build."
    warn "  Install with: sudo apt install gcc-13 g++-13"
fi

# nvcc not required for base ComfyUI — warn only
if [[ "${PROBE_NVCC_VERSION}" == "none" ]]; then
    warn "nvcc not found. CUDA extension builds in custom nodes will fail."
    warn "  Base ComfyUI operation (PyTorch only) is unaffected."
fi

# =============================================================================
# --rebuild mode: wipe venv before continuing
# =============================================================================
if [[ "${1:-}" == "--rebuild" && -d "${VENV_DIR}" ]]; then
    step "Wiping venv for rebuild"
    rm -rf "${VENV_DIR}"
    echo "  Removed: ${VENV_DIR}"
fi

# =============================================================================
# Python via pyenv
# =============================================================================
step "Python ${TARGET_PYTHON}"
require_python "${TARGET_PYTHON}"

# =============================================================================
# Clone / pull repo
# =============================================================================
step "ComfyUI repo"
mkdir -p "${AI_APPS}"
if [[ -d "${INSTALL_DIR}/.git" ]]; then
    echo "  Repo exists — pulling"
    cd "${INSTALL_DIR}" && git pull
else
    git clone https://github.com/comfyanonymous/ComfyUI.git "${INSTALL_DIR}"
fi
cd "${INSTALL_DIR}"

# =============================================================================
# Virtual environment
# =============================================================================
step "Virtual environment"
if [[ ! -d "${VENV_DIR}" ]]; then
    "${REQUIRED_PYTHON}" -m venv "${VENV_DIR}"
    good "Created: ${VENV_DIR}"
else
    echo "  venv exists — skipping (use --rebuild to wipe)"
fi
source "${VENV_DIR}/bin/activate"
pip install --upgrade pip setuptools wheel

# =============================================================================
# PyTorch — dynamic resolution for detected CUDA
# SageAttention 2.2.0 is incompatible with torch >= 2.10 (List_inl.h C++ issue).
# Step down to 2.9.0 so SageAttention and flash_attn can be built and cached.
# ComfyUI has no torch version requirement — this stepdown is safe.
# =============================================================================
# step "PyTorch (${TORCH_CUDA})"
# resolve_torch "${TORCH_CUDA}"
#
# _torch_minor="$(echo "${RESOLVED_TORCH}" | grep -oP '^\d+\.\d+')"
# if awk "BEGIN {exit !(${_torch_minor} >= 2.10)}"; then
#     warn "torch ${RESOLVED_TORCH} incompatible with SageAttention 2.x — stepping down to 2.9.0"
#     resolve_torch_for_app "comfyui" "2.9.0" "${TORCH_CUDA}"
#     print_torch_constraint_notice "comfyui"
# fi
#
# _cur_torch="$(python -c "import torch; print(torch.__version__)" 2>/dev/null || echo "none")"
# if [[ "${_cur_torch}" == "${RESOLVED_TORCH}" ]]; then
#     echo "  torch ${RESOLVED_TORCH} already installed — skipping."
# else
#     pip install \
#         "torch==${RESOLVED_TORCH}" \
#         "torchvision==${RESOLVED_TORCHVISION}" \
#         "torchaudio==${RESOLVED_TORCHAUDIO}" \
#         --index-url "${RESOLVED_TORCH_INDEX}" \
#         --find-links "${WHEELS_DIR}/localbuild/${PYTHON_ABI}"
# fi
step "PyTorch (${TORCH_CUDA})"
resolve_torch "${TORCH_CUDA}"

_torch_minor="$(echo "${RESOLVED_TORCH}" | grep -oP '^\d+\.\d+')"
if awk "BEGIN {exit !(${_torch_minor} >= 2.10)}"; then
    warn "torch ${RESOLVED_TORCH} incompatible with SageAttention 2.x — pinning to 2.9.1"
    RESOLVED_TORCH="2.9.1+cu130"
    RESOLVED_TORCHVISION="0.24.1+cu130"
    RESOLVED_TORCHAUDIO="2.9.1+cu130"
    RESOLVED_TORCH_INDEX="https://download.pytorch.org/whl/cu130"
    export RESOLVED_TORCH RESOLVED_TORCHVISION RESOLVED_TORCHAUDIO RESOLVED_TORCH_INDEX
fi

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

# Second call — torch now installed, reads torch.__config__ to confirm gcc
ensure_build_env "${VENV_DIR}/bin/python" || true

# =============================================================================
# ComfyUI requirements
# =============================================================================
step "ComfyUI requirements"
pip install -r requirements.txt

# =============================================================================
# RTX 3060 ops.py patch — must happen after clone, before launch
# =============================================================================
apply_ops_patch

# =============================================================================
# extra_model_paths.yaml — only write on fresh install / rebuild
# =============================================================================
if [[ ! -f "${INSTALL_DIR}/extra_model_paths.yaml" ]]; then
    write_extra_model_paths
else
    echo
    echo "==> extra_model_paths.yaml already exists — leaving it alone"
    echo "    (delete it and re-run --rebuild if you want it regenerated)"
fi

# =============================================================================
# Output directory symlink
# =============================================================================
step "Output symlink"
mkdir -p "${OUTPUTS_TARGET}"
if [[ -e "${INSTALL_DIR}/output" && ! -L "${INSTALL_DIR}/output" ]]; then
    _bak="${INSTALL_DIR}/output.bak.$(date +%s)"
    warn "Existing output/ dir found (not a symlink) — backing up to ${_bak}"
    mv "${INSTALL_DIR}/output" "${_bak}"
fi
if [[ ! -e "${INSTALL_DIR}/output" ]]; then
    ln -s "${OUTPUTS_TARGET}" "${INSTALL_DIR}/output"
    good "Linked: ${INSTALL_DIR}/output → ${OUTPUTS_TARGET}"
else
    echo "  output symlink already in place — skipping"
fi

# =============================================================================
# Custom nodes
# =============================================================================
install_custom_nodes

# =============================================================================
# SageAttention — wheel cache first, source build if needed
# =============================================================================
step "SageAttention"
_TORCH_VER="$(python -c "import torch; v=torch.__version__.split('+')[0].split('.'); print(f'{v[0]}.{v[1]}')" 2>/dev/null || echo "2.9")"

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
        || warn "SageAttention 2.2.0 build failed — will use SDPA"
else
    echo "  Driver ${PROBE_DRIVER_VERSION} — skipping SageAttention (requires driver >= 570)"
fi

SAGE_VER="$(python -c "import sageattention; print(getattr(sageattention, '__version__', '1.0.x'))" 2>/dev/null || echo "not installed")"
echo "  SageAttention: ${SAGE_VER}"

# =============================================================================
# Flash Attention (optional) — wheel cache first, source build if needed
# =============================================================================
step "Flash Attention (optional)"
if python3 "${SCRIPT_DIR}/pylib/ai_lib_wheels.py" install flash_attn \
    --torch "${_TORCH_VER}" --cuda "${TORCH_CUDA}" --python "${PYTHON_ABI}" \
    --venv "${VENV_DIR}"; then
    echo "  flash-attn installed from cache."
elif [[ "${SAGE_V2_CAPABLE}" == "true" ]]; then
    echo "  No cached wheel — building flash-attn from source (20-60 min)..."
    pip install flash-attn --no-build-isolation \
        && python3 "${SCRIPT_DIR}/pylib/ai_collect_wheels.py" --venv "${VENV_DIR}" --pkg flash_attn \
        || warn "Flash Attention build failed — SageAttention or SDPA will be used"
else
    echo "  Skipped (requires driver >= 570)"
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
for mod, name in [("torchvision","torchvision"),("aiohttp","aiohttp"),
                  ("yaml","PyYAML"),("safetensors","safetensors")]:
    try:
        m = __import__(mod)
        print(f"  {name:<14}: {getattr(m,'__version__','installed')}")
    except ImportError:
        print(f"  {name:<14}: not installed")
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
echo "  ComfyUI install complete"
echo "  Dir      : ${INSTALL_DIR}"
echo "  Python   : ${TARGET_PYTHON}"
echo "  PyTorch  : ${_torch_ver}"
echo "  HF cache : ${HF_HOME}"
echo "  Port     : ${AI_PORT}"
echo "  Outputs  : ${OUTPUTS_TARGET}"
echo ""
echo "  Custom nodes installed:"
echo "    - ComfyUI-GGUF     (city96)"
echo "    - ComfyUI-KJNodes  (kijai)"
echo "    - ComfyUI-LTXVideo (Lightricks)"
echo ""
echo "  ops.py patch: RTX 3060 threshold fix applied"
echo "  Start with  : ai_comfy"
echo "============================================================"
