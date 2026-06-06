#!/usr/bin/env bash
# =============================================================================
# ai_installer.sh  —  runner for ai_installer.py
# =============================================================================
# Hardlink this file into ~/bin/ (or anywhere on PATH).
# The AI_Tools directory is hardcoded here — hardlinks share an inode so
# there is no "original path" to resolve back to at runtime.
#
# Hardlink setup (one-time):
#   ln ~/bin/scripts/AI_Tools/ai_installer.sh ~/bin/ai_installer
# =============================================================================

AI_TOOLS_DIR="${HOME}/bin/scripts/AI_Tools"
PYTHON="${PYTHON:-python3}"
INSTALLER="${AI_TOOLS_DIR}/ai_installer.py"

if [[ ! -f "${INSTALLER}" ]]; then
    echo "ERROR: ai_installer.py not found at ${INSTALLER}" >&2
    exit 1
fi

export AI_INSTALLER_JSON="${AI_TOOLS_DIR}/ai_installer.json"
export AI_TOOLS_DIR

exec "${PYTHON}" "${INSTALLER}" "$@"
