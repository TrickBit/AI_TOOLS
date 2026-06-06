#!/usr/bin/env bash
# =============================================================================
# ai_tools  —  Single entry point for the Jethro AI stack
# =============================================================================
# This is the ONLY directly executable file in AI_Tools/.
# All other scripts are chmod 644 and are sourced or dispatched from here.
#
# Symlink this file into ~/bin/ as 'ai_tools' (no extension):
#   ln -s /path/to/AI_Tools/ai_tools ~/bin/ai_tools
#
# AI_TOOLS_ROOT is resolved from this file's true location, so the symlink
# can live anywhere — the tree is always found correctly.
#
# Usage:
#   ai_tools                              — help + interactive prompt
#   ai_tools install <app> [--rebuild]   — install or rebuild an app
#   ai_tools run <app>                   — launch an app (detached)
#   ai_tools update <app>                — git pin + deps, no launch
#   ai_tools status                      — show all app states
#   ai_tools probe                       — system probe summary
#   ai_tools wheels collect [<app>|--all]
#   ai_tools wheels consolidate [<drive>]
#   ai_tools mirrors update
#   ai_tools mirrors consolidate [<drive>]
# =============================================================================

set -euo pipefail

# =============================================================================
# Resolve true root — works through symlinks
# =============================================================================
AI_TOOLS_ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
export AI_TOOLS_ROOT

# =============================================================================
# Source shared config (paths, probe, helpers)
# =============================================================================
source "${AI_TOOLS_ROOT}/ai_config.sh"

# =============================================================================
# Constants
# =============================================================================
_APPS="automatic wan2gp framepack invokeai comfyui"
_VERSION="2.0"
_LOG_DIR="${AI_TOOLS_ROOT}/logs"

# =============================================================================
# _help()
# Print concise usage to stdout.
# =============================================================================
_help() {
    cat << EOF

AI Tools ${_VERSION}  —  Jethro AI stack manager

Usage:
  ai_tools install <app> [--rebuild]    install or rebuild an app
  ai_tools run <app>                    launch an app (detached)
  ai_tools update <app>                 git pin + deps, no launch
  ai_tools status                       show all app states
  ai_tools target                       show active target
  ai_tools target <drive>               set active target
  ai_tools probe                        system probe summary
  ai_tools wheels organise          sort localbuild/ into ABI subdirs
  ai_tools wheels collect [<app>|--all]
  ai_tools wheels consolidate [<drive>]
  ai_tools wheels collect [<app>|--all] cache wheels from venv(s)
  ai_tools wheels consolidate [<drive>] merge wheel caches to one drive
  ai_tools mirrors update               refresh git mirror bare repos
  ai_tools mirrors consolidate [<drive>] merge mirrors to one drive
  ai_tools models [args]                run model manager
  ai_tools comfyui setup               install ComfyUI workflow packs
  ai_tools comfyui reinstall <id>      reinstall a workflow pack from record
  ai_tools comfyui status              show installed workflow state
  ai_tools --list-targets              list available target drives

Apps: ${_APPS}

EOF
}

# =============================================================================
# _no_args()
# Called when ai_tools is run with no arguments.
# Prints help, offers CLI or interactive menu — single keypress, no Enter.
# =============================================================================
_no_args() {
    _help
    echo "  run:  ai_tools menu    for the interactive menu"
    echo
}
old_no_args() {
    _help
    printf 'Drop to a CLI prompt or open the interactive menu? [1=cli  2=menu]  '
    local key
    IFS= read -r -s -n1 key
    echo   # newline after keypress

    if [[ "${key}" == "2" ]]; then
        echo
        _menu
    else
        # key=1 or anything else — reprint help and return to shell prompt
        _help
    fi
}

# =============================================================================
# _menu()
# Launch the interactive Python menu.
# =============================================================================
_menu() {
    python3 "${AI_TOOLS_ROOT}/ai_installer.py"
}

# =============================================================================
# _require_app <app>
# Validate app name. Exits with usage if not recognised.
# =============================================================================
_require_app() {
    local app="$1"
    for a in ${_APPS}; do
        [[ "${a}" == "${app}" ]] && return 0
    done
    echo "  Unknown app: ${app}"
    echo "  Apps: ${_APPS}"
    echo
    exit 1
}

# =============================================================================
# _installer_script <app>
# Return path to the installer script for an app.
# =============================================================================
_installer_script() {
    local app="$1"
    # framepack maps to ai_frampackstudio_install.sh (legacy name kept)
    case "${app}" in
        framepack) echo "${AI_TOOLS_ROOT}/installers/ai_frampackstudio_install.sh" ;;
        *)         echo "${AI_TOOLS_ROOT}/installers/ai_${app}_install.sh" ;;
    esac
}

# =============================================================================
# _runner_script <app>
# Return path to the runner script for an app.
# =============================================================================
_runner_script() {
    local app="$1"
    case "${app}" in
        framepack) echo "${AI_TOOLS_ROOT}/runners/ai_frampackstudio" ;;
        comfyui)   echo "${AI_TOOLS_ROOT}/runners/ai_comfy" ;;
        *)         echo "${AI_TOOLS_ROOT}/runners/ai_${app}" ;;
    esac
}

# =============================================================================
# cmd_install <app> [--rebuild]
# Run the installer for an app.
# =============================================================================
cmd_install() {
    local app="$1"; shift
    local flag="${1:-}"
    _require_app "${app}"
    local script
    script="$(_installer_script "${app}")"
    [[ ! -f "${script}" ]] && { echo "  Installer not found: ${script}"; exit 1; }
    bash "${script}" ${flag:+"${flag}"}
}

# =============================================================================
# cmd_run <app>
# Launch an app detached from the terminal.
# Prints log path on launch and again when the process exits.
# =============================================================================
cmd_run() {
    local app="$1"
    _require_app "${app}"
    local script
    script="$(_runner_script "${app}")"
    [[ ! -f "${script}" ]] && { echo "  Runner not found: ${script}"; exit 1; }

    local log="${_LOG_DIR}/ai_${app}.lastrun.log"
    echo "Launching ${app}..."
    echo "  log: ${log}"
    echo

    bash "${script}" &
    local pid=$!
    wait "${pid}" || true
    echo
    echo "${app} exited (pid ${pid}) — see the log: ${log}"
}

# =============================================================================
# cmd_update <app>
# Run installer in --update mode (git pin + deps, no launch).
# =============================================================================
cmd_update() {
    local app="$1"
    _require_app "${app}"
    local script
    script="$(_installer_script "${app}")"
    [[ ! -f "${script}" ]] && { echo "  Installer not found: ${script}"; exit 1; }
    bash "${script}" --update
}

# =============================================================================
# cmd_status
# Show install status for all apps via ai_installer.py.
# =============================================================================
cmd_status() {
    python3 "${AI_TOOLS_ROOT}/ai_installer.py" status
}

# =============================================================================
# cmd_probe
# Run system probe and print summary.
# =============================================================================
cmd_probe() {
    python3 "${AI_TOOLS_ROOT}/ai_installer.py" probe
}

# =============================================================================
# cmd_wheels <subcommand> [args...]
# Wheel cache operations.
# =============================================================================
cmd_wheels() {
    local sub="${1:-}"; shift || true
    case "${sub}" in
        collect)
            local target="${1:---all}"
            if [[ "${target}" == "--all" ]]; then
                python3 "${AI_TOOLS_ROOT}/pylib/ai_collect_wheels.py" --auto
            else
                _require_app "${target}"
                case "${target}" in
                    automatic)  _disk="stable-diffusion-webui"; _venv="venv" ;;
                    wan2gp)     _disk="Wan2GP";                 _venv="venv" ;;
                    framepack)  _disk="FramePack-Studio";       _venv="venv" ;;
                    invokeai)   _disk="invokeai";               _venv=".venv" ;;
                    comfyui)    _disk="ComfyUI";                _venv="venv" ;;
                esac
                _venv_path="${AI_APPS}/${_disk}/${_venv}"
                [[ ! -d "${_venv_path}" ]] && { echo "  Venv not found: ${_venv_path}"; exit 1; }
                python3 "${AI_TOOLS_ROOT}/pylib/ai_collect_wheels.py" --venv "${_venv_path}" --auto
            fi
            ;;
        organise)
            bash "${AI_TOOLS_ROOT}/ai_wheels_organise.sh" "${@}"
            ;;
        consolidate)
            local drive="${1:-}"
            echo "  wheels consolidate: not yet implemented"
            [[ -n "${drive}" ]] && echo "  Target drive: ${drive}"
            ;;
        *)
            echo "  Usage: ai_tools wheels collect [<app>|--all]"
            echo "         ai_tools wheels consolidate [<drive>]"
            exit 1
            ;;
    esac
}

# =============================================================================
# cmd_mirrors <subcommand> [args...]
# Git mirror operations.
# =============================================================================
cmd_mirrors() {
    local sub="${1:-}"; shift || true
    case "${sub}" in
        update)
            echo "  mirrors update: not yet implemented"
            ;;
        consolidate)
            local drive="${1:-}"
            echo "  mirrors consolidate: not yet implemented"
            [[ -n "${drive}" ]] && echo "  Target drive: ${drive}"
            ;;
        *)
            echo "  Usage: ai_tools mirrors update"
            echo "         ai_tools mirrors consolidate [<drive>]"
            exit 1
            ;;
    esac
}


# =============================================================================
# cmd_target [mount]
# Show or set the active target drive.
# No args: print current target.
# With arg: validate mount is present and hardlink-capable, then set it.
# =============================================================================
cmd_target() {
    python3 "${AI_TOOLS_ROOT}/ai_installer.py" target "$@"
}

# =============================================================================
# cmd_models [args...]
# Run ai_model_manager.py with any args passed through.
# =============================================================================
cmd_models() {
    python3 "${AI_TOOLS_ROOT}/ai_model_manager.py" "$@"
}

# =============================================================================
# cmd_comfyui <subcommand> [args...]
# ComfyUI workflow pack setup — dispatches to ai_comfyui_postinstall.py.
# Subcommands: setup, reinstall <id>, status
# =============================================================================
cmd_comfyui() {
    python3 "${AI_TOOLS_ROOT}/ai_installer.py" comfyui "$@"
}

# =============================================================================
# cmd_list_targets
# List all hardlink-capable mounted drives (candidate targets).
# =============================================================================
cmd_list_targets() {
    python3 "${AI_TOOLS_ROOT}/ai_installer.py" probe 2>/dev/null \
        | grep -A99 "Drives (hardlink" \
        | tail -n +2
}


# =============================================================================
# Dispatch
# =============================================================================
if [[ $# -eq 0 ]]; then
    _no_args
    exit 0
fi

cmd="$1"; shift
case "${cmd}" in
    install)    cmd_install "$@" ;;
    run)        cmd_run "$@" ;;
    update)     cmd_update "$@" ;;
    status)     cmd_status ;;
    target)     cmd_target "$@" ;;
    probe)      cmd_probe ;;
    wheels)     cmd_wheels "$@" ;;
    mirrors)    cmd_mirrors "$@" ;;
    models)     cmd_models "$@" ;;
    menu)       _menu ;;
    help|--help|-h) _help ;;
    comfyui)    cmd_comfyui "$@" ;;
    --list-targets) cmd_list_targets ;;
    *)
        echo "  Unknown command: ${cmd}"
        _help
        exit 1
        ;;
esac
