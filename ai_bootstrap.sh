#!/usr/bin/env bash
# =============================================================================
# ai_bootstrap.sh — One-file setup for AI_Tools
# =============================================================================
# Downloads and installs the AI_Tools repo on a new machine.
#
# Usage (from anywhere):
#   curl -fsSL https://raw.githubusercontent.com/TrickBit/AI_TOOLS/main/ai_bootstrap.sh \
#       -o ai_bootstrap.sh
#   bash ai_bootstrap.sh
#
# What it does:
#   1. Checks required dependencies
#   2. Asks where to clone the repo (default: ~/bin/scripts/AI_Tools)
#   3. Clones from GitHub
#   4. Finds the right place on PATH for the symlink
#   5. Creates: ai_tools → ai_tools.sh
#   6. Optionally sets a default target drive
#   7. Tells you you're ready to go
#
# Idempotent — safe to re-run. Re-run after a manual git clone to just
# do the symlink and config steps.
#
# ai_update_cont.sh (in the repo) keeps claude_continue.md pointing at
# the latest session doc. Only needed if working with Claude on this project.
# =============================================================================

set -uo pipefail

REPO_URL="https://github.com/TrickBit/AI_TOOLS.git"
DEFAULT_CLONE_DIR="${HOME}/bin/scripts/AI_Tools"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
RESET='\033[0m'

info()  { echo -e "  ${GREEN}✔${RESET}  $*"; }
warn()  { echo -e "  ${YELLOW}!${RESET}  $*"; }
err()   { echo -e "  ${RED}✘${RESET}  $*" >&2; }
die()   { err "$*"; exit 1; }
hdr()   { echo -e "\n${BOLD}${CYAN}$*${RESET}"; }
blank() { echo; }

# Prompt with a default value shown in brackets.
# Usage: ask "Question" "default" varname
ask() {
    local prompt="$1" default="$2" varname="$3"
    read -r -p "  ${prompt} [${default}]: " _input
    printf -v "${varname}" '%s' "${_input:-$default}"
}

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------

blank
echo -e "${BOLD}AI_Tools — bootstrap setup${RESET}"
echo    "  ${REPO_URL}"
blank

# ---------------------------------------------------------------------------
# 1. Dependency checks
# ---------------------------------------------------------------------------

hdr "Checking dependencies"

MISSING=()


check_cmd() {
    local cmd="$1" label="${2:-$1}"
    if command -v "${cmd}" &>/dev/null; then
        info "${label}"
    elif [[ -x "${HOME}/.pyenv/bin/${cmd}" ]]; then
        info "${label}  (found at ~/.pyenv/bin/${cmd}, not on PATH)"
    else
        warn "${label}  ← not found"
        MISSING+=("${label}")
    fi
}

check_cmd git          "git"
check_cmd python3      "python3"
check_cmd pyenv        "pyenv"
check_cmd nvidia-smi   "nvidia-smi (NVIDIA driver)"

# git is the only hard requirement for bootstrap itself
if ! command -v git &>/dev/null; then
    die "git is required to clone the repo. Install it and re-run."
fi

if [[ ${#MISSING[@]} -gt 0 ]]; then
    blank
    warn "Missing: ${MISSING[*]}"
    warn "AI_Tools needs these before it can install any AI apps."
    warn "You can finish setup now and install them later."
    blank
    read -r -p "  Continue anyway? [y/N] " _cont
    [[ "${_cont,,}" == "y" ]] || { echo "  Aborted."; exit 0; }
fi

# ---------------------------------------------------------------------------
# 2. Where to put the repo
# ---------------------------------------------------------------------------

hdr "Repo location"

echo    "  Where should AI_Tools be cloned?"
echo    "  This becomes your working directory for all AI stack scripts."
blank
ask "Clone to" "${DEFAULT_CLONE_DIR}" CLONE_DIR

# Expand ~ manually in case user typed it
CLONE_DIR="${CLONE_DIR/#\~/$HOME}"

# ---------------------------------------------------------------------------
# 3. Clone or update
# ---------------------------------------------------------------------------

hdr "Getting the repo"

if [[ -d "${CLONE_DIR}/.git" ]]; then
    info "Repo already exists at ${CLONE_DIR}"
    info "Skipping clone — using existing repo as-is"
    info "(Run 'git pull' inside it to update)"
elif [[ -d "${CLONE_DIR}" && -n "$(ls -A "${CLONE_DIR}" 2>/dev/null)" ]]; then
    die "${CLONE_DIR} exists and is not empty. Remove it or choose a different path."
else
    parent_dir="$(dirname "${CLONE_DIR}")"
    if [[ ! -d "${parent_dir}" ]]; then
        mkdir -p "${parent_dir}" || die "Could not create ${parent_dir}"
        info "Created ${parent_dir}"
    fi
    echo    "  Cloning..."
    git clone "${REPO_URL}" "${CLONE_DIR}" || die "git clone failed"
    info "Cloned to ${CLONE_DIR}"
fi

AI_TOOLS_SH="${CLONE_DIR}/ai_tools.sh"
[[ -f "${AI_TOOLS_SH}" ]] || die "ai_tools.sh not found in ${CLONE_DIR} — clone may be incomplete"
chmod +x "${AI_TOOLS_SH}"

# ---------------------------------------------------------------------------
# 4. Find the right place on PATH for the symlink
# ---------------------------------------------------------------------------

hdr "Finding symlink location"

# Build a list of candidate bin dirs from PATH, in preference order.
# We prefer dirs under HOME over system dirs — user install, not system.
# We want something that:
#   a) is already on PATH, AND
#   b) is writable by this user, AND
#   c) is not inside the repo itself (that would be circular)
#
# We also accept a dir that doesn't exist yet if it's a well-known
# location that PATH commonly includes on login shells.

mapfile -t PATH_DIRS < <(echo "${PATH}" | tr ':' '\n')

LINK_DIR=""

# Pass 1: existing writable dirs on PATH (prefer ones under HOME)
for dir in "${PATH_DIRS[@]}"; do
    [[ -z "${dir}" ]] && continue
    [[ "${dir}" == "${CLONE_DIR}" ]] && continue       # skip the repo itself
    [[ "${dir}" == "${CLONE_DIR}/"* ]] && continue     # skip subdirs of repo
    if [[ -d "${dir}" && -w "${dir}" && "${dir}" == "${HOME}"* ]]; then
        LINK_DIR="${dir}"
        info "Using ${dir}  (on PATH, writable)"
        break
    fi
done

# Pass 2: any writable dir on PATH (including system dirs, less preferred)
if [[ -z "${LINK_DIR}" ]]; then
    for dir in "${PATH_DIRS[@]}"; do
        [[ -z "${dir}" ]] && continue
        [[ "${dir}" == "${CLONE_DIR}" ]] && continue
        [[ "${dir}" == "${CLONE_DIR}/"* ]] && continue
        if [[ -d "${dir}" && -w "${dir}" ]]; then
            LINK_DIR="${dir}"
            info "Using ${dir}  (on PATH, writable)"
            break
        fi
    done
fi

# Pass 3: well-known locations that PATH usually auto-includes — create them
if [[ -z "${LINK_DIR}" ]]; then
    for dir in "${HOME}/bin/scripts" "${HOME}/bin" "${HOME}/.local/bin"; do
        if echo ":${PATH}:" | grep -q ":${dir}:"; then
            mkdir -p "${dir}"
            LINK_DIR="${dir}"
            info "Created ${dir}  (on PATH)"
            break
        fi
    done
fi

# Pass 4: fallback — create ~/bin and warn
if [[ -z "${LINK_DIR}" ]]; then
    LINK_DIR="${HOME}/bin"
    mkdir -p "${LINK_DIR}"
    warn "Created ${LINK_DIR} — it is not on your PATH yet."
    warn "Add this to ~/.bashrc then run: source ~/.bashrc"
    warn ""
    warn "    export PATH=\"\${HOME}/bin:\${PATH}\""
    warn ""
fi

# ---------------------------------------------------------------------------
# 5. Create the symlink
# ---------------------------------------------------------------------------

LINK_TARGET="${LINK_DIR}/ai_tools"

if [[ -L "${LINK_TARGET}" ]]; then
    existing="$(readlink -f "${LINK_TARGET}" 2>/dev/null || true)"
    if [[ "${existing}" == "${AI_TOOLS_SH}" ]]; then
        info "Symlink already correct: ${LINK_TARGET}"
    else
        ln -sf "${AI_TOOLS_SH}" "${LINK_TARGET}"
        info "Updated symlink: ${LINK_TARGET}"
        info "  → ${AI_TOOLS_SH}"
    fi
elif [[ -e "${LINK_TARGET}" ]]; then
    die "${LINK_TARGET} exists and is not a symlink — remove it manually first"
else
    ln -s "${AI_TOOLS_SH}" "${LINK_TARGET}"
    info "Created symlink: ${LINK_TARGET}"
    info "  → ${AI_TOOLS_SH}"
fi

# ---------------------------------------------------------------------------
# 6. Optional: target drive
# ---------------------------------------------------------------------------

hdr "Target drive (optional)"

echo    "  The target drive is where AI apps will be installed."
echo    "  You can set this now or let ai_tools ask you on first run."
blank

# List mounted ext4 / btrfs drives under /mnt with some used space
# (avoids listing freshly formatted empty drives as suggestions)
mapfile -t DRIVES < <(
    df -h --output=target,fstype,avail,used 2>/dev/null \
    | awk 'NR>1 && ($2=="ext4" || $2=="btrfs") && $1 ~ "^/mnt/" {
        print $1 "  (" $4 " used, " $3 " free)"
    }'
)

if [[ ${#DRIVES[@]} -gt 0 ]]; then
    echo "  Drives found under /mnt/:"
    for d in "${DRIVES[@]}"; do
        echo "      ${d}"
    done
    blank
fi

read -r -p "  Enter target drive path (or Enter to skip): " TARGET_DRIVE

if [[ -n "${TARGET_DRIVE}" ]]; then
    TARGET_DRIVE="${TARGET_DRIVE/#\~/$HOME}"
    if [[ -d "${TARGET_DRIVE}" ]]; then
        JSON_FILE="${CLONE_DIR}/ai_installer.json"
        if [[ -f "${JSON_FILE}" ]]; then
            python3 "${CLONE_DIR}/pylib/ai_config.py" set config active_target "${TARGET_DRIVE}" 2>/dev/null \
                && info "Target drive saved: ${TARGET_DRIVE}" \
                || warn "Could not write to ai_installer.json — ai_tools will ask on first run"
        else
            # No JSON yet — first run will create it and ask for target.
            # We can't pre-set it, but we can note it for the user.
            info "No ai_installer.json yet — ai_tools will ask for the target on first run"
            info "You entered: ${TARGET_DRIVE}  (remember this)"
        fi
    else
        warn "${TARGET_DRIVE} is not a directory — skipped. Set it when ai_tools asks."
    fi
else
    info "Skipped — ai_tools will ask on first run"
fi

# ---------------------------------------------------------------------------
# 7. Done
# ---------------------------------------------------------------------------

blank
echo -e "${BOLD}${GREEN}Setup complete.${RESET}"
blank
echo -e "  Run:  ${BOLD}ai_tools${RESET}"
blank
echo    "  On first run, ai_tools will:"
echo    "    • Probe your GPU, driver, and CUDA version"
echo    "    • Ask which drive to install apps on (if not set above)"
echo    "    • Show you what's available to install"
blank
echo -e "  ${CYAN}Repo location:${RESET}  ${CLONE_DIR}"
echo -e "  ${CYAN}Symlink:${RESET}        ${LINK_TARGET}"
blank

