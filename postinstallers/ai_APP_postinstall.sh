#!/usr/bin/env bash
# =============================================================================
# ai_APP_postinstall.sh  —  Post-install for APP
# =============================================================================
# DESCRIPTION: One line shown in the conductor menu — keep it concise
# =============================================================================
# This script runs after the main installer completes.
# Use it for opinionated setup: custom workflows, extra nodes/plugins,
# model downloads, config files, symlinks — anything specific to YOUR
# use of this app that the vanilla installer doesn't do.
#
# The conductor:
#   - Reads DESCRIPTION (line above) and shows it in the menu
#   - Offers to run this script after install/rebuild (not after plain update)
#   - Records the run date in ai_conductor.json
#   - Won't offer again unless --force is passed to the conductor
#   - Always lists it in the Post-install menu section if this file exists
#
# Usage (normally called by conductor, but safe to run standalone):
#   ./ai_APP_postinstall.sh
#   ./ai_APP_postinstall.sh --force    # re-run even if already done
#
# Naming convention: ai_<appname>_postinstall.sh
#   ai_a1111_postinstall.sh
#   ai_wan2gp_postinstall.sh
#   ai_frampackstudio_postinstall.sh
#   ai_invokeai_postinstall.sh
#   ai_comfyui_postinstall.sh
# =============================================================================

set -euo pipefail

# =============================================================================
# Source shared config — gives you AI_APPS, AI_SHARED, AI_OUTPUTS,
# HF_HOME, TORCH_CUDA, AI_PORT, and all helper functions.
# =============================================================================
source "$(dirname "${BASH_SOURCE[0]}")/ai_config.sh"

# =============================================================================
# App-specific paths — adjust for the app this post-installer targets
# =============================================================================
APP_DIR="${AI_APPS}/APP_NAME"          # e.g. ${AI_APPS}/invokeai
VENV_DIR="${APP_DIR}/.venv"            # or /venv depending on the app
VENV_PIP="${VENV_DIR}/bin/pip"
VENV_PYTHON="${VENV_DIR}/bin/python"

# =============================================================================
# Helpers
# =============================================================================
step() { echo; echo "==> $*"; }
warn() { echo "  WARN: $*"; }
good() { echo -e "\033[32m  ✔\033[0m $*"; }

# =============================================================================
# Preflight
# =============================================================================
step "Preflight"
[[ ! -d "${APP_DIR}" ]] && {
    echo "ERROR: App not found at ${APP_DIR}"
    echo "  Run the main installer first: ai_APP_install.sh"
    exit 1
}
[[ ! -f "${VENV_PYTHON}" ]] && {
    echo "ERROR: venv not found at ${VENV_DIR}"
    echo "  Run the main installer first: ai_APP_install.sh"
    exit 1
}
good "App found: ${APP_DIR}"

# Activate the app's venv so pip installs go to the right place
source "${VENV_DIR}/bin/activate"

# =============================================================================
# Your post-install steps go here
# =============================================================================

# --- Example: install extra pip packages into the app venv ---
# step "Installing extra packages"
# pip install some-package another-package

# --- Example: download a model file ---
# step "Downloading custom model"
# mkdir -p "${AI_SHARED}/image/Checkpoints/custom"
# wget -c -P "${AI_SHARED}/image/Checkpoints/custom" \
#     "https://huggingface.co/some/model/resolve/main/model.safetensors"

# --- Example: copy a workflow file into the app ---
# step "Installing custom workflows"
# cp -r "${AI_WORK}/my_workflows/." "${APP_DIR}/workflows/"

# --- Example: write a config file ---
# step "Writing custom config"
# cat > "${APP_DIR}/custom_config.yaml" << YAML
# setting: value
# YAML

# --- Example: create a symlink ---
# step "Symlinking extra model dir"
# ln -sfn "${AI_SHARED}/image/Checkpoints/custom" "${APP_DIR}/models/custom"

# =============================================================================
# Done
# =============================================================================
echo
echo "============================================================"
echo "  Post-install complete"
echo "  App : ${APP_DIR}"
echo "============================================================"
