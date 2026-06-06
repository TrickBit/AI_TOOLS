#!/usr/bin/env bash
# =============================================================================
# ai_model_manager.sh
# Launcher for ai_model_manager.py
# Manages venv at ai_resourcelib/.venv alongside this script.
#
# Usage:
#   ai_model_manager.sh                          # show help and exit
#   ai_model_manager.sh --consolidate --all      # consolidate all known apps
#   ai_model_manager.sh --consolidate --src <p>  # consolidate one path
#   ai_model_manager.sh --consolidate --all --dry-run
#   ai_model_manager.sh --restore --app <name>
#   ai_model_manager.sh --restore --all
#   ai_model_manager.sh --status
#   ai_model_manager.sh --status --app <name>
# =============================================================================

set -o errexit
set -o pipefail
set -o nounset
# set -o xtrace   # uncomment for debug tracing

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
NC='\033[0m';     CYAN='\033[36m';    WHITE='\033[37m'

TEXT="${WHITE}"
ERROR="${RED}ERROR:${TEXT} "
INFO="${YELLOW}INFO:${TEXT} "
GOOD="${GREEN}GOOD:${TEXT} "

show_info()  { echo -e "${INFO}$*${NC}"  >&2; }
show_good()  { echo -e "${GOOD}$*${NC}"  >&2; }
show_error() { echo -e "${ERROR}$*${NC}" >&2; }

die() {
    show_error "$*"
    exit 1
}

# ---------------------------------------------------------------------------
# Package installation with caching
# ---------------------------------------------------------------------------
install_packages() {
    local required_packages=("$@")
    local missing_packages=()
    local installed_packages=()
    local INSTALL_CACHE_FILE="$ORGANIZER_VENV/requirements_installed.txt"

    declare -A PKG_IMPORT_MAP=(
        ["PyYAML"]="yaml"
        ["Pillow"]="PIL"
        ["charset_normalizer"]="charset_normalizer"
    )

    if [ -f "$INSTALL_CACHE_FILE" ]; then
        mapfile -t installed_packages < "$INSTALL_CACHE_FILE"
    fi

    for pkg in "${required_packages[@]}"; do
        if [[ ! " ${installed_packages[*]} " =~ " $pkg " ]]; then
            import_name="${PKG_IMPORT_MAP[$pkg]:-$pkg}"
            if ! "$PYTHON_BIN" -c "import $import_name" >/dev/null 2>&1; then
                missing_packages+=("$pkg")
            else
                installed_packages+=("$pkg")
            fi
        fi
    done

    if [ ${#missing_packages[@]} -gt 0 ]; then
        show_info "Installing missing packages: ${missing_packages[*]}"
        "$PIP_BIN" install --quiet --upgrade "${missing_packages[@]}"
        installed_packages+=("${missing_packages[@]}")
        printf "%s\n" "${installed_packages[@]}" > "$INSTALL_CACHE_FILE"
    else
        show_good "All required packages already installed."
        if [ ! -f "$INSTALL_CACHE_FILE" ]; then
            printf "%s\n" "${installed_packages[@]}" > "$INSTALL_CACHE_FILE"
        fi
    fi
}

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_BASENAME="ai_model_manager.py"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORGANIZER_VENV="$SCRIPT_DIR/.venv_models"
PYTHON_BIN="$ORGANIZER_VENV/bin/python"
PIP_BIN="$ORGANIZER_VENV/bin/pip"
SCRIPT_PATH="$SCRIPT_DIR/$SCRIPT_BASENAME"

if [ ! -f "$SCRIPT_PATH" ]; then
    die "Python script '$SCRIPT_BASENAME' not found in $SCRIPT_DIR"
fi

# ---------------------------------------------------------------------------
# Deactivate any active venv quietly
# ---------------------------------------------------------------------------
if type deactivate >/dev/null 2>&1; then
    deactivate || true
fi

# ---------------------------------------------------------------------------
# Create venv if needed
# ---------------------------------------------------------------------------
if [ ! -x "$PYTHON_BIN" ]; then
    show_info "Creating virtual environment at $ORGANIZER_VENV ..."
    python3 -m venv "$ORGANIZER_VENV" \
        || die "Failed to create virtual environment at $ORGANIZER_VENV"
    show_info "Upgrading pip, setuptools, wheel ..."
    "$PYTHON_BIN" -m pip install --upgrade pip setuptools wheel >/dev/null
fi

# ---------------------------------------------------------------------------
# Required packages
# ---------------------------------------------------------------------------
required_packages=(
    "safetensors"
    "torch"
    "filetype"
    "rarfile"
    "charset_normalizer"
    "numpy"
    "tqdm"
    "PyYAML"
    "onnx"
)
install_packages "${required_packages[@]}"

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
show_info "Running $SCRIPT_BASENAME $*"
# "$PYTHON_BIN" "$SCRIPT_PATH" "$@"
PYTHONPATH="$SCRIPT_DIR/pylib" "$PYTHON_BIN" "$SCRIPT_PATH" "$@"
