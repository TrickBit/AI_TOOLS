#!/usr/bin/env bash
# =============================================================================
# ai_comfyui_postinstall.sh  —  SUPERSEDED — see ai_comfyui_postinstall.py
# =============================================================================
#
# This script has been replaced by ai_comfyui_postinstall.py + comfyui_workflows.ini
#
# WHY:
#   The original bash version had hardcoded node lists, a hardcoded
#   extra_model_paths.yaml, and no ability to download models, track state,
#   or handle multiple workflow packs. Every new workflow required editing
#   the script itself.
#
# WHAT REPLACED IT:
#   comfyui_workflows.ini   — human-editable workflow pack definitions.
#                             Add a :workflow block for each new pack.
#                             Contains node URLs, model URLs + destinations,
#                             workflow JSON URLs, and yaml key mappings.
#                             Lives in: AI_Tools/
#
#   ai_comfyui_postinstall.py — reads the ini, presents an interactive picker,
#                             downloads missing models into the shared tree,
#                             hardlinks models into ComfyUI's own dirs,
#                             clones/pulls custom nodes, writes yaml,
#                             symlinks workflow JSONs, and records everything
#                             in ai_installer.json for repeatability.
#                             Lives in: AI_Tools/
#
# HOW TO RUN:
#   ai_tools comfyui setup                    — interactive picker
#   ai_tools comfyui reinstall <workflow-id>  — reinstall from JSON record
#                                               (ini not required)
#
# STATE:
#   All installed workflow state is recorded in ai_installer.json under
#   the "comfyui_workflows" key — what was required, what was downloaded,
#   where everything lives, when it was done. A lost ini file does not
#   prevent reinstall.
#
# =============================================================================

echo "This script has been superseded by ai_comfyui_postinstall.py"
echo ""
echo "  Interactive setup:  ai_tools comfyui setup"
echo "  Reinstall:          ai_tools comfyui reinstall <workflow-id>"
echo "  Workflow config:    AI_Tools/comfyui_workflows.ini"
echo ""
exit 0
