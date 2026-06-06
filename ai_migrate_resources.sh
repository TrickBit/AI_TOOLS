#!/usr/bin/env bash
# =============================================================================
# ai_migrate_resources.sh  —  Shared resource tree manager for Jethro AI stack
# =============================================================================
#
# Manages the canonical directory structure and symlinks for all AI apps.
# Safe to re-run at any time. Apps not yet installed are silently skipped.
#
# PRIME DIRECTIVE: An app is either fully migrated and working, or completely
# untouched. There is no in-between state.
#
# DIRECTORY STRUCTURE MANAGED:
#
#   /mnt/BACKUP_4.0_TB/
#   ├── AI-Shared-Resources/        ← models, weights, caches (inputs)
#   │   ├── huggingface/
#   │   ├── image/
#   │   │   ├── Checkpoints/sd-1, sd-2, sdxl/
#   │   │   ├── ControlNet/
#   │   │   ├── Embeddings/
#   │   │   │   ├── A1111/
#   │   │   │   └── Invoke/
#   │   │   ├── GFPGAN/
#   │   │   ├── Invokeai-Models/
#   │   │   ├── Lora/
#   │   │   ├── Upscalers/
#   │   │   └── VAE/
#   │   └── video/
#   │       ├── Lora/
#   │       ├── Models/
#   │       ├── TextEncoders/
#   │       ├── Upscalers/
#   │       └── VAE/
#   │
#   ├── AI_Outputs/                 ← everything apps produce
#   │   ├── A1111/
#   │   │   └── ALL_Outputs/
#   │   ├── ComfyUI/
#   │   │   ├── Image/
#   │   │   └── Video/
#   │   ├── FramePack/
#   │   │   ├── Image/
#   │   │   └── Video/
#   │   ├── Invoke/
#   │   │   └── ALL_Outputs/
#   │   └── Wan2GP/
#   │       ├── Image/
#   │       └── Video/
#   │
#   └── AI_Work/                    ← training data, projects (never touched)
#
# APP SYMLINKS:
#   A1111    : models/Stable-diffusion, VAE, Lora, embeddings,
#              ControlNet, ESRGAN, GFPGAN, outputs
#   InvokeAI : models, outputs
#   Wan2GP   : outputs
#   FramePack: outputs
#   ComfyUI  : output  (skipped until installed)
#
# LEGACY SOURCE TREES (hardlink-legacy modes):
#
#   /mnt/BACKUP_4.0_TB/AI_Resources-common/
#   ├── Stable-diffusion/   flat files routed by name:
#   │     v1-5-* / sd-v1-5-*  →  image/Checkpoints/sd-1/
#   │     v2-1_*               →  image/Checkpoints/sd-2/
#   │     *-sdxl-*             →  image/Checkpoints/sdxl/
#   ├── ControlNet/         →  image/ControlNet/     (flat copy)
#   └── Embeddings/         →  image/Embeddings/A1111/
#         (.bin .pt .safetensors only — skip .meta.json .txt .png .tsv dirs)
#
#   /mnt/BACKUP_4.0_TB/AI_downloaded/
#   ├── diffusion_models/   →  video/Models/
#   ├── loras/              →  video/Lora/
#   ├── text_encoders/      →  video/TextEncoders/
#   └── vae/                →  video/VAE/
#
#   Skipped in all legacy modes:
#     *.meta.json   *.txt   *.png   *.tsv   string_to_files_mapping/
#     AI_Resources-common/Loras/    (handled by ai_find_lora.sh on demand)
#     AI_Resources-common/Models/   (A1111 internal — managed by A1111 itself)
#     AI_Resources-common/Outputs/  (old outputs — handled by --migrate)
#
# USAGE:
#   ai_migrate_resources.sh                  # scan only — show what would happen
#   ai_migrate_resources.sh --migrate        # scan then act
#   ai_migrate_resources.sh --verify         # quick symlink health check only
#   ai_migrate_resources.sh --hardlink-legacy  # hardlink legacy trees into shared
#   ai_migrate_resources.sh --verify-legacy    # confirm every legacy file has same inode at dest
#   ai_migrate_resources.sh --prune-legacy     # delete legacy originals (only after verify-legacy passes 100%)
#
# Called automatically by each app installer. Safe to run standalone.
# This script must NOT be run as root.
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DRIVE="/mnt/BACKUP_4.0_TB"
SHARED="${DRIVE}/AI-Shared-Resources"
OUTPUTS="${DRIVE}/AI_Outputs"
AI_APPS="${DRIVE}/AI_Apps"

A1111_DIR="${AI_APPS}/stable-diffusion-webui"
INVOKE_DIR="${AI_APPS}/invokeai"
WAN2GP_DIR="${AI_APPS}/Wan2GP"
FPS_DIR="${AI_APPS}/FramePack-Studio"
COMFY_DIR="${AI_APPS}/ComfyUI"

# Legacy source trees — files here are hardlinked into SHARED, then optionally pruned
LEGACY_COMMON="${DRIVE}/AI_Resources-common"
LEGACY_DOWNLOADED="${DRIVE}/AI_downloaded"

# Sentinel file written by --verify-legacy when it passes 100%.
# --prune-legacy refuses to run unless this file exists and is fresh (same PID session).
LEGACY_VERIFY_SENTINEL="/tmp/ai_migrate_legacy_verify_ok_$(id -u)"

# Old output locations being relocated to AI_Outputs
OLD_A1111_OUTPUTS="${SHARED}/image/Outputs"
OLD_WAN2GP_OUTPUTS="${SHARED}/video/Outputs/Wan2GP"
OLD_FPS_OUTPUTS="${SHARED}/video/Outputs/FrameworkStudio"

# Lockfile
LOCKFILE="/tmp/ai_migrate_resources.lock"

# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GRN='\033[0;32m'
YLW='\033[1;33m'
CYN='\033[0;36m'
BLD='\033[1m'
RST='\033[0m'

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
hdr()     { echo; echo -e "${BLD}$*${RST}"; }
ok()      { echo -e "  ${GRN}✅${RST}  $*"; }
would()   { echo -e "  ${CYN}🔧${RST}  $*"; }
skip()    { echo -e "  ⏭   $*"; }
warn()    { echo -e "  ${YLW}⚠️ ${RST}  $*"; }
blocker() { echo -e "  ${RED}🚫${RST}  $*"; BLOCKERS+=("$*"); }
info()    { echo -e "       $*"; }
done_()   { echo -e "  ${GRN}✔${RST}   $*"; }
fail()    { echo -e "  ${RED}✖${RST}   $*"; FAILURES+=("$*"); }

# ---------------------------------------------------------------------------
# Mode
# ---------------------------------------------------------------------------
MODE="scan"
case "${1:-}" in
    --migrate)        MODE="migrate"        ;;
    --verify)         MODE="verify"         ;;
    --hardlink-legacy) MODE="hardlink-legacy" ;;
    --verify-legacy)  MODE="verify-legacy"  ;;
    --prune-legacy)   MODE="prune-legacy"   ;;
    "")               MODE="scan"           ;;
    *)
        echo "Usage: $(basename "$0") [--migrate | --verify | --hardlink-legacy | --verify-legacy | --prune-legacy]"
        echo "  (no args) = scan mode: show what would happen, make no changes"
        exit 1
        ;;
esac

# ---------------------------------------------------------------------------
# Tracking arrays
# ---------------------------------------------------------------------------
BLOCKERS=()
FAILURES=()
WOULD_CREATE=()
WOULD_MOVE=()
WOULD_SYMLINK=()
WOULD_SKIP=()
ALREADY_OK=()
CLEANUP_LIST=()   # entries: "source|dest|method"  used for rollback

# ---------------------------------------------------------------------------
# Pre-flight: must not run as root
# ---------------------------------------------------------------------------
if [[ "${EUID}" -eq 0 ]]; then
    echo
    echo -e "${RED}ERROR: This script must not be run as root.${RST}"
    echo "       Run as your normal user account."
    echo
    exit 1
fi

# ---------------------------------------------------------------------------
# Pre-flight: drive must be mounted
# ---------------------------------------------------------------------------
if [[ ! -d "${DRIVE}" ]]; then
    echo
    echo -e "${RED}ERROR: Drive not mounted: ${DRIVE}${RST}"
    echo
    exit 1
fi

# ---------------------------------------------------------------------------
# Lockfile — prevent concurrent runs
# ---------------------------------------------------------------------------
acquire_lock() {
    if [[ -f "${LOCKFILE}" ]]; then
        local existing_pid
        existing_pid="$(cat "${LOCKFILE}" 2>/dev/null || echo "")"
        if [[ -n "${existing_pid}" ]] && kill -0 "${existing_pid}" 2>/dev/null; then
            echo
            echo -e "${RED}ERROR: Another instance is running (PID ${existing_pid}).${RST}"
            echo "       If this is stale, remove: ${LOCKFILE}"
            echo
            exit 1
        fi
    fi
    echo $$ > "${LOCKFILE}"
}

release_lock() {
    rm -f "${LOCKFILE}"
}

trap release_lock EXIT

# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------

# Return filesystem type for a path
fs_type() {
    findmnt --noheadings --output FSTYPE --target "$1" 2>/dev/null || echo "unknown"
}

# Return device ID for a path
device_id() {
    stat --format="%d" "$1" 2>/dev/null || echo "0"
}

# Check filesystem supports hardlinks
fs_supports_hardlinks() {
    local fstype
    fstype="$(fs_type "$1")"
    case "${fstype}" in
        ext2|ext3|ext4|btrfs|xfs|zfs|jfs|reiserfs) return 0 ;;
        *) return 1 ;;
    esac
}

# Check if filesystem is network-based
fs_is_network() {
    local fstype
    fstype="$(fs_type "$1")"
    case "${fstype}" in
        nfs|nfs4|cifs|smb|smbfs|fuse.sshfs) return 0 ;;
        *) return 1 ;;
    esac
}

# Check if path is on a read-only mount
fs_is_readonly() {
    local opts
    opts="$(findmnt --noheadings --output OPTIONS --target "$1" 2>/dev/null || echo "")"
    [[ "${opts}" =~ (^|,)ro(,|$) ]]
}

# Free space in bytes at a path
free_space_bytes() {
    df --block-size=1 --output=avail "$1" 2>/dev/null | tail -1 | tr -d ' '
}

# Total size of a directory tree in bytes
dir_size_bytes() {
    du --bytes --summarize "$1" 2>/dev/null | awk '{print $1}'
}

# ---------------------------------------------------------------------------
# lsof check — bail if any files open under source trees we intend to move
# ---------------------------------------------------------------------------
check_open_files() {
    local dirs=("$@")
    local found=0

    hdr "Checking for open files..."

    for d in "${dirs[@]}"; do
        [[ ! -d "${d}" ]] && continue
        local open_files
        open_files="$(lsof +D "${d}" 2>/dev/null || true)"
        if [[ -n "${open_files}" ]]; then
            echo
            blocker "Open files detected in: ${d}"
            echo "${open_files}" | head -20
            found=1
        fi
    done

    if [[ "${found}" -eq 1 ]]; then
        echo
        echo -e "${RED}FATAL: Files are open in source trees we need to move.${RST}"
        echo "       Close all AI apps and re-run."
        echo
        exit 1
    fi

    ok "No open files detected"
}

# ---------------------------------------------------------------------------
# User prompt — only shown when changes are pending
# ---------------------------------------------------------------------------
prompt_user() {
    echo
    echo -e "${BLD}╔══════════════════════════════════════════════════════════════╗${RST}"
    echo -e "${BLD}║         AI RESOURCE MIGRATION — PLEASE READ CAREFULLY        ║${RST}"
    echo -e "${BLD}╚══════════════════════════════════════════════════════════════╝${RST}"
    echo
    echo "  This script is about to rearrange input resources and output"
    echo "  folders for your AI applications."
    echo
    echo "  The following apps will temporarily lose access to their"
    echo "  existing models, LoRAs, and output folders during migration:"
    echo
    for app in A1111 InvokeAI Wan2GP FramePack-Studio ComfyUI; do
        echo "    • ${app}"
    done
    echo
    echo -e "  ${YLW}Please ensure ALL of the above apps are currently CLOSED.${RST}"
    echo
    while true; do
        read -r -p "  Are they ALL closed and you wish to proceed? [y/N]: " choice
        choice="${choice:-n}"
        case "${choice,,}" in
            y|yes)
                echo
                return 0
                ;;
            n|no)
                echo
                echo "  Migration cancelled. No changes made."
                echo
                exit 0
                ;;
            *)
                echo "  Please enter Y or N."
                ;;
        esac
    done
}

# ---------------------------------------------------------------------------
# Move a directory's contents to a new location
# Same device: hardlink + verify + prune
# Cross device: rsync + verify + prune
# On any failure: full rollback for this app, original untouched
# ---------------------------------------------------------------------------
move_dir_contents() {
    local src="$1"
    local dst="$2"
    local app_name="$3"

    [[ ! -d "${src}" ]] && return 0

    # Count source files
    local src_count
    src_count="$(find "${src}" -type f | wc -l)"
    if [[ "${src_count}" -eq 0 ]]; then
        info "Source is empty, nothing to move: ${src}"
        return 0
    fi

    info "Moving ${src_count} file(s): ${src} → ${dst}"

    # Network filesystem check
    if fs_is_network "${src}" || fs_is_network "${dst}"; then
        fail "${app_name}: Network filesystem detected — refusing to move files over NFS/SMB"
        return 1
    fi

    # Read-only check
    if fs_is_readonly "${dst}"; then
        fail "${app_name}: Target filesystem is read-only: ${dst}"
        return 1
    fi

    # Writable check
    if [[ ! -w "${dst}" ]]; then
        fail "${app_name}: Target directory is not writable: ${dst}"
        return 1
    fi

    # Same device or cross device?
    local src_dev dst_dev
    src_dev="$(device_id "${src}")"
    dst_dev="$(device_id "${dst}")"

    local method
    if [[ "${src_dev}" == "${dst_dev}" ]]; then
        # Same device — check hardlink support
        if fs_supports_hardlinks "${dst}"; then
            method="hardlink"
        else
            method="rsync"
            warn "${app_name}: Filesystem doesn't support hardlinks, using rsync"
        fi
    else
        # Cross device — check space first
        method="rsync"
        local needed avail
        needed="$(dir_size_bytes "${src}")"
        avail="$(free_space_bytes "${dst}")"
        info "Space check: need ${needed} bytes, have ${avail} bytes free"
        if [[ "${needed}" -ge "${avail}" ]]; then
            fail "${app_name}: Insufficient space on target. Need ${needed}B, have ${avail}B free"
            return 1
        fi
    fi

    info "Method: ${method}"

    # Build list of files to process
    local app_cleanup=()
    local copy_ok=1

    if [[ "${method}" == "hardlink" ]]; then
        # Hardlink every file
        while IFS= read -r -d '' srcfile; do
            local relpath="${srcfile#${src}/}"
            local dstfile="${dst}/${relpath}"
            mkdir -p "$(dirname "${dstfile}")"
            if ln "${srcfile}" "${dstfile}" 2>/dev/null; then
                app_cleanup+=("${srcfile}|${dstfile}|hardlink")
            else
                warn "Hardlink failed for ${srcfile}, trying rsync fallback"
                if rsync -a "${srcfile}" "${dstfile}"; then
                    app_cleanup+=("${srcfile}|${dstfile}|rsync")
                else
                    fail "${app_name}: Failed to copy ${srcfile}"
                    copy_ok=0
                    break
                fi
            fi
        done < <(find "${src}" -type f -print0)

        # Handle symlinks within source
        while IFS= read -r -d '' srclink; do
            local relpath="${srclink#${src}/}"
            local dstlink="${dst}/${relpath}"
            local resolved
            resolved="$(readlink -f "${srclink}" 2>/dev/null || true)"
            if [[ -z "${resolved}" ]]; then
                warn "Could not resolve symlink: ${srclink} — skipping"
                continue
            fi
            mkdir -p "$(dirname "${dstlink}")"
            if [[ "$(device_id "$(dirname "${dstlink}")")" == "$(device_id "$(dirname "${resolved}")")" ]]; then
                # Same device — hardlink resolved target
                if ln "${resolved}" "${dstlink}" 2>/dev/null; then
                    app_cleanup+=("${srclink}|${dstlink}|hardlink_symlink")
                    # Ask about removing resolved original
                    echo
                    warn "Symlink resolved and hardlinked: ${srclink} → ${resolved}"
                    read -r -p "       Remove original resolved file ${resolved}? [y/N]: " rm_choice
                    rm_choice="${rm_choice:-n}"
                    [[ "${rm_choice,,}" == "y" ]] && rm -f "${resolved}" && info "Removed: ${resolved}"
                fi
            else
                # Cross device — copy resolved file
                if rsync -a "${resolved}" "${dstlink}"; then
                    app_cleanup+=("${srclink}|${dstlink}|rsync_symlink")
                    echo
                    warn "Symlink resolved and copied (cross-device): ${srclink} → ${resolved}"
                    read -r -p "       Remove original resolved file ${resolved}? [y/N]: " rm_choice
                    rm_choice="${rm_choice:-n}"
                    [[ "${rm_choice,,}" == "y" ]] && rm -f "${resolved}" && info "Removed: ${resolved}"
                fi
            fi
        done < <(find "${src}" -type l -print0)

    else
        # rsync copy
        if rsync -a --info=progress2 "${src}/" "${dst}/"; then
            # Build cleanup list from what rsync copied
            while IFS= read -r -d '' srcfile; do
                local relpath="${srcfile#${src}/}"
                local dstfile="${dst}/${relpath}"
                app_cleanup+=("${srcfile}|${dstfile}|rsync")
            done < <(find "${src}" -type f -print0)
        else
            fail "${app_name}: rsync failed"
            copy_ok=0
        fi
    fi

    if [[ "${copy_ok}" -eq 0 ]]; then
        # Rollback — remove everything we copied for this app
        warn "Rolling back ${app_name} — removing copied files"
        for entry in "${app_cleanup[@]}"; do
            local dstfile="${entry#*|}"
            dstfile="${dstfile%|*}"
            rm -f "${dstfile}" 2>/dev/null || true
        done
        return 1
    fi

    # Verify: count files at destination
    local dst_count
    dst_count="$(find "${dst}" -type f | wc -l)"
    if [[ "${dst_count}" -lt "${src_count}" ]]; then
        fail "${app_name}: Verification failed — expected ${src_count} files, found ${dst_count} at destination"
        # Rollback
        warn "Rolling back ${app_name}"
        for entry in "${app_cleanup[@]}"; do
            local dstfile="${entry#*|}"
            dstfile="${dstfile%|*}"
            rm -f "${dstfile}" 2>/dev/null || true
        done
        return 1
    fi

    # Verification passed — add to global cleanup list
    CLEANUP_LIST+=("${app_cleanup[@]}")

    # Prune source files (now that copies are verified)
    info "Pruning source files..."
    for entry in "${app_cleanup[@]}"; do
        local srcfile="${entry%%|*}"
        # For symlinks: remove the symlink only (not resolved target unless user said yes above)
        rm -f "${srcfile}" 2>/dev/null || true
    done

    # Remove empty source dirs (but not the root src dir itself — that becomes/stays a symlink)
    find "${src}" -mindepth 1 -type d -empty -delete 2>/dev/null || true

    done_ "${app_name}: ${src_count} file(s) moved successfully"

    # Cross-device: leave breadcrumb
    if [[ "${method}" == "rsync" && "${src_dev}" != "${dst_dev}" ]]; then
        ln -sfn "${dst}" "${src}.moved_to" 2>/dev/null || true
        cat > "${src}.THIS_FOLDER_HAS_BEEN_MOVED.txt" << BREADCRUMB
This folder has been moved by ai_migrate_resources.sh.

Original location : ${src}
New location      : ${dst}
Moved on          : $(date)
Moved by          : ai_migrate_resources.sh --migrate

To find your files, go to:
  ${dst}

This text file and the .moved_to symlink can be safely removed
once you have confirmed everything is working correctly.
BREADCRUMB
        info "Left breadcrumb at ${src}.THIS_FOLDER_HAS_BEEN_MOVED.txt"
    fi

    return 0
}

# ---------------------------------------------------------------------------
# Ensure a symlink exists and points to the right place.
# In scan mode: report what would happen.
# In migrate mode: act.
# ---------------------------------------------------------------------------
ensure_symlink() {
    local link="$1"
    local target="$2"
    local app_dir="${3:-}"
    local app_name="${4:-unknown}"

    # Skip if app not installed
    if [[ -n "${app_dir}" && ! -d "${app_dir}" ]]; then
        WOULD_SKIP+=("${app_name}: app not installed at ${app_dir}")
        return 0
    fi

    # Ensure canonical target dir exists — avoid duplicate WOULD_CREATE entries
    if [[ "${MODE}" == "migrate" ]]; then
        mkdir -p "${target}"
    else
        if [[ ! -d "${target}" ]]; then
            local already_listed=0
            for existing in "${WOULD_CREATE[@]:-}"; do
                [[ "${existing}" == "${target}" ]] && already_listed=1 && break
            done
            [[ "${already_listed}" -eq 0 ]] && WOULD_CREATE+=("${target}")
        fi
    fi

    # Already correct — compare resolved absolute paths to handle relative symlinks
    if [[ -L "${link}" ]]; then
        local resolved_current
        resolved_current="$(readlink -f "${link}" 2>/dev/null || true)"
        local resolved_target
        resolved_target="$(readlink -f "${target}" 2>/dev/null || echo "${target}")"
        if [[ "${resolved_current}" == "${resolved_target}" ]]; then
            ALREADY_OK+=("${link} → ${target}")
            return 0
        fi
    fi

    # Wrong target symlink
    if [[ -L "${link}" ]]; then
        local old_target
        old_target="$(readlink "${link}")"
        if [[ "${MODE}" == "migrate" ]]; then
            rm "${link}"
            ln -s "${target}" "${link}"
            done_ "Updated symlink: ${link} → ${target}  (was → ${old_target})"
        else
            WOULD_SYMLINK+=("UPDATE: ${link} → ${target}  (currently → ${old_target})")
        fi
        return 0
    fi

    # Real directory exists — need to move contents then replace with symlink
    if [[ -d "${link}" ]]; then
        if [[ "${MODE}" == "migrate" ]]; then
            if move_dir_contents "${link}" "${target}" "${app_name}"; then
                rm -rf "${link}"
                ln -s "${target}" "${link}"
                done_ "Replaced dir with symlink: ${link} → ${target}"
            else
                fail "Could not replace ${link} with symlink — leaving untouched"
            fi
        else
            local fcount
            fcount="$(find "${link}" -type f 2>/dev/null | wc -l)"
            if [[ "${fcount}" -eq 0 ]]; then
                # Empty dir — just replace with symlink, no move needed
                WOULD_SYMLINK+=("CREATE (replace empty dir): ${link} → ${target}")
            else
                WOULD_MOVE+=("${link} → ${target}  (${fcount} files)")
                WOULD_SYMLINK+=("CREATE: ${link} → ${target}")
            fi
        fi
        return 0
    fi

    # Nothing there — just create
    if [[ "${MODE}" == "migrate" ]]; then
        mkdir -p "$(dirname "${link}")"
        ln -s "${target}" "${link}"
        done_ "Created symlink: ${link} → ${target}"
    else
        WOULD_SYMLINK+=("CREATE: ${link} → ${target}  (nothing currently there)")
    fi
}

# ---------------------------------------------------------------------------
# Scan: walk app dirs looking for paths referencing old locations
# ---------------------------------------------------------------------------
scan_configs() {
    hdr "Config file scan..."

    local old_paths=(
        "${SHARED}/image/Outputs"
        "${SHARED}/video/Outputs"
        "${SHARED}/video/Outputs/FrameworkStudio"
        "${SHARED}/video/Outputs/Wan2GP"
    )

    local app_dirs=(
        "${A1111_DIR}"
        "${INVOKE_DIR}"
        "${WAN2GP_DIR}"
        "${FPS_DIR}"
        "${COMFY_DIR}"
    )

    local found_any=0

    for app_dir in "${app_dirs[@]}"; do
        [[ ! -d "${app_dir}" ]] && continue
        local app_name
        app_name="$(basename "${app_dir}")"

        # Find config files
        while IFS= read -r -d '' cfg; do
            for old_path in "${old_paths[@]}"; do
                if grep -q "${old_path}" "${cfg}" 2>/dev/null; then
                    warn "Config references old path in ${app_name}:"
                    info "  File: ${cfg}"
                    info "  Contains: ${old_path}"
                    info "  ACTION NEEDED: Manual review recommended"
                    found_any=1
                fi
            done
        done < <(find "${app_dir}" -maxdepth 3 \
            \( -name "*.yaml" -o -name "*.yml" -o -name "*.json" \
               -o -name "*.toml" -o -name "*.ini" -o -name "*.sh" \) \
            -not -path "*/venv/*" \
            -not -path "*/.git/*" \
            -print0 2>/dev/null)
    done

    [[ "${found_any}" -eq 0 ]] && ok "No config files reference old paths"
}

# ---------------------------------------------------------------------------
# Scan: check for unknown dirs in app model locations that might be shareable
# ---------------------------------------------------------------------------
scan_for_mergeable() {
    hdr "Scanning for potentially shareable resources..."

    # A1111 model dirs we know about
    local known_a1111=(
        "Stable-diffusion" "VAE" "Lora" "ControlNet"
        "ESRGAN" "GFPGAN" "hypernetworks" "Codeformer"
    )

    if [[ -d "${A1111_DIR}/models" ]]; then
        while IFS= read -r -d '' d; do
            local dname
            dname="$(basename "${d}")"
            # Skip backup dirs created by this script and known non-model dirs
            [[ "${dname}" == *".bak."* ]] && continue
            [[ "${dname}" == "karlo" ]] && continue        # A1111 internal
            [[ "${dname}" == "deepbooru" ]] && continue   # A1111 internal tagger
            [[ "${dname}" == "VAE-approx" ]] && continue  # A1111 internal
            local known=0
            for k in "${known_a1111[@]}"; do
                [[ "${dname}" == "${k}" ]] && known=1 && break
            done
            if [[ "${known}" -eq 0 ]]; then
                local fcount
                fcount="$(find "${d}" -type f 2>/dev/null | wc -l)"
                warn "Unknown A1111 model dir: ${d}  (${fcount} files)"
                info "  SUGGESTION: Consider adding to shared tree if other apps can use it"
            fi
        done < <(find "${A1111_DIR}/models" -maxdepth 1 -mindepth 1 -type d -print0 2>/dev/null)
    fi

    # ComfyUI custom nodes — report what's installed
    if [[ -d "${COMFY_DIR}/custom_nodes" ]]; then
        local cncount
        cncount="$(find "${COMFY_DIR}/custom_nodes" -maxdepth 1 -mindepth 1 -type d | wc -l)"
        info "ComfyUI has ${cncount} custom node(s) installed"
        info "  → custom_nodes are not shared — each ComfyUI install manages its own"
    fi

    # InvokeAI models — report what's there
    if [[ -d "${INVOKE_DIR}/models" ]]; then
        local icount
        icount="$(find "${INVOKE_DIR}/models" -type f 2>/dev/null | wc -l)"
        if [[ "${icount}" -gt 0 ]]; then
            info "InvokeAI models dir contains ${icount} file(s)"
            info "  → Run after first InvokeAI launch to see full structure"
            info "  → Some models may be shareable with A1111 once structure is known"
        else
            ok "InvokeAI models dir is empty (pre-first-launch)"
        fi
    fi
}

# ---------------------------------------------------------------------------
# --verify mode: quick symlink check only
# ---------------------------------------------------------------------------
run_verify() {
    hdr "Symlink verification"

    local all_ok=1

    check_link() {
        local link="$1" target="$2" app_dir="${3:-}"
        [[ -n "${app_dir}" && ! -d "${app_dir}" ]] && skip "$(basename "${app_dir}") not installed" && return
        if [[ -L "${link}" && "$(readlink "${link}")" == "${target}" ]]; then
            ok "${link} → ${target}"
        elif [[ -L "${link}" ]]; then
            warn "Wrong target: ${link} → $(readlink "${link}")  (want ${target})"
            all_ok=0
        elif [[ -e "${link}" ]]; then
            warn "Not a symlink: ${link}"
            all_ok=0
        else
            warn "Missing: ${link}"
            all_ok=0
        fi
    }

    check_link "${A1111_DIR}/models/Stable-diffusion" "${SHARED}/image/Checkpoints"          "${A1111_DIR}"
    check_link "${A1111_DIR}/models/VAE"               "${SHARED}/image/VAE"                  "${A1111_DIR}"
    check_link "${A1111_DIR}/models/Lora"              "${SHARED}/image/Lora"                 "${A1111_DIR}"
    check_link "${A1111_DIR}/embeddings"               "${SHARED}/image/Embeddings/A1111"     "${A1111_DIR}"
    check_link "${A1111_DIR}/models/ControlNet"        "${SHARED}/image/ControlNet"           "${A1111_DIR}"
    check_link "${A1111_DIR}/models/ESRGAN"            "${SHARED}/image/Upscalers"            "${A1111_DIR}"
    check_link "${A1111_DIR}/models/GFPGAN"            "${SHARED}/image/GFPGAN"               "${A1111_DIR}"
    check_link "${A1111_DIR}/outputs"                  "${OUTPUTS}/A1111/ALL_Outputs"         "${A1111_DIR}"
    check_link "${INVOKE_DIR}/models"                  "${SHARED}/image/Invokeai-Models"      "${INVOKE_DIR}"
    check_link "${INVOKE_DIR}/outputs"                 "${OUTPUTS}/Invoke/ALL_Outputs"        "${INVOKE_DIR}"
    check_link "${WAN2GP_DIR}/outputs"                 "${OUTPUTS}/Wan2GP"                    "${WAN2GP_DIR}"
    check_link "${FPS_DIR}/outputs"                    "${OUTPUTS}/FramePack"                 "${FPS_DIR}"
    check_link "${COMFY_DIR}/output"                   "${OUTPUTS}/ComfyUI"                   "${COMFY_DIR}"

    echo
    if [[ "${all_ok}" -eq 1 ]]; then
        echo -e "  ${GRN}All symlinks correct.${RST}"
    else
        echo -e "  ${YLW}Some symlinks need attention. Run:${RST}"
        echo "    ai_migrate_resources.sh          # to see full scan"
        echo "    ai_migrate_resources.sh --migrate # to fix"
    fi
}

# ---------------------------------------------------------------------------
# Main shared tree creation
# ---------------------------------------------------------------------------
ensure_shared_tree() {
    local dirs=(
        "${SHARED}/huggingface"
        "${SHARED}/image/Checkpoints/sd-1"
        "${SHARED}/image/Checkpoints/sd-2"
        "${SHARED}/image/Checkpoints/sdxl"
        "${SHARED}/image/ControlNet"
        "${SHARED}/image/Embeddings/A1111"
        "${SHARED}/image/Embeddings/Invoke"
        "${SHARED}/image/GFPGAN"
        "${SHARED}/image/Invokeai-Models"
        "${SHARED}/image/Lora"
        "${SHARED}/image/Upscalers"
        "${SHARED}/image/VAE"
        "${SHARED}/video/Lora"
        "${SHARED}/video/Models"
        "${SHARED}/video/TextEncoders"
        "${SHARED}/video/Upscalers"
        "${SHARED}/video/VAE"
        "${OUTPUTS}/A1111/ALL_Outputs"
        "${OUTPUTS}/ComfyUI/Image"
        "${OUTPUTS}/ComfyUI/Video"
        "${OUTPUTS}/FramePack/Image"
        "${OUTPUTS}/FramePack/Video"
        "${OUTPUTS}/Invoke/ALL_Outputs"
        "${OUTPUTS}/Wan2GP/Image"
        "${OUTPUTS}/Wan2GP/Video"
    )

    for d in "${dirs[@]}"; do
        if [[ ! -d "${d}" ]]; then
            if [[ "${MODE}" == "migrate" ]]; then
                mkdir -p "${d}"
                done_ "Created: ${d}"
            else
                WOULD_CREATE+=("${d}")
            fi
        fi
    done
}

# ---------------------------------------------------------------------------
# Wire all symlinks
# ---------------------------------------------------------------------------
wire_symlinks() {
    hdr "A1111 symlinks"
    ensure_symlink "${A1111_DIR}/models/Stable-diffusion" "${SHARED}/image/Checkpoints"      "${A1111_DIR}" "A1111"
    ensure_symlink "${A1111_DIR}/models/VAE"               "${SHARED}/image/VAE"              "${A1111_DIR}" "A1111"
    ensure_symlink "${A1111_DIR}/models/Lora"              "${SHARED}/image/Lora"             "${A1111_DIR}" "A1111"
    ensure_symlink "${A1111_DIR}/embeddings"               "${SHARED}/image/Embeddings/A1111" "${A1111_DIR}" "A1111"
    ensure_symlink "${A1111_DIR}/models/ControlNet"        "${SHARED}/image/ControlNet"       "${A1111_DIR}" "A1111"
    ensure_symlink "${A1111_DIR}/models/ESRGAN"            "${SHARED}/image/Upscalers"        "${A1111_DIR}" "A1111"
    ensure_symlink "${A1111_DIR}/models/GFPGAN"            "${SHARED}/image/GFPGAN"           "${A1111_DIR}" "A1111"
    ensure_symlink "${A1111_DIR}/outputs"                  "${OUTPUTS}/A1111/ALL_Outputs"     "${A1111_DIR}" "A1111"

    hdr "InvokeAI symlinks"
    ensure_symlink "${INVOKE_DIR}/models"  "${SHARED}/image/Invokeai-Models"  "${INVOKE_DIR}" "InvokeAI"
    ensure_symlink "${INVOKE_DIR}/outputs" "${OUTPUTS}/Invoke/ALL_Outputs"    "${INVOKE_DIR}" "InvokeAI"

    hdr "Wan2GP symlinks"
    ensure_symlink "${WAN2GP_DIR}/outputs" "${OUTPUTS}/Wan2GP" "${WAN2GP_DIR}" "Wan2GP"

    hdr "FramePack-Studio symlinks"
    ensure_symlink "${FPS_DIR}/outputs" "${OUTPUTS}/FramePack" "${FPS_DIR}" "FramePack-Studio"

    hdr "ComfyUI symlinks"
    ensure_symlink "${COMFY_DIR}/output" "${OUTPUTS}/ComfyUI" "${COMFY_DIR}" "ComfyUI"
}

# ---------------------------------------------------------------------------
# Migrate existing outputs from old AI-Shared-Resources locations
# ---------------------------------------------------------------------------
migrate_old_outputs() {
    hdr "Migrating existing outputs from old locations..."

    # A1111 stray output subdirs sitting loose in image/Outputs/
    if [[ -d "${OLD_A1111_OUTPUTS}" ]]; then
        local stray_dirs=()
        while IFS= read -r -d '' d; do
            local dname
            dname="$(basename "${d}")"
            # Skip the A1111/ subdir itself — that's handled by symlink
            [[ "${dname}" == "A1111" ]] && continue
            stray_dirs+=("${d}")
        done < <(find "${OLD_A1111_OUTPUTS}" -maxdepth 1 -mindepth 1 -type d -print0 2>/dev/null)

        for stray in "${stray_dirs[@]}"; do
            local dname
            dname="$(basename "${stray}")"

            # Route known app dirs to their correct output locations
            local dest
            case "${dname}" in
                InvokeAI)  dest="${OUTPUTS}/Invoke/ALL_Outputs" ;;
                ComfyUI)   dest="${OUTPUTS}/ComfyUI" ;;
                *)         dest="${OUTPUTS}/A1111/ALL_Outputs/${dname}" ;;
            esac

            if [[ "${MODE}" == "migrate" ]]; then
                move_dir_contents "${stray}" "${dest}" "stray-outputs"
            else
                local fcount
                fcount="$(find "${stray}" -type f 2>/dev/null | wc -l)"
                WOULD_MOVE+=("Stray outputs: ${stray} → ${dest}  (${fcount} files)")
            fi
        done
    fi

    # Wan2GP outputs
    if [[ -d "${OLD_WAN2GP_OUTPUTS}" ]]; then
        if [[ "${MODE}" == "migrate" ]]; then
            move_dir_contents "${OLD_WAN2GP_OUTPUTS}" "${OUTPUTS}/Wan2GP" "Wan2GP-outputs"
        else
            local fcount
            fcount="$(find "${OLD_WAN2GP_OUTPUTS}" -type f 2>/dev/null | wc -l)"
            WOULD_MOVE+=("Wan2GP outputs: ${OLD_WAN2GP_OUTPUTS} → ${OUTPUTS}/Wan2GP  (${fcount} files)")
        fi
    fi

    # FramePack outputs (fixes FrameworkStudio typo)
    if [[ -d "${OLD_FPS_OUTPUTS}" ]]; then
        if [[ "${MODE}" == "migrate" ]]; then
            move_dir_contents "${OLD_FPS_OUTPUTS}" "${OUTPUTS}/FramePack" "FramePack-outputs"
        else
            local fcount
            fcount="$(find "${OLD_FPS_OUTPUTS}" -type f 2>/dev/null | wc -l)"
            WOULD_MOVE+=("FramePack outputs (fixes FrameworkStudio typo): ${OLD_FPS_OUTPUTS} → ${OUTPUTS}/FramePack  (${fcount} files)")
        fi
    fi
}

# ---------------------------------------------------------------------------
# Print scan report
# ---------------------------------------------------------------------------
print_scan_report() {
    echo
    echo -e "${BLD}╔══════════════════════════════════════════════════════════════╗${RST}"
    echo -e "${BLD}║              SCAN REPORT — ai_migrate_resources              ║${RST}"
    echo -e "${BLD}╚══════════════════════════════════════════════════════════════╝${RST}"

    if [[ "${#WOULD_CREATE[@]}" -gt 0 ]]; then
        echo
        echo -e "  ${CYN}WOULD CREATE:${RST}"
        for item in "${WOULD_CREATE[@]}"; do
            echo "    📁  ${item}"
        done
    fi

    if [[ "${#WOULD_MOVE[@]}" -gt 0 ]]; then
        echo
        echo -e "  ${CYN}WOULD MOVE:${RST}"
        for item in "${WOULD_MOVE[@]}"; do
            echo "    📦  ${item}"
        done
    fi

    if [[ "${#WOULD_SYMLINK[@]}" -gt 0 ]]; then
        echo
        echo -e "  ${CYN}WOULD SYMLINK:${RST}"
        for item in "${WOULD_SYMLINK[@]}"; do
            echo "    🔗  ${item}"
        done
    fi

    if [[ "${#WOULD_SKIP[@]}" -gt 0 ]]; then
        echo
        echo -e "  WOULD SKIP (app not installed):"
        for item in "${WOULD_SKIP[@]}"; do
            echo "    ⏭   ${item}"
        done
    fi

    if [[ "${#ALREADY_OK[@]}" -gt 0 ]]; then
        echo
        echo -e "  ${GRN}ALREADY CORRECT (no action needed):${RST}"
        for item in "${ALREADY_OK[@]}"; do
            echo "    ✅  ${item}"
        done
    fi

    if [[ "${#BLOCKERS[@]}" -gt 0 ]]; then
        echo
        echo -e "  ${RED}BLOCKERS (would prevent --migrate from proceeding):${RST}"
        for item in "${BLOCKERS[@]}"; do
            echo "    🚫  ${item}"
        done
    else
        echo
        echo -e "  ${GRN}BLOCKERS: none${RST}"
    fi

    echo
    echo -e "${BLD}═══════════════════════════════════════════════════════════════${RST}"
    echo "  Scan complete — no changes made."
    echo
    echo "  To act on the above:"
    echo "    ai_migrate_resources.sh --migrate   # perform all changes"
    echo "    ai_migrate_resources.sh --verify    # check symlinks only"
    echo "    ai_migrate_resources.sh             # re-scan"
    echo -e "${BLD}═══════════════════════════════════════════════════════════════${RST}"
    echo
}

# ---------------------------------------------------------------------------
# Legacy helpers
# ---------------------------------------------------------------------------

# _legacy_skip_file <filename>
# Returns 0 (true/skip) for files we never want to hardlink from legacy trees:
#   .meta.json sidecars, plain text files, preview images, spreadsheets,
#   and the "Put XXX here" placeholder text files.
_legacy_skip_file() {
    local f="$1"
    case "${f}" in
        *.meta.json)  return 0 ;;
        *.txt)        return 0 ;;
        *.png)        return 0 ;;
        *.tsv)        return 0 ;;
    esac
    return 1
}

# _legacy_route_checkpoint <filename> → prints target subdir name (sd-1 | sd-2 | sdxl | unknown)
# Routing rules based on observed filenames in AI_Resources-common/Stable-diffusion/:
#   v1-5-* or sd-v1-5-*  →  sd-1
#   v2-1_*               →  sd-2
#   *-sdxl-* or *sdxl*   →  sdxl
#   anything else        →  unknown  (will warn, not hardlink)
_legacy_route_checkpoint() {
    local fname="$1"
    case "${fname}" in
        v1-5-*|sd-v1-5-*)  echo "sd-1"    ;;
        v2-1_*)             echo "sd-2"    ;;
        *-sdxl-*|*sdxl*)   echo "sdxl"    ;;
        *)                  echo "unknown" ;;
    esac
}

# _hardlink_file <src> <dst>
# Hardlinks src to dst. dst parent dir must already exist.
# Pre:  src is a regular file; dst does not exist; same filesystem.
# Post: dst exists with same inode as src.
# Returns 0 on success, 1 on failure (logs error).
_hardlink_file() {
    local src="$1" dst="$2"
    if ln "${src}" "${dst}" 2>/dev/null; then
        return 0
    fi
    fail "hardlink failed: ${src} → ${dst}"
    return 1
}

# ---------------------------------------------------------------------------
# do_hardlink_legacy
# ---------------------------------------------------------------------------
# Walks both legacy source trees and hardlinks model files into their correct
# locations under AI-Shared-Resources.  Already-linked files (same inode)
# are silently skipped.  Files that would overwrite a different inode at the
# destination are skipped with a warning — never clobber.
# ---------------------------------------------------------------------------
do_hardlink_legacy() {
    local errors=0
    local linked=0
    local skipped_already=0
    local skipped_skip=0
    local skipped_conflict=0

    # --- helper: hardlink one file, with inode-check ---
    # _hl_one <src> <dst_dir>
    # dst filename = basename of src.
    _hl_one() {
        local src="$1" dst_dir="$2"
        local fname dst
        fname="$(basename "${src}")"
        dst="${dst_dir}/${fname}"

        # Files we never want
        if _legacy_skip_file "${fname}"; then
            (( skipped_skip++ )) || true
            return 0
        fi

        # Already linked (same inode) — nothing to do
        if [[ -e "${dst}" ]]; then
            local src_ino dst_ino
            src_ino="$(stat --format='%i' "${src}" 2>/dev/null || echo 0)"
            dst_ino="$(stat --format='%i' "${dst}" 2>/dev/null || echo 1)"
            if [[ "${src_ino}" == "${dst_ino}" ]]; then
                (( skipped_already++ )) || true
                return 0
            fi
            # Different content at destination — do not overwrite
            warn "CONFLICT — different file already at destination, skipping:"
            info "  src: ${src}"
            info "  dst: ${dst}"
            (( skipped_conflict++ )) || true
            return 0
        fi

        mkdir -p "${dst_dir}"
        if _hardlink_file "${src}" "${dst}"; then
            done_ "linked: ${fname}  →  ${dst_dir}/"
            (( linked++ )) || true
        else
            (( errors++ )) || true
        fi
    }

    # ------------------------------------------------------------------
    # 1. AI_Resources-common/Stable-diffusion/  →  image/Checkpoints/{sd-1,sd-2,sdxl}/
    # ------------------------------------------------------------------
    hdr "Legacy checkpoints: AI_Resources-common/Stable-diffusion/"
    local src_ckpt="${LEGACY_COMMON}/Stable-diffusion"
    if [[ ! -d "${src_ckpt}" ]]; then
        warn "Source not found — skipping: ${src_ckpt}"
    else
        while IFS= read -r -d '' f; do
            local fname subdir
            fname="$(basename "${f}")"
            if _legacy_skip_file "${fname}"; then
                (( skipped_skip++ )) || true
                continue
            fi
            subdir="$(_legacy_route_checkpoint "${fname}")"
            if [[ "${subdir}" == "unknown" ]]; then
                warn "Cannot route checkpoint — unrecognised name, skipping: ${fname}"
                (( skipped_conflict++ )) || true
                continue
            fi
            _hl_one "${f}" "${SHARED}/image/Checkpoints/${subdir}"
        done < <(find "${src_ckpt}" -maxdepth 1 -type f -print0 2>/dev/null)
    fi

    # ------------------------------------------------------------------
    # 2. AI_Resources-common/ControlNet/  →  image/ControlNet/
    # ------------------------------------------------------------------
    hdr "Legacy ControlNet: AI_Resources-common/ControlNet/"
    local src_cn="${LEGACY_COMMON}/ControlNet"
    if [[ ! -d "${src_cn}" ]]; then
        warn "Source not found — skipping: ${src_cn}"
    else
        # ControlNet may have subdirs (T2I adapters etc) — walk recursively,
        # preserve relative structure under image/ControlNet/
        while IFS= read -r -d '' f; do
            local fname relpath dst_dir
            fname="$(basename "${f}")"
            if _legacy_skip_file "${fname}"; then
                (( skipped_skip++ )) || true
                continue
            fi
            relpath="${f#${src_cn}/}"
            relpath="$(dirname "${relpath}")"
            if [[ "${relpath}" == "." ]]; then
                dst_dir="${SHARED}/image/ControlNet"
            else
                dst_dir="${SHARED}/image/ControlNet/${relpath}"
            fi
            _hl_one "${f}" "${dst_dir}"
        done < <(find "${src_cn}" -type f -print0 2>/dev/null)
    fi

    # ------------------------------------------------------------------
    # 3. AI_Resources-common/Embeddings/  →  image/Embeddings/A1111/
    #    Only .bin .pt .safetensors — skip everything else
    # ------------------------------------------------------------------
    hdr "Legacy embeddings: AI_Resources-common/Embeddings/"
    local src_emb="${LEGACY_COMMON}/Embeddings"
    if [[ ! -d "${src_emb}" ]]; then
        warn "Source not found — skipping: ${src_emb}"
    else
        while IFS= read -r -d '' f; do
            local fname
            fname="$(basename "${f}")"
            # Only embedding model formats
            case "${fname}" in
                *.bin|*.pt|*.safetensors) : ;;
                *) (( skipped_skip++ )) || true; continue ;;
            esac
            _hl_one "${f}" "${SHARED}/image/Embeddings/A1111"
        done < <(find "${src_emb}" -maxdepth 1 -type f -print0 2>/dev/null)
    fi

    # ------------------------------------------------------------------
    # 4. AI_downloaded/  →  video/{Models,Lora,TextEncoders,VAE}/
    # ------------------------------------------------------------------
    local -A dl_map=(
        ["diffusion_models"]="video/Models"
        ["loras"]="video/Lora"
        ["text_encoders"]="video/TextEncoders"
        ["vae"]="video/VAE"
    )
    for src_sub in diffusion_models loras text_encoders vae; do
        local src_dir dst_sub
        src_dir="${LEGACY_DOWNLOADED}/${src_sub}"
        dst_sub="${dl_map[${src_sub}]}"
        hdr "Legacy video: AI_downloaded/${src_sub}/"
        if [[ ! -d "${src_dir}" ]]; then
            warn "Source not found — skipping: ${src_dir}"
            continue
        fi
        while IFS= read -r -d '' f; do
            local fname relpath dst_dir
            fname="$(basename "${f}")"
            if _legacy_skip_file "${fname}"; then
                (( skipped_skip++ )) || true
                continue
            fi
            relpath="${f#${src_dir}/}"
            relpath="$(dirname "${relpath}")"
            if [[ "${relpath}" == "." ]]; then
                dst_dir="${SHARED}/${dst_sub}"
            else
                dst_dir="${SHARED}/${dst_sub}/${relpath}"
            fi
            _hl_one "${f}" "${dst_dir}"
        done < <(find "${src_dir}" -type f -print0 2>/dev/null)
    done

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    echo
    echo -e "${BLD}╔══════════════════════════════════════════════════════════════╗${RST}"
    echo -e "${BLD}║                HARDLINK LEGACY — COMPLETE                    ║${RST}"
    echo -e "${BLD}╚══════════════════════════════════════════════════════════════╝${RST}"
    echo
    echo "  Linked          : ${linked}"
    echo "  Already linked  : ${skipped_already}"
    echo "  Skipped (type)  : ${skipped_skip}"
    echo "  Conflicts       : ${skipped_conflict}"
    echo "  Errors          : ${errors}"
    echo
    if [[ "${errors}" -gt 0 || "${skipped_conflict}" -gt 0 ]]; then
        echo -e "  ${YLW}Review warnings above before running --verify-legacy.${RST}"
    else
        echo -e "  ${GRN}Clean run. Now verify with:${RST}"
        echo "    ai_migrate_resources.sh --verify-legacy"
    fi
    echo
    if [[ "${errors}" -gt 0 ]]; then
        return 1
    fi
}

# ---------------------------------------------------------------------------
# do_verify_legacy
# ---------------------------------------------------------------------------
# For every non-skipped file in both legacy source trees, confirms that the
# same inode exists at the expected destination.  Reports any missing or
# mismatched files.  Writes the sentinel file only when 100% clean.
# ---------------------------------------------------------------------------
do_verify_legacy() {
    local total=0
    local ok_count=0
    local missing=0
    local mismatch=0

    # _vfy_one <src> <dst_dir>
    _vfy_one() {
        local src="$1" dst_dir="$2"
        local fname dst
        fname="$(basename "${src}")"
        dst="${dst_dir}/${fname}"
        (( total++ )) || true

        if [[ ! -e "${dst}" ]]; then
            fail "MISSING at destination: ${dst}"
            (( missing++ )) || true
            return
        fi

        local src_ino dst_ino
        src_ino="$(stat --format='%i' "${src}" 2>/dev/null || echo 0)"
        dst_ino="$(stat --format='%i' "${dst}" 2>/dev/null || echo 1)"
        if [[ "${src_ino}" == "${dst_ino}" ]]; then
            (( ok_count++ )) || true
        else
            fail "INODE MISMATCH (not hardlinked): ${src}"
            info "  expected inode ${src_ino}, destination has ${dst_ino}"
            (( mismatch++ )) || true
        fi
    }

    # Stable-diffusion
    hdr "Verify: Stable-diffusion/ checkpoints"
    local src_ckpt="${LEGACY_COMMON}/Stable-diffusion"
    if [[ -d "${src_ckpt}" ]]; then
        while IFS= read -r -d '' f; do
            local fname subdir
            fname="$(basename "${f}")"
            _legacy_skip_file "${fname}" && continue
            subdir="$(_legacy_route_checkpoint "${fname}")"
            [[ "${subdir}" == "unknown" ]] && continue
            _vfy_one "${f}" "${SHARED}/image/Checkpoints/${subdir}"
        done < <(find "${src_ckpt}" -maxdepth 1 -type f -print0 2>/dev/null)
    fi

    # ControlNet
    hdr "Verify: ControlNet/"
    local src_cn="${LEGACY_COMMON}/ControlNet"
    if [[ -d "${src_cn}" ]]; then
        while IFS= read -r -d '' f; do
            local fname relpath dst_dir
            fname="$(basename "${f}")"
            _legacy_skip_file "${fname}" && continue
            relpath="${f#${src_cn}/}"
            relpath="$(dirname "${relpath}")"
            [[ "${relpath}" == "." ]] && dst_dir="${SHARED}/image/ControlNet" \
                                      || dst_dir="${SHARED}/image/ControlNet/${relpath}"
            _vfy_one "${f}" "${dst_dir}"
        done < <(find "${src_cn}" -type f -print0 2>/dev/null)
    fi

    # Embeddings
    hdr "Verify: Embeddings/"
    local src_emb="${LEGACY_COMMON}/Embeddings"
    if [[ -d "${src_emb}" ]]; then
        while IFS= read -r -d '' f; do
            local fname
            fname="$(basename "${f}")"
            case "${fname}" in *.bin|*.pt|*.safetensors) : ;; *) continue ;; esac
            _vfy_one "${f}" "${SHARED}/image/Embeddings/A1111"
        done < <(find "${src_emb}" -maxdepth 1 -type f -print0 2>/dev/null)
    fi

    # AI_downloaded video dirs
    local -A dl_map=(
        ["diffusion_models"]="video/Models"
        ["loras"]="video/Lora"
        ["text_encoders"]="video/TextEncoders"
        ["vae"]="video/VAE"
    )
    for src_sub in diffusion_models loras text_encoders vae; do
        local src_dir dst_sub
        src_dir="${LEGACY_DOWNLOADED}/${src_sub}"
        dst_sub="${dl_map[${src_sub}]}"
        hdr "Verify: AI_downloaded/${src_sub}/"
        [[ ! -d "${src_dir}" ]] && warn "Not found: ${src_dir}" && continue
        while IFS= read -r -d '' f; do
            local fname relpath dst_dir
            fname="$(basename "${f}")"
            _legacy_skip_file "${fname}" && continue
            relpath="${f#${src_dir}/}"
            relpath="$(dirname "${relpath}")"
            [[ "${relpath}" == "." ]] && dst_dir="${SHARED}/${dst_sub}" \
                                      || dst_dir="${SHARED}/${dst_sub}/${relpath}"
            _vfy_one "${f}" "${dst_dir}"
        done < <(find "${src_dir}" -type f -print0 2>/dev/null)
    done

    # ------------------------------------------------------------------
    # Summary and sentinel
    # ------------------------------------------------------------------
    echo
    echo -e "${BLD}╔══════════════════════════════════════════════════════════════╗${RST}"
    echo -e "${BLD}║                  VERIFY LEGACY — RESULTS                     ║${RST}"
    echo -e "${BLD}╚══════════════════════════════════════════════════════════════╝${RST}"
    echo
    echo "  Total checked   : ${total}"
    echo "  Correct         : ${ok_count}"
    echo "  Missing at dest : ${missing}"
    echo "  Inode mismatch  : ${mismatch}"
    echo

    rm -f "${LEGACY_VERIFY_SENTINEL}"

    if [[ "${missing}" -eq 0 && "${mismatch}" -eq 0 ]]; then
        echo -e "  ${GRN}✔ 100% verified — all files correctly hardlinked.${RST}"
        echo
        # Write sentinel so --prune-legacy knows verify just passed
        echo "verified_at=$(date -Iseconds)" > "${LEGACY_VERIFY_SENTINEL}"
        echo "  Sentinel written. You may now safely run:"
        echo "    ai_migrate_resources.sh --prune-legacy"
    else
        echo -e "  ${RED}✘ Verify FAILED — do NOT run --prune-legacy.${RST}"
        echo "  Run --hardlink-legacy again to fix missing/mismatched files."
        return 1
    fi
    echo
}

# ---------------------------------------------------------------------------
# do_prune_legacy
# ---------------------------------------------------------------------------
# Removes the original files from both legacy source trees.
# REFUSES to run unless the sentinel from --verify-legacy exists.
# The sentinel is per-user in /tmp so it cannot survive a reboot or
# survive being run in a different shell session without re-verifying.
# After pruning, sentinel is deleted.
# ---------------------------------------------------------------------------
do_prune_legacy() {
    # Hard gate: sentinel must exist
    if [[ ! -f "${LEGACY_VERIFY_SENTINEL}" ]]; then
        echo
        echo -e "${RED}REFUSED: --prune-legacy requires a passing --verify-legacy run first.${RST}"
        echo
        echo "  The sentinel file does not exist:"
        echo "    ${LEGACY_VERIFY_SENTINEL}"
        echo
        echo "  Run in order:"
        echo "    ai_migrate_resources.sh --hardlink-legacy"
        echo "    ai_migrate_resources.sh --verify-legacy"
        echo "    ai_migrate_resources.sh --prune-legacy"
        echo
        exit 1
    fi

    # Show what's in the sentinel for transparency
    echo
    echo -e "  Sentinel: $(cat "${LEGACY_VERIFY_SENTINEL}")"
    echo

    echo -e "${BLD}╔══════════════════════════════════════════════════════════════╗${RST}"
    echo -e "${BLD}║          PRUNE LEGACY — ABOUT TO DELETE SOURCE FILES         ║${RST}"
    echo -e "${BLD}╚══════════════════════════════════════════════════════════════╝${RST}"
    echo
    echo "  This will delete the original files from:"
    echo "    ${LEGACY_COMMON}/Stable-diffusion/"
    echo "    ${LEGACY_COMMON}/ControlNet/"
    echo "    ${LEGACY_COMMON}/Embeddings/  (model files only)"
    echo "    ${LEGACY_DOWNLOADED}/diffusion_models/"
    echo "    ${LEGACY_DOWNLOADED}/loras/"
    echo "    ${LEGACY_DOWNLOADED}/text_encoders/"
    echo "    ${LEGACY_DOWNLOADED}/vae/"
    echo
    echo -e "  ${YLW}The hardlinks in AI-Shared-Resources will be unaffected.${RST}"
    echo "  Only the legacy-tree copies (same inode) are removed."
    echo
    read -r -p "  Type YES to proceed with deletion: " _confirm
    if [[ "${_confirm}" != "YES" ]]; then
        echo
        echo "  Aborted — nothing deleted."
        echo
        exit 0
    fi

    local deleted=0
    local errors=0

    # _prune_one <src> <dst_dir>
    # Deletes src only if its inode matches dst — never deletes unverified files.
    _prune_one() {
        local src="$1" dst_dir="$2"
        local fname dst
        fname="$(basename "${src}")"
        dst="${dst_dir}/${fname}"

        if [[ ! -e "${dst}" ]]; then
            warn "Destination missing — NOT deleting source: ${src}"
            (( errors++ )) || true
            return
        fi

        local src_ino dst_ino
        src_ino="$(stat --format='%i' "${src}" 2>/dev/null || echo 0)"
        dst_ino="$(stat --format='%i' "${dst}" 2>/dev/null || echo 1)"
        if [[ "${src_ino}" != "${dst_ino}" ]]; then
            warn "Inode mismatch — NOT deleting source: ${src}"
            (( errors++ )) || true
            return
        fi

        rm -f "${src}"
        (( deleted++ )) || true
    }

    # Stable-diffusion
    hdr "Pruning: Stable-diffusion/"
    local src_ckpt="${LEGACY_COMMON}/Stable-diffusion"
    if [[ -d "${src_ckpt}" ]]; then
        while IFS= read -r -d '' f; do
            local fname subdir
            fname="$(basename "${f}")"
            _legacy_skip_file "${fname}" && continue
            subdir="$(_legacy_route_checkpoint "${fname}")"
            [[ "${subdir}" == "unknown" ]] && continue
            _prune_one "${f}" "${SHARED}/image/Checkpoints/${subdir}"
        done < <(find "${src_ckpt}" -maxdepth 1 -type f -print0 2>/dev/null)
    fi

    # ControlNet
    hdr "Pruning: ControlNet/"
    local src_cn="${LEGACY_COMMON}/ControlNet"
    if [[ -d "${src_cn}" ]]; then
        while IFS= read -r -d '' f; do
            local fname relpath dst_dir
            fname="$(basename "${f}")"
            _legacy_skip_file "${fname}" && continue
            relpath="${f#${src_cn}/}"
            relpath="$(dirname "${relpath}")"
            [[ "${relpath}" == "." ]] && dst_dir="${SHARED}/image/ControlNet" \
                                      || dst_dir="${SHARED}/image/ControlNet/${relpath}"
            _prune_one "${f}" "${dst_dir}"
        done < <(find "${src_cn}" -type f -print0 2>/dev/null)
    fi

    # Embeddings
    hdr "Pruning: Embeddings/"
    local src_emb="${LEGACY_COMMON}/Embeddings"
    if [[ -d "${src_emb}" ]]; then
        while IFS= read -r -d '' f; do
            local fname
            fname="$(basename "${f}")"
            case "${fname}" in *.bin|*.pt|*.safetensors) : ;; *) continue ;; esac
            _prune_one "${f}" "${SHARED}/image/Embeddings/A1111"
        done < <(find "${src_emb}" -maxdepth 1 -type f -print0 2>/dev/null)
    fi

    # AI_downloaded video dirs
    local -A dl_map=(
        ["diffusion_models"]="video/Models"
        ["loras"]="video/Lora"
        ["text_encoders"]="video/TextEncoders"
        ["vae"]="video/VAE"
    )
    for src_sub in diffusion_models loras text_encoders vae; do
        local src_dir dst_sub
        src_dir="${LEGACY_DOWNLOADED}/${src_sub}"
        dst_sub="${dl_map[${src_sub}]}"
        hdr "Pruning: AI_downloaded/${src_sub}/"
        [[ ! -d "${src_dir}" ]] && continue
        while IFS= read -r -d '' f; do
            local fname relpath dst_dir
            fname="$(basename "${f}")"
            _legacy_skip_file "${fname}" && continue
            relpath="${f#${src_dir}/}"
            relpath="$(dirname "${relpath}")"
            [[ "${relpath}" == "." ]] && dst_dir="${SHARED}/${dst_sub}" \
                                      || dst_dir="${SHARED}/${dst_sub}/${relpath}"
            _prune_one "${f}" "${dst_dir}"
        done < <(find "${src_dir}" -type f -print0 2>/dev/null)
    done

    # Remove now-empty legacy dirs (leaves the top-level dir itself — don't
    # remove the parent tree, only empty leaf dirs we created files in)
    for src_dir in \
        "${LEGACY_COMMON}/Stable-diffusion" \
        "${LEGACY_COMMON}/ControlNet" \
        "${LEGACY_COMMON}/Embeddings" \
        "${LEGACY_DOWNLOADED}/diffusion_models" \
        "${LEGACY_DOWNLOADED}/loras" \
        "${LEGACY_DOWNLOADED}/text_encoders" \
        "${LEGACY_DOWNLOADED}/vae"; do
        [[ -d "${src_dir}" ]] && \
            find "${src_dir}" -mindepth 1 -type d -empty -delete 2>/dev/null || true
    done

    # Remove sentinel — must re-verify before any further prune attempts
    rm -f "${LEGACY_VERIFY_SENTINEL}"

    echo
    echo -e "${BLD}╔══════════════════════════════════════════════════════════════╗${RST}"
    echo -e "${BLD}║                  PRUNE LEGACY — COMPLETE                     ║${RST}"
    echo -e "${BLD}╚══════════════════════════════════════════════════════════════╝${RST}"
    echo
    echo "  Deleted  : ${deleted}"
    echo "  Errors   : ${errors}"
    echo
    if [[ "${errors}" -gt 0 ]]; then
        echo -e "  ${YLW}Some files were not deleted — review warnings above.${RST}"
    else
        echo -e "  ${GRN}Legacy source files removed. Shared tree is the sole copy.${RST}"
    fi
    echo
}

# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
acquire_lock

echo
echo -e "${BLD}ai_migrate_resources.sh${RST} — Jethro AI stack resource manager"
echo "Mode: ${MODE}"
echo

case "${MODE}" in

    # -----------------------------------------------------------------------
    verify)
        run_verify
        ;;

    # -----------------------------------------------------------------------
    scan)
        hdr "Shared tree check"
        ensure_shared_tree

        hdr "Symlink check"
        wire_symlinks

        hdr "Output relocation check"
        migrate_old_outputs

        scan_configs
        scan_for_mergeable

        print_scan_report
        ;;

    # -----------------------------------------------------------------------
    migrate)
        # 1. Scan first — collect what needs doing
        hdr "Pre-migration scan..."
        MODE="scan"
        ensure_shared_tree
        wire_symlinks
        migrate_old_outputs
        scan_configs
        scan_for_mergeable
        MODE="migrate"

        # 2. Check for blockers
        if [[ "${#BLOCKERS[@]}" -gt 0 ]]; then
            echo
            echo -e "${RED}Migration cannot proceed — blockers found:${RST}"
            for b in "${BLOCKERS[@]}"; do
                echo "  🚫  ${b}"
            done
            echo
            echo "Resolve the above issues and re-run."
            exit 1
        fi

        # 3. Check if anything actually needs doing
        local total_changes=$(( ${#WOULD_CREATE[@]} + ${#WOULD_MOVE[@]} + ${#WOULD_SYMLINK[@]} ))
        if [[ "${total_changes}" -eq 0 ]]; then
            echo
            ok "Everything is already correct — nothing to do."
            echo
            exit 0
        fi

        # 4. Show scan report
        print_scan_report

        # 5. Check for open files in source trees we'll be moving
        check_open_files \
            "${OLD_A1111_OUTPUTS}" \
            "${OLD_WAN2GP_OUTPUTS}" \
            "${OLD_FPS_OUTPUTS}" \
            "${COMFY_DIR}"

        # 6. Prompt user
        prompt_user

        # 7. Act
        hdr "Creating shared tree..."
        ensure_shared_tree

        hdr "Migrating existing outputs..."
        migrate_old_outputs

        hdr "Wiring symlinks..."
        wire_symlinks

        # 8. Final report
        echo
        echo -e "${BLD}╔══════════════════════════════════════════════════════════════╗${RST}"
        echo -e "${BLD}║                    MIGRATION COMPLETE                        ║${RST}"
        echo -e "${BLD}╚══════════════════════════════════════════════════════════════╝${RST}"

        if [[ "${#FAILURES[@]}" -gt 0 ]]; then
            echo
            echo -e "  ${YLW}Completed with warnings:${RST}"
            for f in "${FAILURES[@]}"; do
                echo "    ⚠️   ${f}"
            done
        else
            echo
            ok "All operations completed successfully."
        fi

        echo
        echo "  Run verify to confirm:"
        echo "    ai_migrate_resources.sh --verify"
        echo
        ;;

    # -----------------------------------------------------------------------
    hardlink-legacy)
        if [[ ! -d "${LEGACY_COMMON}" ]]; then
            echo -e "${RED}ERROR: Legacy common tree not found: ${LEGACY_COMMON}${RST}"
            exit 1
        fi
        if [[ ! -d "${LEGACY_DOWNLOADED}" ]]; then
            echo -e "${RED}ERROR: Legacy downloaded tree not found: ${LEGACY_DOWNLOADED}${RST}"
            exit 1
        fi
        do_hardlink_legacy
        ;;

    # -----------------------------------------------------------------------
    verify-legacy)
        do_verify_legacy
        ;;

    # -----------------------------------------------------------------------
    prune-legacy)
        do_prune_legacy
        ;;

esac
