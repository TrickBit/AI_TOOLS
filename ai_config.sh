#!/usr/bin/env bash
# =============================================================================
# ai_config.sh  —  Jethro AI stack shared configuration
# =============================================================================
# SOURCE this file; do not execute directly.
# All ai_* scripts must be co-located with this file and ai_installer.json.
#
# Usage in every installer and runner:
#   source "$(dirname "${BASH_SOURCE[0]}")/ai_config.sh"
#
# Exports after sourcing:
#   Paths   : AI_TARGET  AI_APPS  AI_SHARED  AI_OUTPUTS  AI_WORK  HF_HOME
#             WHEELS_DRIVE  WHEELS_DIR
#   CUDA    : CUDA_HOME  TORCH_CUDA  TORCH_INDEX  DRIVER_MAJOR
#   Caps    : SAGE_V2_CAPABLE
#   Build   : CC  CXX  GCC_VER
#   Port    : AI_PORT
#   Pythons : PYTHON_VER_{AUTOMATIC,WAN2GP,FRAMPACKSTUDIO,INVOKEAI,COMFYUI}
#   Probe   : PROBE_GPU  PROBE_VRAM_GB  PROBE_DRIVER_VERSION  PROBE_DRIVER_MAJOR
#             PROBE_DRIVER_CUDA_MAX  PROBE_TORCH_CUDA  PROBE_TORCH_INDEX
#             PROBE_SAGE_V2_CAPABLE  PROBE_NVCC_VERSION  PROBE_GCC12_PRESENT
#             PROBE_DEBIAN_VERSION
#   Funcs   : probe_system
#             require_python <version>
#             resolve_torch [cuda_tag]
#             resolve_torch_for_app <app> <required_base> <system_cuda_tag>
#             print_torch_constraint_notice <app>
#             ai_record_install <app> <status> <python_ver> <torch_ver>
#             ai_offer_install_apt <pkg> <desc>
#             _jq <query>
#             _jq_str <query>
# =============================================================================

[[ -n "${_AI_CONFIG_LOADED:-}" ]] && return 0
_AI_CONFIG_LOADED=1

# =============================================================================
# Self-location
# =============================================================================
_AI_CONFIG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export AI_TOOLS_ROOT="${_AI_CONFIG_DIR}"
export AI_INSTALLER_JSON="${_AI_CONFIG_DIR}/ai_installer.json"

# =============================================================================
# Colours
# =============================================================================
_c_cyan='\033[36m'; _c_yellow='\033[33m'; _c_red='\033[31m'
_c_green='\033[32m'; _c_nc='\033[0m'; _c_dim='\033[2m'
_cfg_info()  { echo -e "${_c_cyan}[config]${_c_nc} $*" >&2; }
_cfg_warn()  { echo -e "${_c_yellow}[config WARN]${_c_nc} $*" >&2; }
_cfg_error() { echo -e "${_c_red}[config ERROR]${_c_nc} $*" >&2; }
_cfg_die()   { _cfg_error "$*"; return 1; }



# =============================================================================
# getinput <prompt> <result_var>
# =============================================================================
# Beeps to alert the user, then reads a single line of input.
# Use in place of bare 'read -r -p' for all interactive prompts.
#
# Usage:
#   getinput "Install now? [Y/n]: " answer
#   [[ "${answer:-y}" =~ ^[Nn]$ ]] && ...
# =============================================================================
getinput() {
    local prompt="$1"
    local result_var="$2"
    printf '\a'
    read -r -p "${prompt}" "${result_var}"
}


# =============================================================================
# sudo_keepalive_start / sudo_keepalive_stop
# =============================================================================
# Refreshes sudo token every 60s in background — no system files touched.
# Call start once at the top of any script that uses sudo, stop at exit.
# =============================================================================
_SUDO_KEEPALIVE_PID=""

sudo_keepalive_start() {
    printf '\a'
    sudo -v || return 1
    ( while true; do sudo -n true; sleep 60; done ) &
    _SUDO_KEEPALIVE_PID=$!
    _cfg_info "sudo keepalive started (pid ${_SUDO_KEEPALIVE_PID})"
}

sudo_keepalive_stop() {
    if [[ -n "${_SUDO_KEEPALIVE_PID:-}" ]]; then
        kill "${_SUDO_KEEPALIVE_PID}" 2>/dev/null || true
        _cfg_info "sudo keepalive stopped"
        _SUDO_KEEPALIVE_PID=""
    fi
}


# =============================================================================
# Safe apt-install offer
# Only userspace packages — never drivers, kernel modules, or anything that
# modifies hardware configuration.
# =============================================================================
ai_offer_install_apt() {
    local pkg="$1"
    local desc="${2:-${pkg}}"
    dpkg -s "${pkg}" &>/dev/null && return 0
    echo ""
    _cfg_warn "${desc} (${pkg}) is not installed."
    getinput "  Install now? (sudo apt install ${pkg}) [Y/n]: " _ans
    [[ "${_ans:-y}" =~ ^[Nn]$ ]] && {
        _cfg_warn "${pkg} skipped — some features may be unavailable."
        return 1
    }
    sudo apt-get install -y "${pkg}"
    dpkg -s "${pkg}" &>/dev/null && { _cfg_info "${pkg} installed."; return 0; }
    _cfg_die "${pkg} installation failed."
    return 1
}

# =============================================================================
# Ensure jq
# =============================================================================
if ! command -v jq &>/dev/null; then
    ai_offer_install_apt "jq" "jq (required for JSON config parsing)" || {
        _cfg_error "jq is required. Cannot continue."
        return 1
    }
fi

# =============================================================================
# JSON helpers — available to all sourcing scripts
# =============================================================================
_jq()     { jq -r "$1" "${AI_INSTALLER_JSON}"; }
_jq_str() { jq -r "$1 // empty" "${AI_INSTALLER_JSON}"; }

# =============================================================================
# probe_system()
# =============================================================================
# System probe for bash — reads GPU/driver/CUDA/tools
# JSON persistence is owned by ai_installer.py (ai_lib_probe.run()).
# Bash callers get env vars via the /tmp cache; only the installer writes JSON.
#
# Can be called directly to force a fresh probe:
#   probe_system force    # skips /tmp cache, re-probes
# =============================================================================


probe_system() {
    _cfg_info "Probing system..."

    # --- GPU ---
    local gpu vram_gb
    gpu="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null \
        | head -1 | xargs || echo 'not found')"
    vram_gb="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null \
        | head -1 | awk '{printf "%.0f", $1/1024}' || echo '0')"

    # --- Driver ---
    local driver_version driver_major
    driver_version="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null \
        | head -1 | xargs || echo '0.0.0')"
    driver_major="$(echo "${driver_version}" | cut -d. -f1)"

    # --- Driver → max CUDA → torch tag ---
    local driver_cuda_max torch_cuda
    if   [[ "${driver_major}" -ge 570 ]]; then driver_cuda_max="13.0"; torch_cuda="cu130"
    elif [[ "${driver_major}" -ge 545 ]]; then driver_cuda_max="12.6"; torch_cuda="cu126"
    elif [[ "${driver_major}" -ge 525 ]]; then driver_cuda_max="12.4"; torch_cuda="cu124"
    elif [[ "${driver_major}" -ge 520 ]]; then driver_cuda_max="12.0"; torch_cuda="cu121"
    elif [[ "${driver_major}" -ge 510 ]]; then driver_cuda_max="11.8"; torch_cuda="cu118"
    else                                       driver_cuda_max="11.x";  torch_cuda="cu118"
    fi

    # --- SageAttention v2 (driver >= 570) ---
    local sage_v2="false"
    [[ "${driver_major}" -ge 570 ]] && sage_v2="true"

    # --- nvcc ---
    local nvcc_ver="none"
    command -v nvcc &>/dev/null && \
        nvcc_ver="$(nvcc --version 2>/dev/null \
            | grep 'release' | sed 's/.*release \([0-9.]*\).*/\1/' || echo 'unknown')"

    # --- gcc-12 ---
    local gcc12="false"
    command -v gcc-12 &>/dev/null && gcc12="true"

    # --- git ---
    local git_present="false"
    command -v git &>/dev/null && git_present="true"

    # --- pyenv ---
    local pyenv_present="false"
    local pyenv_root="${PYENV_ROOT:-$HOME/.pyenv}"
    [[ -d "${pyenv_root}" ]] && pyenv_present="true"

    # --- Debian version ---
    local debian="unknown"
    [[ -f /etc/debian_version ]] && debian="$(cat /etc/debian_version)"

    local now
    now="$(date -Iseconds)"

# Export probe vars directly — no /tmp cache needed
    PROBE_GPU="${gpu}"
    PROBE_VRAM_GB="${vram_gb}"
    PROBE_DRIVER_VERSION="${driver_version}"
    PROBE_DRIVER_MAJOR="${driver_major}"
    PROBE_DRIVER_CUDA_MAX="${driver_cuda_max}"
    PROBE_TORCH_CUDA="${torch_cuda}"
    PROBE_TORCH_INDEX="https://download.pytorch.org/whl/${torch_cuda}"
    PROBE_SAGE_V2_CAPABLE="${sage_v2}"
    PROBE_NVCC_VERSION="${nvcc_ver}"
    PROBE_GCC12_PRESENT="${gcc12}"
    PROBE_GIT_PRESENT="${git_present}"
    PROBE_PYENV_PRESENT="${pyenv_present}"
    PROBE_DEBIAN_VERSION="${debian}"
    PROBE_AT="${now}"
    _cfg_info "Probe: ${gpu} | driver ${driver_version} | ${torch_cuda} | sage_v2=${sage_v2}"
}

# =============================================================================
# Read config — requires JSON to exist
# =============================================================================
if [[ ! -f "${AI_INSTALLER_JSON}" ]]; then
    _cfg_error "ai_installer.json not found. Run: ai_installer.py --init"
    return 1
fi

# Paths
# AI_TARGET is set by the conductor via ACTIVE_TARGET before sourcing this file.
# Fall back to config.active_target in JSON for backwards compatibility,
# then to config.target_dir for very old JSON files.
if [[ -z "${AI_TARGET:-}" ]]; then
    _target="$(_jq_str '.config.active_target // .config.target_dir // empty')"
    _target="${_target/#\~/$HOME}"
    export AI_TARGET="${_target}"
fi
[[ -z "${AI_TARGET:-}" ]] && { _cfg_error "No active target set. Run ai_installer.py --init to initialise."; return 1; }

export AI_APPS="${AI_TARGET}/$(_jq '.config.apps_subdir')"
export AI_SHARED="${AI_TARGET}/$(_jq '.config.resources_subdir')"
export AI_OUTPUTS="${AI_TARGET}/$(_jq '.config.outputs_subdir')"
export AI_WORK="${AI_TARGET}/$(_jq '.config.work_subdir')"
export HF_HOME="${AI_SHARED}/huggingface"
export AI_PORT="$(_jq '.config.port')"

# Wheels cache — independent of active target, lives on permanent drive
_wheels_drive="$(_jq_str '.config.wheels_drive // empty')"
if [[ -n "${_wheels_drive}" ]]; then
    export WHEELS_DRIVE="${_wheels_drive}"
    export WHEELS_DIR="${WHEELS_DRIVE}/AI_Collected_Wheels"
else
    # Fallback for pre-init or missing config — use permanent drive
    export WHEELS_DRIVE="/mnt/BACKUP_4.0_TB"
    export WHEELS_DIR="${WHEELS_DRIVE}/AI_Collected_Wheels"
    _cfg_warn "config.wheels_drive not set — defaulting to ${WHEELS_DRIVE}"
    _cfg_warn "  Fix with: python3 ai_config.py set config wheels_drive /mnt/BACKUP_4.0_TB"
fi

# Python versions
export PYTHON_VER_AUTOMATIC="$(_jq '.config.python.automatic')"
export PYTHON_VER_WAN2GP="$(_jq         '.config.python.wan2gp')"
export PYTHON_VER_FRAMPACKSTUDIO="$(_jq '.config.python.frampackstudio')"
export PYTHON_VER_INVOKEAI="$(_jq       '.config.python.invokeai')"
export PYTHON_VER_COMFYUI="$(_jq        '.config.python.comfyui')"

# Run probe (uses /tmp cache if available)
probe_system

# CUDA_HOME
if [[ "${PROBE_NVCC_VERSION}" != "none" && "${PROBE_NVCC_VERSION}" != "unknown" ]]; then
    _cuda_home="/usr/local/cuda-${PROBE_NVCC_VERSION%.*}"
    [[ ! -d "${_cuda_home}" ]] && _cuda_home="/usr/local/cuda"
else
    _cuda_home="/usr/local/cuda"
fi
[[ ! -d "${_cuda_home}" ]] && _cuda_home=""
export CUDA_HOME="${_cuda_home}"
[[ -n "${CUDA_HOME}" ]] && {
    export PATH="${CUDA_HOME}/bin:${PATH}"
    export LD_LIBRARY_PATH="${CUDA_HOME}/lib64:${LD_LIBRARY_PATH:-}"
}

# Exported probe values
export DRIVER_MAJOR="${PROBE_DRIVER_MAJOR}"
export TORCH_CUDA="${PROBE_TORCH_CUDA}"
export TORCH_INDEX="${PROBE_TORCH_INDEX}"
export SAGE_V2_CAPABLE="${PROBE_SAGE_V2_CAPABLE}"

# Compiler — find highest available gcc (needed for torch 2.12+ extension builds)
# We set CC/CXX here as defaults; ensure_build_env() overrides with the exact
# version torch was built with when a venv is present.
GCC_VER=""
for _v in 14 13 12 11 10; do
    if command -v "gcc-${_v}" &>/dev/null; then
        GCC_VER="${_v}"
        break
    fi
done
if [[ -n "${GCC_VER}" ]]; then
    export CC="gcc-${GCC_VER}"
    export CXX="g++-${GCC_VER}"
    export GCC_VER
else
    export CC=gcc; export CXX=g++; export GCC_VER=""
    _cfg_warn "No versioned gcc found (gcc-10 through gcc-14). CUDA extension builds may fail."
    _cfg_warn "  Install with: sudo apt install gcc-13 g++-13"
fi

# Soft warning if config not yet approved
if [[ "$(_jq_str '.meta.approved')" != "true" ]]; then
    _cfg_warn "Config not yet confirmed. Run: ai_installer.py --confirm or re-run --init"
fi

# =============================================================================
# require_python <version>
# =============================================================================
require_python() {
    local version="$1"
    export PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}"

    if [[ ! -d "${PYENV_ROOT}" ]]; then
        _cfg_info "pyenv not found — installing privately to ${PYENV_ROOT}..."
        curl -fsSL https://pyenv.run | bash
        export PATH="${PYENV_ROOT}/bin:${PATH}"
        eval "$(pyenv init -)" 2>/dev/null || true
        if [[ ! -d "${PYENV_ROOT}" ]]; then
            _cfg_die "pyenv install failed."
            return 1
        fi
        _cfg_info "pyenv installed. Note: add the following to ~/.bashrc if not already present:"
        echo '  export PYENV_ROOT="$HOME/.pyenv"'
        echo '  export PATH="$PYENV_ROOT/bin:$PATH"'
        echo '  eval "$(pyenv init -)"'
    fi

    export PATH="${PYENV_ROOT}/bin:${PATH}"
    eval "$(pyenv init -)" 2>/dev/null || true

    if ! pyenv versions --bare 2>/dev/null | sed 's/^ *//' | grep -qx "${version}"; then
        _cfg_info "Installing Python ${version} via pyenv..."
        pyenv install "${version}"
    fi

    local py_path
    py_path="$(PYENV_VERSION="${version}" pyenv which python 2>/dev/null || true)"
    [[ -z "${py_path}" ]] && { _cfg_die "Python ${version} unavailable after install."; return 1; }

    export REQUIRED_PYTHON="${py_path}"
    _cfg_info "Python ${version}: ${REQUIRED_PYTHON}"
}

# =============================================================================
# resolve_torch [cuda_tag]
# =============================================================================
resolve_torch() {
    local cuda_tag="${1:-${TORCH_CUDA}}"
    local index="https://download.pytorch.org/whl/${cuda_tag}"
    local py_abi
    py_abi="cp$(python3 -c 'import sys; print(f"{sys.version_info.major}{sys.version_info.minor}")' 2>/dev/null || echo '311')"

    _cfg_info "Resolving torch for ${cuda_tag} (${py_abi})..."

    _resolve_pkg() {
        local pkg="$1"; local ver=""
        for naming in "manylinux_2_28_x86_64" "linux_x86_64"; do
            ver="$(curl -fsSL --max-time 15 "${index}/${pkg}/" 2>/dev/null \
                | grep -oP "(?<=>)${pkg}-[0-9][^+]+\+${cuda_tag}-${py_abi}-${py_abi}-${naming}\.whl(?=<)" \
                | grep -oP "[0-9]+\.[0-9]+\.[0-9]+" \
                | sort -V | tail -1 || true)"
            [[ -n "${ver}" ]] && break
        done
        echo "${ver}"
    }

    local tv tvv ta
    tv="$(_resolve_pkg torch)"; tvv="$(_resolve_pkg torchvision)"; ta="$(_resolve_pkg torchaudio)"

    if [[ -z "${tv}" || -z "${tvv}" || -z "${ta}" ]]; then
        _cfg_warn "Dynamic resolution failed — using pinned fallback for ${cuda_tag}."
        tv="$(_jq_str ".config.torch_fallbacks.\"${cuda_tag}\".torch")"
        tvv="$(_jq_str ".config.torch_fallbacks.\"${cuda_tag}\".torchvision")"
        ta="$(_jq_str ".config.torch_fallbacks.\"${cuda_tag}\".torchaudio")"
        [[ -z "${tv}" ]] && { _cfg_die "No fallback for ${cuda_tag}."; return 1; }
    else
        tv="${tv}+${cuda_tag}"; tvv="${tvv}+${cuda_tag}"; ta="${ta}+${cuda_tag}"
    fi

    export RESOLVED_TORCH="${tv}"
    export RESOLVED_TORCHVISION="${tvv}"
    export RESOLVED_TORCHAUDIO="${ta}"
    export RESOLVED_TORCH_INDEX="${index}"
    _cfg_info "torch=${tv}"
}


# =============================================================================
# resolve_torch_for_app <app> <required_torch_base> <system_cuda_tag>
# =============================================================================
# Finds the highest CUDA tag that has a wheel for the required torch base
# version (e.g. "2.7.1"), not exceeding the system's max CUDA tag.
#
# Sets RESOLVED_* exports (same as resolve_torch) plus:
#   TORCH_CONSTRAINED=true/false   — whether we had to step down from system max
#   TORCH_CONSTRAINT_REASON        — human-readable explanation if constrained
#   TORCH_CONSTRAINT_CUDA_USED     — the cuda tag actually used
#   TORCH_CONSTRAINT_CUDA_SYSTEM   — the system's max cuda tag
#   TORCH_CONSTRAINT_VER_REQUIRED  — the torch base version required by the app
#
# Usage:
#   resolve_torch_for_app "invokeai" "2.7.1" "${TORCH_CUDA}"
# =============================================================================
resolve_torch_for_app() {
    local app="$1"
    local required_base="$2"   # e.g. "2.7.1" — base version without +cuXXX
    local system_cuda="$3"     # e.g. "cu130"
    local py_abi
    py_abi="cp$(python3 -c 'import sys; print(f"{sys.version_info.major}{sys.version_info.minor}")' 2>/dev/null || echo '311')"

    # Ordered list of CUDA tags from highest to lowest
    local -a cuda_tags=("cu130" "cu128" "cu126" "cu124" "cu121" "cu118")

    # Find where the system max sits in the list and trim anything above it
    local -a candidates=()
    local found_system=false
    for tag in "${cuda_tags[@]}"; do
        if [[ "${tag}" == "${system_cuda}" ]]; then
            found_system=true
        fi
        [[ "${found_system}" == true ]] && candidates+=("${tag}")
    done
    # If system_cuda not in our list, just try them all
    [[ "${#candidates[@]}" -eq 0 ]] && candidates=("${cuda_tags[@]}")

    export TORCH_CONSTRAINED=false
    export TORCH_CONSTRAINT_REASON=""
    export TORCH_CONSTRAINT_CUDA_USED=""
    export TORCH_CONSTRAINT_CUDA_SYSTEM="${system_cuda}"
    export TORCH_CONSTRAINT_VER_REQUIRED="${required_base}"

    _cfg_info "Resolving torch ${required_base} for ${app} (system max: ${system_cuda})..."

    local tried=()
    for tag in "${candidates[@]}"; do
        tried+=("${tag}")
        local index="https://download.pytorch.org/whl/${tag}"
        # Check if the required base version exists at this tag
        local found_ver=""
        for naming in "manylinux_2_28_x86_64" "linux_x86_64"; do
            found_ver="$(curl -fsSL --max-time 15 "${index}/torch/" 2>/dev/null \
                | grep -oP "(?<=>)torch-[0-9][^+]+\+${tag}-${py_abi}-${py_abi}-${naming}\.whl(?=<)" \
                | grep -oP "[0-9]+\.[0-9]+\.[0-9]+" \
                | grep "^${required_base%.*}\." \
                | sort -V | tail -1 || true)"
            [[ -n "${found_ver}" ]] && break
        done

        if [[ -n "${found_ver}" ]]; then
            # Found a compatible wheel — now resolve torchvision and torchaudio too
            resolve_torch "${tag}"
            export TORCH_CONSTRAINT_CUDA_USED="${tag}"
            if [[ "${tag}" != "${system_cuda}" ]]; then
                export TORCH_CONSTRAINED=true
                export TORCH_CONSTRAINT_REASON="torch~=${required_base%.*}.x required by ${app}"
            fi
            return 0
        fi
        _cfg_info "  ${tag}: no torch ${required_base%.*}.x wheel — trying lower..."
    done

    # Nothing found — fall back to system cuda and let pip fight it out
    _cfg_warn "Could not find torch ${required_base} at any CUDA tag. Falling back to ${system_cuda}."
    resolve_torch "${system_cuda}"
    export TORCH_CONSTRAINED=true
    export TORCH_CONSTRAINT_CUDA_USED="${system_cuda}"
    export TORCH_CONSTRAINT_REASON="no compatible wheel found for torch~=${required_base%.*}.x (tried: ${tried[*]})"
    return 0
}

# =============================================================================
# print_torch_constraint_notice <app>
# =============================================================================
# Call after resolve_torch_for_app to print a user-facing notice if
# TORCH_CONSTRAINED=true. Explains what was done, what it means, and
# what the user can do about it.
# =============================================================================
print_torch_constraint_notice() {
    local app="$1"
    [[ "${TORCH_CONSTRAINED}" != "true" ]] && return 0

    local _c_yellow='\033[33m'; local _c_cyan='\033[36m'
    local _c_nc='\033[0m'; local _c_bold='\033[1m'

    echo ""
    echo -e "${_c_yellow}╔══════════════════════════════════════════════════════════════╗${_c_nc}"
    echo -e "${_c_yellow}║  NOTICE: App torch requirement below system capability       ║${_c_nc}"
    echo -e "${_c_yellow}╚══════════════════════════════════════════════════════════════╝${_c_nc}"
    echo ""
    echo -e "  ${_c_bold}App         :${_c_nc} ${app}"
    echo -e "  ${_c_bold}Reason      :${_c_nc} ${TORCH_CONSTRAINT_REASON}"
    echo ""
    echo -e "  ${_c_bold}System max  :${_c_nc} ${TORCH_CONSTRAINT_CUDA_SYSTEM} (driver supports up to CUDA ${TORCH_CONSTRAINT_CUDA_SYSTEM#cu})"
    echo -e "  ${_c_bold}Using       :${_c_nc} ${TORCH_CONSTRAINT_CUDA_USED} (torch ${RESOLVED_TORCH})"
    echo ""
    echo -e "  ${_c_bold}What this means for you:${_c_nc}"
    echo    "    • GPU acceleration still works fully — this is not a fallback to CPU"
    echo    "    • Slightly less efficient VRAM allocation vs torch 2.12 (newer memory"
    echo    "      management is not available in torch 2.7.x)"
    echo    "    • Some newer attention optimisations in torch 2.12 unavailable"
    echo    "    • SageAttention built for other apps may run at slightly lower"
    echo    "      efficiency within InvokeAI (different torch ABI)"
    echo    "    • No impact on image quality or model compatibility"
    echo ""
    echo -e "  ${_c_bold}This is not a driver or system problem.${_c_nc}"
    echo    "  ${app} has declared torch~=${TORCH_CONSTRAINT_VER_REQUIRED%.*}.x as its supported"
    echo    "  version. Your driver (${PROBE_DRIVER_VERSION}) is fine."
    echo ""
    echo -e "  ${_c_bold}How to get full cu${TORCH_CONSTRAINT_CUDA_SYSTEM#cu} support in ${app}:${_c_nc}"
    echo    "  Watch for a new ${app} release that bumps its torch requirement"
    echo    "  to 2.12.x or higher. When that happens, run:"
    echo    "    ai_${app}_install.sh --rebuild"
    echo    "  The installer will automatically detect and use ${TORCH_CONSTRAINT_CUDA_SYSTEM}."
    echo ""
    echo -e "${_c_yellow}══════════════════════════════════════════════════════════════════${_c_nc}"
    echo ""
}
# =============================================================================
# ai_record_install <app> <status> <python_ver> <torch_ver>
# =============================================================================
# STUB — JSON writes are owned by ai_installer.py (Python writes, bash reads).
# ai_installer.py records the install after dispatch_app() returns successfully.
# This stub keeps existing callers in ai_*_install.sh from breaking.
ai_record_install() {
    local app="$1"
    _cfg_info "ai_record_install: '${app}' — install record will be written by ai_installer.py."
}

# =============================================================================
# ensure_build_env [venv_python]
# =============================================================================
# Validates the build environment for CUDA extension compilation and sets
# CC, CXX, CUDA_HOME to compatible values.
#
# If venv_python is supplied and the venv exists, reads torch.__config__ to
# determine exactly which GCC version torch was built with and requires that
# version. Falls back to system-level check if venv doesn't exist yet.
#
# Returns:
#   0  — environment is ready, CC/CXX/CUDA_HOME exported
#   1  — environment not ready, clear message printed with fix instructions
#
# Usage in installers:
#   ensure_build_env "${VENV_DIR}/bin/python" || exit 1   # source builds needed
#   ensure_build_env                                       # no source builds, no-op
# =============================================================================
ensure_build_env() {
    local venv_python="${1:-}"
    local needs_source_build=false
    local issues=()

    # ── Determine if we actually need source build capability ──────────────
    # Called with no args = caller doesn't need source builds = no-op
    if [[ -z "${venv_python}" ]]; then
        return 0
    fi

    needs_source_build=true

    # ── Step 1: Determine required GCC version ─────────────────────────────
    local required_gcc=""
    local torch_gcc=""

    if [[ -x "${venv_python}" ]]; then
        # Venv exists — read what GCC torch was actually built with
        torch_gcc="$("${venv_python}" -c "
import torch, re
cfg = torch.__config__.show()
m = re.search(r'GCC (\d+)\.', cfg)
print(m.group(1) if m else '')
" 2>/dev/null || echo "")"
        if [[ -n "${torch_gcc}" ]]; then
            required_gcc="${torch_gcc}"
        fi
    fi

    # Fall back to highest available gcc if we couldn't read from venv
    if [[ -z "${required_gcc}" ]]; then
        for v in 14 13 12 11 10; do
            if command -v "gcc-${v}" &>/dev/null; then
                required_gcc="${v}"
                break
            fi
        done
    fi

    if [[ -z "${required_gcc}" ]]; then
        issues+=("No GCC found. Install with: sudo apt install gcc-13 g++-13")
    elif ! command -v "gcc-${required_gcc}" &>/dev/null; then
        issues+=("gcc-${required_gcc} not found (required by torch). Install: sudo apt install gcc-${required_gcc} g++-${required_gcc}")
    else
        export CC="gcc-${required_gcc}"
        export CXX="g++-${required_gcc}"
        _cfg_info "Build compiler: ${CC} ($(${CC} --version | head -1))"

        # ── Ensure 'gcc' resolves to required version ─────────────────────────
        # torch's build system invokes 'gcc' directly (not $CC), so the
        # update-alternatives default must match what we're building with.
        local _cur_gcc_major=""
        _cur_gcc_major="$(gcc --version 2>/dev/null | grep -oP '[0-9]+\.[0-9]+\.[0-9]+' | head -1 | cut -d. -f1 || echo '')"
        if [[ "${_cur_gcc_major}" != "${required_gcc}" ]]; then
            local _gcc_bin="/usr/bin/gcc-${required_gcc}"
            if [[ -x "${_gcc_bin}" ]]; then
                _cfg_info "Setting gcc alternative: gcc → gcc-${required_gcc} (was ${_cur_gcc_major:-?})..."
                _cfg_info "  (sudo needed to update /etc/alternatives/gcc — one-time per session)"
                if sudo update-alternatives --set gcc "${_gcc_bin}" 2>/dev/null; then
                    _cfg_info "gcc alternative updated ✔"
                else
                    _cfg_warn "Could not set gcc alternative (sudo failed or alternative not registered)."
                    _cfg_warn "  Fix manually: sudo update-alternatives --install /usr/bin/gcc gcc ${_gcc_bin} ${required_gcc}0"
                    _cfg_warn "               sudo update-alternatives --set gcc ${_gcc_bin}"
                fi
            fi
        fi
    fi

    # ── Step 2: Validate nvcc ──────────────────────────────────────────────
    local nvcc_path
    nvcc_path="$(command -v nvcc 2>/dev/null || echo "")"

    if [[ -z "${nvcc_path}" ]]; then
        issues+=("nvcc not found. Install: sudo apt install cuda-toolkit-13-3")
    else
        local nvcc_ver
        nvcc_ver="$(nvcc --version 2>/dev/null | grep -oP 'release \K[0-9]+\.[0-9]+'  || echo "")"

        # If venv exists, check nvcc matches torch CUDA version
        if [[ -x "${venv_python}" ]]; then
            local torch_cuda_ver
            torch_cuda_ver="$("${venv_python}" -c "import torch; print(torch.version.cuda or '')" 2>/dev/null || echo "")"

            if [[ -n "${torch_cuda_ver}" && -n "${nvcc_ver}" ]]; then
                local nvcc_major torch_major
                nvcc_major="${nvcc_ver%%.*}"
                torch_major="${torch_cuda_ver%%.*}"
                if [[ "${nvcc_major}" != "${torch_major}" ]]; then
                    issues+=("nvcc ${nvcc_ver} does not match torch CUDA ${torch_cuda_ver}. Install: sudo apt install cuda-toolkit-${torch_major}-x")
                else
                    _cfg_info "nvcc ${nvcc_ver} matches torch CUDA ${torch_cuda_ver} ✔"
                fi
            fi
        fi
    fi

    # ── Step 3: Validate CUDA_HOME ─────────────────────────────────────────
    if [[ -z "${CUDA_HOME:-}" ]]; then
        # Try to derive it
        if [[ -n "${nvcc_path}" ]]; then
            CUDA_HOME="$(dirname "$(dirname "${nvcc_path}")")"
        elif [[ -d "/usr/local/cuda" ]]; then
            CUDA_HOME="/usr/local/cuda"
        fi
    fi

    if [[ -z "${CUDA_HOME:-}" || ! -f "${CUDA_HOME}/bin/nvcc" ]]; then
        issues+=("CUDA_HOME not set or invalid. Add to ~/.profile: export CUDA_HOME=/usr/local/cuda")
    else
        export CUDA_HOME
        export PATH="${CUDA_HOME}/bin:${PATH}"
        export LD_LIBRARY_PATH="${CUDA_HOME}/lib64:${LD_LIBRARY_PATH:-}"
        _cfg_info "CUDA_HOME: ${CUDA_HOME}"
    fi

    # ── Report ─────────────────────────────────────────────────────────────
    if [[ "${#issues[@]}" -gt 0 ]]; then
        echo ""
        _cfg_error "Build environment not ready — ${#issues[@]} issue(s):"
        for issue in "${issues[@]}"; do
            echo "  ✘ ${issue}"
        done
        echo ""
        echo "  Fix the above then re-run this installer."
        echo ""
        return 1
    fi

    _cfg_info "Build environment ready: CC=${CC} CXX=${CXX} CUDA_HOME=${CUDA_HOME}"
    return 0
}

_cfg_info "Ready: ${AI_APPS} | ${TORCH_CUDA} | driver ${PROBE_DRIVER_VERSION} | port ${AI_PORT}"
