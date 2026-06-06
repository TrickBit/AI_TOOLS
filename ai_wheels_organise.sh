#!/usr/bin/env bash
# =============================================================================
# ai_wheels_organise.sh  —  Sort localbuild/ wheel cache into ABI subdirs
# =============================================================================
# Moves ABI-specific wheels (cpXXX) into cp310/ cp311/ cp312/ cp313/ subdirs.
# Deletes pure-Python wheels (py3-none-any, none-manylinux) — pip gets those
# from PyPI fine. The cache exists for source builds and compiled wheels only.
#
# Safe to re-run — already-moved wheels are skipped.
#
# Usage:
#   ./ai_wheels_organise.sh [--dry-run]
# =============================================================================

set -euo pipefail

LOCALBUILD="/mnt/BACKUP_4.0_TB/AI_Collected_Wheels/localbuild"
DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

log()  { echo "$*"; }
run()  { if $DRY_RUN; then echo "  [dry] $*"; else "$@"; fi; }

[[ ! -d "${LOCALBUILD}" ]] && { echo "ERROR: ${LOCALBUILD} not found"; exit 1; }

cd "${LOCALBUILD}"

moved=0
deleted=0
skipped=0

for whl in *.whl; do
    [[ -f "${whl}" ]] || continue

    # Extract ABI tag — field 3 of dash-separated filename
    # e.g. sageattention-2.2.0+cu130-cp311-cp311-linux_x86_64.whl → cp311
    abi="$(echo "${whl}" | cut -d- -f3)"

    case "${abi}" in
        cp310|cp311|cp312|cp313)
            dest="${LOCALBUILD}/${abi}"
            if [[ -f "${dest}/${whl}" ]]; then
                log "  skip (exists): ${abi}/${whl}"
                (( skipped++ )) || true
            else
                log "  move → ${abi}/: ${whl}"
                run mkdir -p "${dest}"
                run mv "${whl}" "${dest}/"
                (( moved++ )) || true
            fi
            ;;
        py3|none)
            # Keep large nvidia CUDA runtime wheels — slow to re-download
            if [[ "${whl}" == nvidia_* ]]; then
                log "  keep (nvidia): ${whl}"
                (( skipped++ )) || true
            else
                # Pure Python — pip gets these from PyPI fine
                log "  delete (pure-py): ${whl}"
                run rm "${whl}"
                (( deleted++ )) || true
            fi
            ;;
        *)
            log "  UNKNOWN abi tag '${abi}' — leaving: ${whl}"
            ;;
    esac
done

echo ""
echo "Done: ${moved} moved, ${deleted} deleted, ${skipped} skipped"
$DRY_RUN && echo "(dry run — no changes made)"
