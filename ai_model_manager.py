#!/usr/bin/env python3
# ai_model_manager.py
"""
   ai_model_manager.py
   Located at: ~/bin/scripts/ai_model_manager.py
   Launched via: ai_model_manager.sh (manages venv)

   Consolidates AI model files from app directories into a single canonical
   shared resource tree using hardlinks. No disk space is consumed beyond
   sidecar (.meta.json) files. Cross-device sources are copied and flagged.

   The tool stays within AI_BASE unless --src points elsewhere, in which
   case resources are consolidated but the external app is not managed.

   Usage:
       ai_model_manager.sh                               # show this help
       ai_model_manager.sh --consolidate --src PATH      # full run from explicit path (backs up shared tree)
       ai_model_manager.sh --consolidate --apps          # fast incremental apps-only (no backup)
       ai_model_manager.sh --consolidate --src SUBFOLDER # targeted run, verify-prune reported after
       ai_model_manager.sh --verify PATH                 # is this path safe to prune?
       ai_model_manager.sh --restore --app NAME          # restore hardlinks for app
       ai_model_manager.sh --restore --apps              # restore all known apps
       ai_model_manager.sh --status                      # report shared tree state
       ai_model_manager.sh --status --app NAME           # report one app
       ai_model_manager.sh --health                      # verify tree integrity
       ai_model_manager.sh --health --app NAME           # verify one app coverage
       ai_model_manager.sh [mode] --dry-run              # show what would happen

   Add --dry-run to any mode to see what would happen without doing it.

   used by:
   (standalone — called via ai_model_manager.sh)
"""

import argparse
import json
import logging
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
# Shared Python library — moved to pylib/ during project restructure
_PYLIB = Path(__file__).parent / "pylib"
if str(_PYLIB) not in sys.path:
    sys.path.insert(0, str(_PYLIB))

# ---------------------------------------------------------------------------
# Imports from ai_resourcelib
# ---------------------------------------------------------------------------
from ai_resourcelib.generic import files_are_same_fast, collapse_to_canonical, file_sha256, file_fingerprint
from ai_resourcelib.metadata_helpers import (
    extract_safetensors_metadata,
    extract_torch_checkpoint_metadata,
    extract_onnx_metadata,
)
from ai_resourcelib.metadata_structure import (
    classify_ai_resource,
    FILENAME_HINTS,
    DIRECTORY_HINTS,
)
from ai_resourcelib.ai_resource_tree import (
    dir_map,
    checkpoint_key_for_file,
    apply_directory_hint,
)

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------
VERSION = "0.5.0"

# =============================================================================
# Configuration — edit these if your tree moves
# =============================================================================
AI_BASE         = "/mnt/BACKUP_4.0_TB"
AI_APPS_ROOT    = f"{AI_BASE}/AI_Apps"           # first-level subdirs = apps
AI_SHARED_ROOT  = f"{AI_BASE}/AI-Shared-Resources"  # canonical model store
AI_PREV_ROOT    = f"{AI_BASE}/AI-Shared-Resources_previous"  # fixed backup name
AI_OUTPUTS_ROOT = f"{AI_BASE}/AI_Outputs"        # generated outputs (never scanned)
LOG_FILE        = f"{AI_BASE}/ai_model_manager.log"
SIDECAR_EXT     = ".meta.json"                   # existing classification sidecars
AMM_SIDECAR_EXT = ".amm.json"                    # ai_model_manager tracking sidecars
# =============================================================================

# ---------------------------------------------------------------------------
# Model file extensions we care about — everything else is skipped
# ---------------------------------------------------------------------------
MODEL_EXTENSIONS = {
    ".safetensors", ".ckpt", ".pt", ".pth", ".bin",
    ".gguf", ".ggml", ".onnx",
    # ".pb",
}

COMPANION_EXTENSIONS = {".txt", ".md", ".json"}

# ---------------------------------------------------------------------------
# Exclusion rules — directory names that are never scanned
# Edit this list to add new app-specific dirs that should be ignored.
# ---------------------------------------------------------------------------
EXCLUDED_DIR_NAMES = {
    # Generated output — not models
    "ai_outputs", "outputs", "output",
    # HuggingFace cache internals
    "blobs", "refs", "snapshots",
    # Python environments
    ".venv", "venv", "__pycache__",
    # Other common environments
    "miniconda", "miniconda3", "anaconda", "anaconda3",
    # Version control
    ".git",
    # ComfyUI code, not models
    "custom_nodes",
    # Wan2GP app-specific auxiliary dirs (not portable)
    "pose", "mask", "depth", "flow", "det_align",
    "pyannote", "scribble", "chinese-wav2vec2-base",
    "wav2vec", "roformer",
    # Training data and development — not portable models
    "ai_work", "ai_development",
    "hub",           # HuggingFace cache root
    # InvokeAI pipeline model dirs — UUID-named, component files not useful standalone
    "invokeai-models",
    # review/ subdirs — persistent audit dirs, never re-ingest
    "confirmed_duplicate", "unknown_type", "duplicate_name",
}

APP_EXCLUDED_DIRS = {
     "Wan2GP": {"models", "scripts", "plugins", "finetunes"},

}


# Excluded dir name prefixes (glob-style — matched with startswith)
EXCLUDED_DIR_PREFIXES = {
    "gemma-", "qwen", "t5_xxl", "umt5", "xlm-roberta",
    "models--",   # HuggingFace cache top-level dirs
}

# Paths that are never scanned regardless of dir name
EXCLUDED_PATH_FRAGMENTS = {
    AI_OUTPUTS_ROOT,
    AI_SHARED_ROOT,
    f"{AI_SHARED_ROOT}/huggingface",
    f"{AI_BASE}/.Trash*",
    f"{AI_BASE}/AI_Work",
    f"{AI_BASE}/AI_Development",
    f"{AI_BASE}/Pinokio",
    f"{AI_BASE}/ai_model_manager.log",   # just a file but tidy
    # f"{AI_BASE}/AI-Shared-Resources_20260528_1334",  # Temporarily ignore
}


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
def setup_logging(dry_run: bool = False) -> logging.Logger:
    """
    Configure root logger to write to both the log file and stdout.
    Dry-run mode prefixes every log line with [DRY-RUN].
    """
    logger = logging.getLogger("amm")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    fmt_prefix = "[DRY-RUN] " if dry_run else ""
    formatter = logging.Formatter(
        f"%(asctime)s  {fmt_prefix}%(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File handler — always full detail
    try:
        fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    except Exception as e:
        print(f"WARNING: could not open log file {LOG_FILE}: {e}", file=sys.stderr)

    # Console handler — INFO and above
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    return logger


# ---------------------------------------------------------------------------
# Usage / argument parsing
# ---------------------------------------------------------------------------
def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai_model_manager",
        description=(
            "Consolidate AI model files into a canonical shared resource tree.\n"
            "No args — show this help and exit."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Consolidation modes:
  --consolidate --src PATH     Full run from PATH. Backs up shared tree first.
                               Use AI_BASE for a complete drive sweep.
  --consolidate --apps         Fast incremental — known apps only, no backup.
                               Use for routine maintenance after app model downloads.
  --consolidate --src SUBDIR   Targeted run on one subfolder, no backup.
                               Reports whether SUBDIR is safe to prune after.

Examples:
  ai_model_manager.sh --consolidate --src /mnt/BACKUP_4.0_TB               # full drive sweep
  ai_model_manager.sh --consolidate --src /mnt/BACKUP_4.0_TB/AI_Apps/ComfyUI  # one app
  ai_model_manager.sh --consolidate --src /mnt/BACKUP_4.0_TB/Remote_Discovered_Resources
  ai_model_manager.sh --consolidate --src '/mnt/BACKUP_3.0_TB/DEVELOPMENT/AI Tools'
  ai_model_manager.sh --consolidate --apps                                  # fast routine run
  ai_model_manager.sh --consolidate --apps --dry-run
  ai_model_manager.sh --verify /mnt/BACKUP_4.0_TB/AI_OLD_STUFF             # safe to prune?
  ai_model_manager.sh --restore --app ComfyUI
  ai_model_manager.sh --restore --apps
  ai_model_manager.sh --status
  ai_model_manager.sh --status --app Wan2GP
  ai_model_manager.sh --health
  ai_model_manager.sh --health --app ComfyUI
        """,
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--consolidate", action="store_true",
        help=(
            "Hardlink model files into shared tree. "
            "Use --apps for fast incremental run, or --src PATH for full/targeted run."
        ),
    )
    mode.add_argument(
        "--verify", metavar="PATH",
        help=(
            "Check whether PATH is safe to prune — every file in it has its "
            "inode accounted for in the shared tree."
        ),
    )
    mode.add_argument(
        "--restore", action="store_true",
        help="Recreate hardlinks for an app from sidecar records.",
    )
    mode.add_argument(
        "--status", action="store_true",
        help="Report state of shared tree and known apps.",
    )
    mode.add_argument(
        "--health", action="store_true",
        help=(
            "Verify shared tree integrity: check hardlink counts, sidecar "
            "known_locations, and that every app model file inode exists in "
            "the shared tree."
        ),
    )
    mode.add_argument(
        "--recover", action="store_true",
        help="Consolidate from previous backup tree then prune it if safe.",
    )
    mode.add_argument(
        "--prev-status", action="store_true",
        help="Show what files are in the previous backup tree vs current shared tree.",
    )
    mode.add_argument(
        "--prev-prune", action="store_true",
        help="Prune the previous backup tree if safe (safety check runs first).",
    )
    mode.add_argument(
        "--clean-sidecars", action="store_true",
        help="Remove stale known_locations from all .amm.json sidecars in the shared tree.",
    )

    parser.add_argument(
        "--apps", action="store_true",
        help=(
            "Incremental apps-only mode: scan all known apps under AI_APPS_ROOT. "
            "No backup of shared tree. Fast — use for routine maintenance. "
            "(--all is accepted as a synonym for backward compatibility.)"
        ),
    )
    # Keep --all as silent alias for --apps
    parser.add_argument("--all", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument(
        "--src", metavar="PATH",
        help=(
            "Source path for --consolidate. "
            "Full run (backs up shared tree) when PATH is AI_BASE or a whole device root. "
            "Targeted run (no backup, prune report after) for any subfolder."
        ),
    )
    parser.add_argument(
        "--app", metavar="NAME",
        help="App name (first-level subdir of AI_APPS_ROOT) for --restore, --status, --health.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would happen without making any changes.",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="Skip confirmation prompt and proceed automatically.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {VERSION}",
    )

    return parser


# ---------------------------------------------------------------------------
# Exclusion checks
# ---------------------------------------------------------------------------
def is_excluded_dir(dirpath: Path) -> bool:
    """
    Return True if dirpath should not be scanned.
    Checks:
      1. Path fragments (exact or prefix match, wildcard * suffix supported)
      2. Dir name exact match against EXCLUDED_DIR_NAMES
      3. Dir name prefix match against EXCLUDED_DIR_PREFIXES
    """
    dir_str = str(dirpath)
    for fragment in EXCLUDED_PATH_FRAGMENTS:
        if fragment.endswith("*"):
            if dir_str.startswith(fragment[:-1]):
                return True
        else:
            if dir_str == fragment or dir_str.startswith(fragment + "/"):
                return True

    name_lower = dirpath.name.lower()
    if name_lower in EXCLUDED_DIR_NAMES:
        return True

    for prefix in EXCLUDED_DIR_PREFIXES:
        if name_lower.startswith(prefix):
            return True

    return False


def is_excluded_file(filepath: Path) -> bool:
    """Return True if this file should be skipped."""
    # Skip sidecar files themselves
    if filepath.name.endswith(SIDECAR_EXT) or filepath.name.endswith(AMM_SIDECAR_EXT):
        return True
    # Skip non-model extensions
    if filepath.suffix.lower() not in MODEL_EXTENSIONS:
        return True
    return False


# ---------------------------------------------------------------------------
# Shared tree management
# ---------------------------------------------------------------------------
def previous_tree_path() -> Path:
    """Return the fixed path used for the previous-run backup tree."""
    return Path(AI_PREV_ROOT)


def check_previous_tree_guard(logger: logging.Logger) -> None:
    """
    Refuse to run consolidation if a previous backup tree still exists.
    This means the last run did not complete cleanly or auto-prune was blocked.
    Exits with code 1 and clear instructions.
    """
    prev = previous_tree_path()
    if prev.exists():
        logger.error(
            f"Previous shared tree backup exists: {prev.name}\n"
            f"  This means the last run did not complete cleanly or\n"
            f"  auto-prune was blocked.\n"
            f"\n"
            f"  Options:\n"
            f"    1. Check what is missing:\n"
            f"         ai_model_manager.sh --prev-status\n"
            f"    2. Recover missing files then prune:\n"
            f"         ai_model_manager.sh --recover\n"
            f"    3. Prune manually if you are sure it is safe:\n"
            f"         ai_model_manager.sh --prev-prune\n"
        )
        sys.exit(1)


def prepare_shared_tree(dry_run: bool, logger: logging.Logger) -> Optional[Path]:
    """
    Ensure the shared tree directory exists, ready to receive files.

    If AI_SHARED_ROOT already exists, rename it to the fixed backup name
    (AI_PREV_ROOT) so it becomes an additional consolidation source.
    The caller is responsible for scanning the renamed tree.

    The huggingface/ and review/confirmed_duplicate/ subdirectories are
    moved from the old tree into the new tree immediately after rename,
    so HF_HOME stays valid and audit logs persist across runs.

    Returns:
        Path to renamed old tree if one was moved, else None.
    """
    shared = Path(AI_SHARED_ROOT)
    prev   = previous_tree_path()
    old_tree = None

    if shared.exists():
        logger.info(f"Existing shared tree found — renaming to {prev.name}")
        if not dry_run:
            shared.rename(prev)
            old_tree = prev
        else:
            logger.info(f"[DRY-RUN] Would rename {shared} → {prev}")
            old_tree = prev  # report as if it happened

    if not dry_run:
        shared.mkdir(parents=True, exist_ok=True)
        logger.info(f"Shared tree ready at {shared}")

        # Move huggingface/ cache from old tree into new tree immediately so
        # HF_HOME stays valid and the cache is never scanned as a source.
        if old_tree and old_tree.exists():
            old_hf = old_tree / "huggingface"
            new_hf = shared / "huggingface"
            if old_hf.exists() and not new_hf.exists():
                old_hf.rename(new_hf)
                logger.info(f"Moved huggingface/ cache to new shared tree.")
            elif old_hf.exists() and new_hf.exists():
                logger.warning(
                    f"huggingface/ exists in both old and new tree — "
                    f"leaving old copy in {old_tree.name}/huggingface (manual merge needed)."
                )

            # Move confirmed_duplicate/ audit log — persistent across runs
            old_cd = old_tree / "review" / "confirmed_duplicate"
            new_cd = shared / "review" / "confirmed_duplicate"
            if old_cd.exists() and not new_cd.exists():
                new_cd.parent.mkdir(parents=True, exist_ok=True)
                old_cd.rename(new_cd)
                logger.info(f"Moved review/confirmed_duplicate/ audit log to new shared tree.")
            elif old_cd.exists() and new_cd.exists():
                logger.warning(
                    f"review/confirmed_duplicate/ exists in both old and new tree — "
                    f"leaving old copy in {old_tree.name} (manual merge needed)."
                )

    return old_tree


# ---------------------------------------------------------------------------
# AMM sidecar read / write
# ---------------------------------------------------------------------------
def amm_sidecar_path(model_file: Path) -> Path:
    """Return the .amm.json sidecar path for a given model file."""
    return model_file.parent / (model_file.name + AMM_SIDECAR_EXT)


def read_amm_sidecar(model_file: Path) -> dict:
    """
    Read the .amm.json sidecar for model_file.
    Returns an empty dict if the sidecar does not exist or is unreadable.
    """
    sidecar = amm_sidecar_path(model_file)
    if not sidecar.exists():
        return {}
    try:
        return json.loads(sidecar.read_text(encoding="utf-8"))
    except Exception:
        return {}

def write_amm_sidecar(
    model_file: Path,
    resource_type: str,
    known_location: str,
    dry_run: bool,
    logger: logging.Logger,
) -> None:
    """
    Write or update the .amm.json sidecar for a model file in the shared tree.

    Merges with any existing sidecar data so known_locations accumulate
    across consolidation runs rather than being overwritten.

    SHA256 is computed and stored on first write, then preserved on all
    subsequent updates — never recomputed if already present.
    Fingerprint (first+last 2KB hash) is also stored on first write —
    cheap to compute, useful for fast dedup checks.
    """
    import re as _re
    sidecar = amm_sidecar_path(model_file)
    data = read_amm_sidecar(model_file)

    now = datetime.now(timezone.utc).isoformat()
    stat = model_file.stat()

    amm = data.get("ai_model_manager", {})
    amm["resource_type"]  = resource_type
    amm["inode"]          = stat.st_ino
    amm["size_bytes"]     = stat.st_size
    amm["last_verified"]  = now

    if "first_seen" not in amm:
        amm["first_seen"] = now


    # Fingerprint and SHA256 — disabled pending relink-after-rebuild fix
    # Will rehash everything on every run until inode update is implemented
    # Fingerprint — cheap start+end sample hash, computed once if missing.
    # Fast enough to not matter; useful for remote dedup index.
    if "fingerprint" not in amm:
        fp = file_fingerprint(model_file)
        if fp:
            amm["fingerprint"] = fp
            amm["fingerprint_size"] = 2048

    # SHA256 — compute once on first write, preserve forever after.
    # Skipped if already stored — avoids re-hashing large model files on
    # every subsequent consolidation run.
    if "sha256" not in amm:
        sha = file_sha256(model_file)
        if sha:
            amm["sha256"] = sha
            # If filename carries a SHA8 collision suffix, verify it matches.
            # A mismatch means something renamed the file incorrectly.
            m = _re.search(r'_([0-9a-f]{8})(\.\w+)$', model_file.name)
            if m and not sha.startswith(m.group(1)):
                logger.warning(
                    f"SHA8 mismatch — filename suffix does not match actual hash: "
                    f"{model_file.name} (got {sha[:8]})"
                )

    # Accumulate known locations — deduplicated, stale paths removed
    locations = amm.get("known_locations", [])
    locations = [loc for loc in locations if Path(loc).exists()]
    if known_location not in locations:
        locations.append(known_location)
    amm["known_locations"] = locations

    data["ai_model_manager"] = amm

    if dry_run:
        logger.debug(f"[DRY-RUN] Would write sidecar {sidecar.name}")
        return

    try:
        sidecar.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"Could not write sidecar {sidecar}: {e}")

# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------
def classify_file(filepath: Path, logger: logging.Logger) -> str:
    """
    Classify a model file, returning a resource_type string.
    Precedence:
      1. Existing .amm.json sidecar (fast path)
      2. Existing .meta.json sidecar (from ai_collect_metadata legacy runs)
      3. Binary header read + classification rules
      4. FILENAME_HINTS
      5. DIRECTORY_HINTS
      6. Fallback → 'review'
    """
    def _vae_size_check(rt: str, fp: Path) -> str:
        """
        Sanity check — real VAEs are never larger than 1.5 GB.
        Legacy sidecars sometimes misclassified large checkpoints as vae.
        Demote to checkpoint if the size doesn't match.
        """
        if rt != "vae":
            return rt
        try:
            if fp.stat().st_size > 1_500_000_000:
                logger.debug(
                    f"Sidecar says vae but file is "
                    f"{fp.stat().st_size // (1024**2)} MB "
                    f"— reclassifying as checkpoint: {fp.name}"
                )
                return "checkpoint"
        except OSError:
            pass
        return rt

    # 1. AMM sidecar fast path
    amm = read_amm_sidecar(filepath)
    if amm.get("ai_model_manager", {}).get("resource_type"):
        rt = amm["ai_model_manager"]["resource_type"]
        if rt not in ("unknown", "unset", "review"):
            rt = _vae_size_check(rt, filepath)
            logger.debug(f"Classified via AMM sidecar: {filepath.name} → {rt}")
            return rt

    # 2. Legacy .meta.json sidecar fast path
    legacy_sidecar = filepath.parent / (filepath.name + SIDECAR_EXT)
    if legacy_sidecar.exists():
        try:
            legacy = json.loads(legacy_sidecar.read_text(encoding="utf-8"))
            rt = (
                legacy
                .get("ai_resource_identity", {})
                .get("resource_type", "")
            )
            if rt and rt not in ("unknown", "unset", "review"):
                rt = _vae_size_check(rt, filepath)
                logger.debug(f"Classified via legacy sidecar: {filepath.name} → {rt}")
                return rt
        except Exception:
            pass

    # 3. Header classification
    ext = filepath.suffix.lower()
    embedded = {}
    try:
        if ext == ".safetensors":
            embedded["safetensors"] = extract_safetensors_metadata(filepath)
        elif ext in (".pt", ".pth", ".ckpt", ".bin"):
            embedded["torch"] = extract_torch_checkpoint_metadata(filepath)
        elif ext == ".onnx":
            embedded["onnx"] = extract_onnx_metadata(filepath)
    except Exception as e:
        logger.debug(f"Header extraction failed for {filepath.name}: {e}")

    if embedded:
        result = classify_ai_resource(embedded, filepath)
        rt = result.get("resource_type", "unknown")
        if rt and rt not in ("unknown",):
            rt = _vae_size_check(rt, filepath)
            logger.debug(f"Classified via header: {filepath.name} → {rt}")
            return rt

    # 4. Filename hints
    name_lower = filepath.stem.lower()
    for hint, hint_type in FILENAME_HINTS.items():
        if hint in name_lower:
            logger.debug(f"Classified via filename hint '{hint}': {filepath.name} → {hint_type}")
            return hint_type

    # 5. Directory hints
    rt = apply_directory_hint("unknown", filepath)
    if rt != "unknown":
        logger.debug(f"Classified via directory hint: {filepath.name} → {rt}")
        return rt

    # 6. Fallback
    logger.debug(f"Could not classify {filepath.name} — sending to review/")
    return "review"

def resolve_resource_type_to_dir_key(resource_type: str, filepath: Path) -> str:
    """
    Convert a resource_type string to the correct _dir_map_templates key.
    Handles the checkpoint extension split.
    """
    if resource_type == "checkpoint":
        return checkpoint_key_for_file(filepath)
    return resource_type


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------
def scan_directory(
    src: Path,
    logger: logging.Logger,
    app_name: Optional[str] = None,
) -> list[tuple[Path, str]]:
    """
    Walk src, skipping excluded dirs and non-model files.
    Does NOT follow symlinks.

    app_name: if provided, per-app exclusions from APP_EXCLUDED_DIRS are
              added to the global exclusion set for this scan only.

    Returns:
        List of (filepath, resource_type) tuples.
    """
    results = []
    skipped_dirs = []
    extra_exclusions = APP_EXCLUDED_DIRS.get(app_name, set()) if app_name else set()
    files_checked = 0
    PROGRESS_INTERVAL = 500

    for dirpath_str, dirnames, filenames in os.walk(src, followlinks=False):
        dirpath = Path(dirpath_str)

        # Prune excluded dirs in-place so os.walk doesn't descend into them
        pruned = []
        for d in dirnames:
            child = dirpath / d
            if is_excluded_dir(child) or d in extra_exclusions:
                skipped_dirs.append(child)
            else:
                pruned.append(d)
        dirnames[:] = pruned

        for filename in filenames:
            filepath = dirpath / filename
            files_checked += 1
            if files_checked % PROGRESS_INTERVAL == 0:
                print(
                    f"  ... {files_checked} files checked, "
                    f"{len(results)} model files found so far - working ...",
                    flush=True
                )
            if is_excluded_file(filepath):
                continue
            resource_type = classify_file(filepath, logger)
            results.append((filepath, resource_type))

    if skipped_dirs:
        logger.debug(f"Skipped {len(skipped_dirs)} excluded directories under {src}")

    return results


# ---------------------------------------------------------------------------
# Companion file support
# ---------------------------------------------------------------------------
def find_companions(model_file: Path) -> list[Path]:
    """
    Return a list of companion files sitting alongside model_file.

    Companion files share the same stem as the model file (with or without
    an additional dot-separated extension) and carry a COMPANION_EXTENSIONS
    suffix. Examples:
        my_lora.safetensors  →  my_lora.txt  or  my_lora.safetensors.txt
        flux_dev.safetensors →  flux_dev.md  or  flux_dev.safetensors.json

    Only existing regular files are returned (broken symlinks excluded).
    """
    companions = []
    parent = model_file.parent
    stem   = model_file.stem        # e.g. "my_lora"
    full   = model_file.name        # e.g. "my_lora.safetensors"

    for ext in COMPANION_EXTENSIONS:
        # Pattern 1:  <stem><ext>   e.g. my_lora.txt
        c1 = parent / f"{stem}{ext}"
        if c1.exists() and c1.is_file():
            companions.append(c1)
        # Pattern 2:  <full><ext>   e.g. my_lora.safetensors.txt
        c2 = parent / f"{full}{ext}"
        if c2.exists() and c2.is_file():
            companions.append(c2)

    return companions


def link_companion(
    companion: Path,
    target_dir: Path,
    model_dest_name: str,
    dry_run: bool,
    logger: logging.Logger,
) -> None:
    """
    Hardlink (or symlink cross-device) a companion file into target_dir.

    The destination filename is derived from model_dest_name so it stays
    aligned if the model was given a collision-suffix during linking.
    E.g. if model landed as my_lora_2.safetensors, companion lands as
    my_lora_2.safetensors.txt (or my_lora_2.txt for stem-only companions).

    companion:       original companion Path
    model_dest_name: final name chosen for the model in target_dir (may
                     differ from model_file.name due to collision renaming)
    """
    # Work out the companion's own suffix relative to the original model name
    # so we can reconstruct it against the (possibly renamed) model dest name.
    # companion.name is one of: <stem><cext> or <stem><mext><cext>
    # We strip the companion extension, then check if what remains is the
    # model stem or full model name, and rebuild from model_dest_name.
    cext = companion.suffix                     # e.g. ".txt"
    model_dest_stem = Path(model_dest_name).stem   # e.g. "my_lora_2"
    model_dest_full = model_dest_name              # e.g. "my_lora_2.safetensors"

    # Reconstruct dest name: if companion was <stem><mext><cext> use full model
    # name as base; if it was just <stem><cext> use stem only.
    model_full_no_cext = Path(companion.name[: -len(cext)])
    if model_full_no_cext.suffix:
        dest_cname = f"{model_dest_full}{cext}"
    else:
        dest_cname = f"{model_dest_stem}{cext}"

    dest = target_dir / dest_cname
    if dest.exists():
        logger.debug(f"Companion already present: {dest.name}")
        return

    if dry_run:
        logger.debug(f"[DRY-RUN] Would link companion {companion.name} → {dest.name}")
        return

    try:
        src_resolved = companion.resolve()
        if src_resolved.stat().st_dev == dest.parent.stat().st_dev:
            os.link(src_resolved, dest)
        else:
            shutil.copy2(src_resolved, dest)
            logger.info(f"Companion copied (cross-device): {dest.name}")
        logger.debug(f"Companion linked: {companion.name} → {dest.name}")
    except Exception as e:
        logger.warning(f"Could not link companion {companion.name}: {e}")


# ---------------------------------------------------------------------------
# Consolidate
# ---------------------------------------------------------------------------
def consolidate_src(
    src: Path,
    shared: Path,
    dry_run: bool,
    logger: logging.Logger,
) -> dict:
    """
    Scan src, link model files into the shared tree.

    Returns a summary dict with counts.
    """
    external = not str(src).startswith(AI_BASE)
    if external:
        logger.info(
            f"Source {src} is outside managed tree ({AI_BASE}). "
            "Resources will be consolidated but app will not be managed."
        )

    # Derive app name if src is a direct child of AI_APPS_ROOT
    app_name = src.name if str(src.parent) == AI_APPS_ROOT else None
    if app_name:
        logger.info(f"Scanning app: {app_name} ({src})")
    else:
        logger.info(f"Scanning {src} ...")

    found = scan_directory(src, logger, app_name=app_name)
    logger.info(f"Found {len(found)} model files in {src}")

    target_map = dir_map(str(shared))

    counts = {
        "found": len(found),
        "linked": 0,
        "already_linked": 0,
        "review": 0,
        "errors": 0,
    }

    for filepath, resource_type in found:
        # Skip broken symlinks early — before any collision or link logic
        if filepath.is_symlink() and not filepath.exists():
            logger.warning(f"Broken symlink (skipped): {filepath}")
            counts["errors"] += 1
            continue

        dir_key = resolve_resource_type_to_dir_key(resource_type, filepath)
        target_dir = target_map.get(dir_key) or target_map.get("review")

        if target_dir is None:
            logger.error(f"No target dir for key '{dir_key}', skipping {filepath.name}")
            counts["errors"] += 1
            continue

        dest = target_dir / filepath.name

        # Handle name collisions
        if dest.exists():
            # Check inode first — same inode means already hardlinked
            try:
                same_inode = os.path.samefile(filepath, dest)
            except OSError:
                same_inode = False

            if same_inode:
                logger.info(f"Already in tree — same inode (skipped): {filepath.name}")
                counts["already_linked"] += 1
                if not dry_run:
                    src_is_prev = str(filepath).startswith(AI_PREV_ROOT)
                    location_to_record = str(dest) if src_is_prev else str(filepath)
                    write_amm_sidecar(
                        dest, resource_type, location_to_record, dry_run, logger
                    )
                continue

            if files_are_same_fast(filepath, dest, use_sha256_fallback=True):
                # Same content, different inode — collapse src onto canonical dest.
                confirmed_dup_dir = shared / "review" / "confirmed_duplicate"
                collapsed = collapse_to_canonical(
                    src=filepath,
                    canonical=dest,
                    confirmed_dup_dir=confirmed_dup_dir,
                    dry_run=dry_run,
                    logger=logger,
                )
                if collapsed:
                    counts["already_linked"] += 1
                    src_is_prev = str(filepath).startswith(AI_PREV_ROOT)
                    location_to_record = str(dest) if src_is_prev else str(filepath)
                    write_amm_sidecar(dest, resource_type, location_to_record, dry_run, logger)
                    continue
                # SHA256 mismatch — fast check was wrong, fall through to duplicate_name

            else:
                # Genuinely different file, same name — file with SHA8 suffix
                # in the correct type dir and hardlink back to source location.
                sha = file_sha256(filepath)
                if sha is None:
                    logger.warning(f"Could not hash {filepath.name} — skipping collision")
                    counts["errors"] += 1
                    continue
                sha8 = sha[:8]
                stem   = filepath.stem
                suffix = filepath.suffix
                sha_name = f"{stem}_{sha8}{suffix}"
                sha_dest = target_dir / sha_name

                try:
                    src_mb  = filepath.stat().st_size // (1024 ** 2)
                    dest_mb = dest.stat().st_size    // (1024 ** 2)
                    logger.warning(
                        f"Name collision — different file: {filepath.name} "
                        f"(src {src_mb} MB  vs  dest {dest_mb} MB) "
                        f"— filing as {sha_name}"
                    )
                except OSError:
                    logger.warning(f"Name collision — different file: {filepath.name} — filing as {sha_name}")

                if sha_dest.exists():
                    # Same SHA8 already in tree — same content, different inode
                    if files_are_same_fast(filepath, sha_dest):
                        logger.info(f"Already in tree via SHA8 (skipped): {sha_name}")
                        counts["already_linked"] += 1
                        # Still hardlink source location to canonical sha_dest
                        if not dry_run and filepath != sha_dest:
                            try:
                                filepath.unlink()
                                os.link(sha_dest, filepath)
                                logger.info(f"Source relinked to canonical: {filepath.name}")
                            except Exception as e:
                                logger.warning(f"Could not relink source {filepath}: {e}")
                        continue
                    else:
                        logger.error(f"SHA8 collision (different content) for {sha_name} — skipping.")
                        counts["errors"] += 1
                        continue

                # File sha_dest into correct type dir, then relink source
                dest = sha_dest
                resource_type = f"sha8_variant:{resource_type}"

        if resource_type == "review":
            counts["review"] += 1
        else:
            counts["linked"] += 1

        if dry_run:
            try:
                rel_src = filepath.relative_to(AI_BASE)
            except ValueError:
                rel_src = filepath
            logger.info(f"[DRY-RUN] Would link {rel_src} → {target_dir.relative_to(shared)}/")
            continue

        # Create target dir if needed
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"Could not create {target_dir}: {e}")
            counts["errors"] += 1
            continue

        # Hardlink same-device; copy cross-device (no symlinks ever)
        # If dest already exists with same content but different inode, unlink
        # it first so all copies collapse to one inode.
        try:
            src_resolved = filepath.resolve()
            if not src_resolved.exists():
                logger.warning(f"Symlink target missing, skipping: {filepath}")
                counts["errors"] += 1
                continue
            dest_device = dest.parent.stat().st_dev
            src_device  = src_resolved.stat().st_dev

            if dest.exists():
                dest.unlink()
            if src_device == dest_device:
                os.link(src_resolved, dest)
                logger.info(
                    f"Hardlinked {filepath.name} → "
                    f"{target_dir.relative_to(shared)}/"
                )
            else:
                shutil.copy2(src_resolved, dest)
                logger.info(
                    f"Copied (cross-device) {filepath.name} → "
                    f"{target_dir.relative_to(shared)}/"
                )
            # Carry sidecar across — preserves sha256/fingerprint forever.
            # Hash is content-based so valid regardless of source device.
            # No sidecar = manually placed file; write_amm_sidecar() hashes it fresh.
            src_sidecar = amm_sidecar_path(filepath)
            dest_sidecar = amm_sidecar_path(dest)
            if src_sidecar.exists() and not dest_sidecar.exists():
                try:
                    if src_device == dest_device:
                        os.link(src_sidecar, dest_sidecar)
                    else:
                        shutil.copy2(src_sidecar, dest_sidecar)
                except Exception as e:
                    logger.warning(f"Could not carry sidecar for {filepath.name}: {e}")
        except Exception as e:
            logger.error(f"Link failed for {filepath.name}: {e}")
            counts["errors"] += 1
            continue

        src_is_prev = str(filepath).startswith(AI_PREV_ROOT)
        location_to_record = str(dest) if src_is_prev else str(filepath)
        write_amm_sidecar(dest, resource_type, location_to_record, dry_run, logger)

        # If this was a sha8_variant, relink the source location to the canonical dest
        if resource_type.startswith("sha8_variant:") and not dry_run:
            try:
                src_resolved = filepath.resolve()
                if src_resolved != dest.resolve():
                    filepath.unlink()
                    os.link(dest, filepath)
                    logger.info(f"Source relinked to canonical SHA8 copy: {filepath.name}")
            except Exception as e:
                logger.warning(f"Could not relink source {filepath}: {e}")

        # Link companion files (.txt / .md / .json) that sit alongside the model
        for companion in find_companions(filepath):
            link_companion(companion, target_dir, dest.name, dry_run, logger)

    return counts



def check_old_tree_safe(old_tree: Path, shared: Path, logger: logging.Logger) -> bool:
    """
    Verify that every model file in old_tree has a matching inode in shared.
    Logs any files not accounted for.

    Returns True if safe to prune, False otherwise.
    """
    unaccounted = []

    for dirpath_str, dirnames, filenames in os.walk(old_tree, followlinks=False):
        dirpath = Path(dirpath_str)
        dirnames[:] = [
            d for d in dirnames
            if not is_excluded_dir(dirpath / d)
        ]
        for filename in filenames:
            fp = dirpath / filename
            if is_excluded_file(fp):
                continue
            try:
                if fp.is_symlink() and not fp.exists():
                    logger.warning(f"Broken symlink in old tree (skipped): {fp}")
                    continue
                stat = fp.stat()
            except OSError:
                logger.warning(f"Unreadable in old tree (skipped): {fp}")
                continue
            inode = stat.st_ino
            # Search shared tree for matching inode (same device implied)
            found_in_shared = False
            for sdirpath_str, _, sfilenames in os.walk(shared, followlinks=False):
                for sfn in sfilenames:
                    sfp = Path(sdirpath_str) / sfn
                    try:
                        if sfp.stat().st_ino == inode:
                            found_in_shared = True
                            break
                    except OSError:
                        continue
                if found_in_shared:
                    break
            if not found_in_shared:
                unaccounted.append(fp)

    if unaccounted:
        logger.warning(
            f"OLD TREE NOT SAFE TO PRUNE — "
            f"{len(unaccounted)} file(s) not found in new shared tree:"
        )
        for fp in unaccounted:
            logger.warning(f"  {fp}")
        logger.warning(
            f"Re-run: ai_model_manager.sh --consolidate --src {old_tree}"
        )
        return False

    logger.info(
        f"Old tree {old_tree.name} is SAFE TO PRUNE — "
        f"all files accounted for in new shared tree."
    )
    logger.info(f"To remove:  rm -rf {old_tree}")
    return True


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------
def restore_app(
    app_name: str,
    shared: Path,
    dry_run: bool,
    logger: logging.Logger,
) -> dict:
    """
    Recreate hardlinks for app_name by reading .amm.json sidecars in the
    shared tree and relinking any file whose known_locations include a path
    under AI_APPS_ROOT/app_name.
    """
    app_root = Path(AI_APPS_ROOT) / app_name
    logger.info(f"Restoring hardlinks for app: {app_name} ({app_root})")

    counts = {"restored": 0, "already_present": 0, "errors": 0}

    for dirpath_str, _, filenames in os.walk(shared, followlinks=False):
        for filename in filenames:
            if not filename.endswith(AMM_SIDECAR_EXT):
                continue
            sidecar_path = Path(dirpath_str) / filename
            try:
                data = json.loads(sidecar_path.read_text(encoding="utf-8"))
            except Exception:
                continue

            amm = data.get("ai_model_manager", {})
            locations = amm.get("known_locations", [])

            for loc in locations:
                if not loc.startswith(str(app_root)):
                    continue

                # This file belonged to app_name at loc
                dest = Path(loc)
                model_file = sidecar_path.parent / filename[: -len(AMM_SIDECAR_EXT)]

                if not model_file.exists():
                    logger.error(f"Shared tree file missing: {model_file}")
                    counts["errors"] += 1
                    continue

                if dest.exists():
                    if files_are_same_fast(model_file, dest):
                        logger.debug(f"Already present: {dest}")
                        counts["already_present"] += 1
                    else:
                        logger.warning(
                            f"Destination exists but differs: {dest} — skipping."
                        )
                        counts["errors"] += 1
                    continue

                if dry_run:
                    logger.info(f"[DRY-RUN] Would restore {dest}")
                    counts["restored"] += 1
                    continue

                try:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    os.link(model_file.resolve(), dest)
                    logger.info(f"Restored {dest}")
                    counts["restored"] += 1
                except Exception as e:
                    logger.error(f"Could not restore {dest}: {e}")
                    counts["errors"] += 1

    return counts


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------
def show_status(app_name: Optional[str], shared: Path, logger: logging.Logger) -> None:
    """
    Report the state of the shared tree, and optionally one app's coverage.
    """
    if not shared.exists():
        logger.info("Shared tree does not exist yet.")
        return

    # Count files per subdir
    logger.info(f"Shared tree: {shared}")
    total_files = 0
    total_size  = 0

    for dirpath_str, dirnames, filenames in os.walk(shared, followlinks=False):
        dirpath = Path(dirpath_str)
        dirnames[:] = sorted(d for d in dirnames if not is_excluded_dir(dirpath / d))
        model_files = [f for f in filenames if not f.endswith(SIDECAR_EXT)
                       and not f.endswith(AMM_SIDECAR_EXT)
                       and Path(f).suffix.lower() in MODEL_EXTENSIONS]
        if model_files:
            rel = dirpath.relative_to(shared)
            # size = sum((dirpath / f).stat().st_size for f in model_files)
            size = 0
            for f in model_files:
                fp = dirpath / f
                try:
                    size += fp.stat().st_size
                except OSError:
                    logger.warning(f"Broken link (skipped): {fp}")
            total_files += len(model_files)
            total_size  += size
            logger.info(
                f"  {str(rel):<45}  {len(model_files):>5} files  "
                f"{size / (1024**3):>7.2f} GB"
            )

    logger.info(f"  {'TOTAL':<45}  {total_files:>5} files  {total_size / (1024**3):>7.2f} GB")

    # Apps summary
    apps_root = Path(AI_APPS_ROOT)
    if apps_root.exists():
        apps = sorted(p for p in apps_root.iterdir() if p.is_dir())
        if app_name:
            apps = [a for a in apps if a.name.lower() == app_name.lower()]

        logger.info("")
        logger.info("Known apps:")
        for app in apps:
            # Count how many shared tree sidecars reference this app
            ref_count = 0
            for _, _, fns in os.walk(shared, followlinks=False):
                for fn in fns:
                    if fn.endswith(AMM_SIDECAR_EXT):
                        pass  # counted below
            # Simpler: just report app dir existence and rough model count
            # model_count = sum(
            #     1 for _, _, fns in os.walk(app, followlinks=False)
            #     for fn in fns
            #     if Path(fn).suffix.lower() in MODEL_EXTENSIONS
            # )
            found = scan_directory(app, logger, app_name=app.name)
            model_count = len(found)
            logger.info(f"  {app.name:<30}  {model_count:>5} model files found")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
def run_health_check(
    app_name: Optional[str],
    shared: Path,
    logger: logging.Logger,
) -> bool:
    """
    Verify shared tree integrity across three dimensions:

    1. Orphaned files — model files in the shared tree with st_nlink == 1,
       meaning they have no hardlink in any app directory.  These are safe
       but suggest the app that used them has been removed.

    2. Stale sidecar locations — paths recorded in .amm.json known_locations
       that no longer exist on disk (app was reinstalled without --restore,
       or files were moved).

    3. App file coverage — every model file inode found under AI_APPS_ROOT
       (or the named app) exists in the shared tree.  Files that don't are
       "untracked" — consolidation hasn't seen them yet.

    If app_name is given, only that app is checked for dimension 3.

    Returns True if no issues were found, False otherwise.
    Exits with code 2 from main() when False.
    """
    if not shared.exists():
        logger.error(f"Shared tree not found at {shared} — run --consolidate first.")
        return False

    issues = 0

    # ------------------------------------------------------------------
    # 1. Orphaned shared-tree files (st_nlink == 1)
    # ------------------------------------------------------------------
    orphans = []
    for dirpath_str, dirnames, filenames in os.walk(shared, followlinks=False):
        dirpath = Path(dirpath_str)
        dirnames[:] = sorted(d for d in dirnames if not is_excluded_dir(dirpath / d))
        for fn in filenames:
            if is_excluded_file(dirpath / fn):
                continue
            fp = dirpath / fn
            try:
                if fp.stat().st_nlink == 1:
                    orphans.append(fp)
            except OSError:
                pass

    if orphans:
        logger.warning(
            f"HEALTH: {len(orphans)} file(s) in shared tree have no app hardlinks "
            f"(st_nlink == 1) — safe but unlinked:"
        )
        for fp in orphans:
            logger.warning(f"  {fp.relative_to(shared)}")
        issues += len(orphans)
    else:
        logger.info("HEALTH: All shared tree files have at least one app hardlink. ✓")

    # ------------------------------------------------------------------
    # 2. Stale sidecar known_locations
    # ------------------------------------------------------------------
    stale_total = 0
    for dirpath_str, _, filenames in os.walk(shared, followlinks=False):
        for fn in filenames:
            if not fn.endswith(AMM_SIDECAR_EXT):
                continue
            sidecar_fp = Path(dirpath_str) / fn
            try:
                data = json.loads(sidecar_fp.read_text(encoding="utf-8"))
            except Exception:
                continue
            locations = data.get("ai_model_manager", {}).get("known_locations", [])
            stale = [loc for loc in locations if not Path(loc).exists()]
            if stale:
                model_name = fn[: -len(AMM_SIDECAR_EXT)]
                for loc in stale:
                    logger.warning(f"HEALTH: Stale location for {model_name}: {loc}")
                stale_total += len(stale)

    if stale_total:
        issues += stale_total
    else:
        logger.info("HEALTH: All sidecar known_locations resolve to existing paths. ✓")

    # ------------------------------------------------------------------
    # 3. App file coverage — any model inode not in shared tree?
    # ------------------------------------------------------------------
    apps_root = Path(AI_APPS_ROOT)
    if not apps_root.exists():
        logger.warning(f"HEALTH: AI_APPS_ROOT not found ({apps_root}) — skipping app coverage check.")
    else:
        # Build shared tree inode set once
        shared_inodes: set[int] = set()
        for dirpath_str, _, filenames in os.walk(shared, followlinks=False):
            for fn in filenames:
                fp = Path(dirpath_str) / fn
                if is_excluded_file(fp):
                    continue
                try:
                    shared_inodes.add(fp.stat().st_ino)
                except OSError:
                    pass

        # Scan app dirs
        apps = sorted(p for p in apps_root.iterdir() if p.is_dir())
        if app_name:
            apps = [a for a in apps if a.name.lower() == app_name.lower()]

        untracked_total = 0
        for app in apps:
            untracked = []
            found = scan_directory(app, logger, app_name=app.name)
            for filepath, _ in found:
                try:
                    if filepath.stat().st_ino not in shared_inodes:
                        untracked.append(filepath)
                except OSError:
                    pass
            if untracked:
                logger.warning(
                    f"HEALTH: {app.name}: {len(untracked)} model file(s) not in shared tree:"
                )
                for fp in untracked:
                    logger.warning(f"  {fp}")
                untracked_total += len(untracked)
            else:
                logger.info(f"HEALTH: {app.name}: all model files accounted for in shared tree. ✓")

        if untracked_total:
            logger.warning(
                f"HEALTH: {untracked_total} untracked file(s) total — "
                f"run --consolidate to absorb them."
            )
            issues += untracked_total
        else:
            logger.info("HEALTH: App coverage complete — no untracked files found. ✓")

    # ------------------------------------------------------------------
    # 4. Stale numbered hardlinks within shared tree
    #    Files matching *_<number>.<ext> that share an inode with another
    #    file in the shared tree — leftover from old collision numbering.
    #    Auto-remove since they're just duplicate directory entries.
    # ------------------------------------------------------------------
    stale_numbered = []
    import re as _re
    numbered_pattern = _re.compile(r'^(.+)_\d+(\.\w+)$')
    # Build inode → paths map for shared tree
    inode_to_paths: dict[int, list[Path]] = {}
    for dirpath_str, _, filenames in os.walk(shared, followlinks=False):
        for fn in filenames:
            fp = Path(dirpath_str) / fn
            if is_excluded_file(fp):
                continue
            try:
                ino = fp.stat().st_ino
                inode_to_paths.setdefault(ino, []).append(fp)
            except OSError:
                pass
    for ino, paths in inode_to_paths.items():
        if len(paths) < 2:
            continue
        # Find paths with numbered suffix that share inode with a non-numbered path
        non_numbered = [p for p in paths if not numbered_pattern.match(p.stem)]
        numbered     = [p for p in paths if numbered_pattern.match(p.stem)]
        if non_numbered and numbered:
            stale_numbered.extend(numbered)

    if stale_numbered:
        logger.warning(
            f"HEALTH: {len(stale_numbered)} stale numbered hardlink(s) found "
            f"(same inode as canonical, leftover from old collision naming):"
        )
        for fp in stale_numbered:
            logger.warning(f"  {fp.relative_to(shared)}")
            try:
                fp.unlink()
                logger.info(f"  Removed stale numbered hardlink: {fp.name}")
            except Exception as e:
                logger.warning(f"  Could not remove {fp.name}: {e}")
        issues += len(stale_numbered)
    else:
        logger.info("HEALTH: No stale numbered hardlinks found. ✓")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    if issues:
        logger.warning(f"\nHEALTH CHECK COMPLETE — {issues} issue(s) found.")
        return False

    logger.info("\nHEALTH CHECK COMPLETE — no issues found. ✓")
    return True


# ---------------------------------------------------------------------------
# Sidecar cleanup
# ---------------------------------------------------------------------------
def clean_sidecars(shared: Path, dry_run: bool, logger: logging.Logger) -> None:
    """
    Walk the shared tree and remove stale paths from every .amm.json sidecar.
    A path is stale if it no longer exists on disk.
    """
    if not shared.exists():
        logger.error(f"Shared tree not found at {shared}")
        return

    cleaned = 0
    untouched = 0

    for dirpath_str, _, filenames in os.walk(shared, followlinks=False):
        for fn in filenames:
            if not fn.endswith(AMM_SIDECAR_EXT):
                continue
            sidecar = Path(dirpath_str) / fn
            try:
                data = json.loads(sidecar.read_text(encoding="utf-8"))
            except Exception:
                continue

            amm = data.get("ai_model_manager", {})
            locations = amm.get("known_locations", [])
            clean = [loc for loc in locations if Path(loc).exists()]

            if len(clean) == len(locations):
                untouched += 1
                continue

            removed = len(locations) - len(clean)
            amm["known_locations"] = clean
            data["ai_model_manager"] = amm
            logger.info(f"Cleaned {removed} stale location(s) from {fn}")
            cleaned += removed

            if not dry_run:
                try:
                    sidecar.write_text(
                        json.dumps(data, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
                except Exception as e:
                    logger.warning(f"Could not write sidecar {sidecar}: {e}")

    logger.info(
        f"Sidecar cleanup complete: "
        f"{cleaned} stale location(s) removed, "
        f"{untouched} sidecar(s) already clean."
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
def main() -> None:
    parser = build_arg_parser()

    # No args — show help and exit cleanly
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    # --all is a silent alias for --apps
    if args.all:
        args.apps = True

    # Must have a mode
    if not any([args.consolidate, args.verify, args.restore, args.status,
                args.health, args.recover, args.prev_status, args.prev_prune,
                args.clean_sidecars]):
        parser.print_help()
        sys.exit(0)

    logger = setup_logging(dry_run=args.dry_run)
    run_start = datetime.now(timezone.utc)

    logger.info(
        f"{'=' * 60}\n"
        f"ai_model_manager v{VERSION}  "
        f"{'[DRY-RUN] ' if args.dry_run else ''}"
        f"started {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )

    shared = Path(AI_SHARED_ROOT)

    # ------------------------------------------------------------------
    # CONSOLIDATE
    # ------------------------------------------------------------------
    if args.consolidate:
        if not args.apps and not args.src:
            logger.error("--consolidate requires --apps or --src PATH")
            sys.exit(1)
        if args.apps and args.src:
            logger.error("--apps and --src are mutually exclusive")
            sys.exit(1)

        # Determine run mode
        apps_only = args.apps
        src_path  = Path(args.src) if args.src else None

        # Full run: --src points at AI_BASE itself (whole drive sweep)
        # Targeted run: --src points at a subfolder
        is_full_run = (not apps_only) and src_path is not None and (
            str(src_path) == AI_BASE or str(src_path).rstrip("/") == AI_BASE.rstrip("/")
        )

        # Describe what we're about to do and ask for confirmation
        if apps_only:
            action_desc = (
                f"INCREMENTAL run — scan known apps under {AI_APPS_ROOT}\n"
                f"  Shared tree:  {AI_SHARED_ROOT} (updated in place, NO backup)"
            )
        elif is_full_run:
            action_desc = (
                f"FULL run — sweep entire {AI_BASE}\n"
                f"  Shared tree:  {AI_SHARED_ROOT}\n"
                f"  Backup first: {AI_PREV_ROOT}"
            )
        else:
            action_desc = (
                f"TARGETED run — source: {src_path}\n"
                f"  Shared tree:  {AI_SHARED_ROOT} (updated in place, NO backup)\n"
                f"  Prune report: will check if source is safe to delete after"
            )

        if args.dry_run:
            action_desc = "[DRY-RUN] " + action_desc

        print(f"\n{action_desc}\n")
        if not args.yes and not args.dry_run:
            reply = input("Proceed? [Enter to continue, any other key to cancel]: ").strip()
            if reply:
                logger.info("Cancelled by user.")
                sys.exit(0)

        # Full run only: refuse if _previous exists, then back up shared tree
        if is_full_run:
            check_previous_tree_guard(logger)

        sources = []

        if apps_only:
            apps_root = Path(AI_APPS_ROOT)
            if not apps_root.exists():
                logger.error(f"AI_APPS_ROOT not found: {apps_root}")
                sys.exit(1)
            sources = sorted(p for p in apps_root.iterdir() if p.is_dir())
            logger.info(f"Found {len(sources)} app(s) under {apps_root}")
            old_tree = None
        else:
            if not src_path.exists():
                logger.error(f"--src path does not exist: {src_path}")
                sys.exit(1)
            sources = [src_path]
            if is_full_run:
                old_tree = prepare_shared_tree(args.dry_run, logger)
                if old_tree and old_tree.exists():
                    sources.insert(0, old_tree)
                    logger.info(f"Added old shared tree as consolidation source: {old_tree.name}")
            else:
                old_tree = None
                # Ensure shared tree exists for targeted run
                if not args.dry_run:
                    shared.mkdir(parents=True, exist_ok=True)

        # Consolidate each source
        total = {"found": 0, "linked": 0, "already_linked": 0, "review": 0, "errors": 0}
        for src in sources:
            logger.info(f"--- Consolidating: {src} ---")
            counts = consolidate_src(src, shared, args.dry_run, logger)
            for k in total:
                total[k] += counts.get(k, 0)

        # Summary
        logger.info(
            f"\nConsolidation complete:\n"
            f"  Found:          {total['found']}\n"
            f"  Linked:         {total['linked']}\n"
            f"  Already linked: {total['already_linked']}\n"
            f"  Sent to review: {total['review']}\n"
            f"  Errors:         {total['errors']}"
        )

        # Full run: prune old tree if safe, then clean sidecars
        if is_full_run and old_tree and old_tree.exists() and not args.dry_run:
            logger.info(f"\nChecking old tree for prune safety ...")
            safe = check_old_tree_safe(old_tree, shared, logger)
            if safe:
                logger.info(f"Auto-pruning old tree: {old_tree.name} ...")
                shutil.rmtree(old_tree)
                logger.info(f"Old tree removed: {old_tree.name}")
                logger.info("Cleaning stale sidecar locations ...")
                clean_sidecars(shared, dry_run=False, logger=logger)

        # Targeted run: report whether source is safe to prune
        if not apps_only and not is_full_run and not args.dry_run:
            logger.info(f"\nChecking whether source is safe to prune ...")
            check_old_tree_safe(src_path, shared, logger)

    # ------------------------------------------------------------------
    # VERIFY
    # ------------------------------------------------------------------
    elif args.verify:
        verify_path = Path(args.verify)
        if not verify_path.exists():
            logger.error(f"--verify path does not exist: {verify_path}")
            sys.exit(1)
        if not shared.exists():
            logger.error(f"Shared tree not found at {shared} — run --consolidate first.")
            sys.exit(1)
        logger.info(f"Verifying: {verify_path}")
        safe = check_old_tree_safe(verify_path, shared, logger)
        sys.exit(0 if safe else 2)

    # ------------------------------------------------------------------
    # RESTORE
    # ------------------------------------------------------------------
    elif args.restore:
        if not args.apps and not args.app:
            logger.error("--restore requires --apps or --app NAME")
            sys.exit(1)

        if not shared.exists():
            logger.error(f"Shared tree not found at {shared} — run --consolidate first.")
            sys.exit(1)

        apps_to_restore = []
        if args.apps:
            apps_root = Path(AI_APPS_ROOT)
            apps_to_restore = sorted(p.name for p in apps_root.iterdir() if p.is_dir())
        if args.app:
            if args.app not in apps_to_restore:
                apps_to_restore.append(args.app)

        for app_name in apps_to_restore:
            counts = restore_app(app_name, shared, args.dry_run, logger)
            logger.info(
                f"Restore {app_name}: "
                f"restored={counts['restored']}  "
                f"already_present={counts['already_present']}  "
                f"errors={counts['errors']}"
            )

    # ------------------------------------------------------------------
    # STATUS
    # ------------------------------------------------------------------
    elif args.status:
        show_status(args.app, shared, logger)

    # ------------------------------------------------------------------
    # HEALTH
    # ------------------------------------------------------------------
    elif args.health:
        ok = run_health_check(args.app, shared, logger)
        if not ok:
            sys.exit(2)   # exit 2 = health issues found; caller can detect

    # ------------------------------------------------------------------
    # RECOVER
    # ------------------------------------------------------------------
    elif args.recover:
        prev = previous_tree_path()
        if not prev.exists():
            logger.info("No previous backup tree found — nothing to recover.")
        else:
            logger.info(f"Recovering from previous tree: {prev.name}")
            counts = consolidate_src(prev, shared, args.dry_run, logger)
            logger.info(
                f"Recovery complete: linked={counts['linked']}  "
                f"already_linked={counts['already_linked']}  "
                f"errors={counts['errors']}"
            )
            if not args.dry_run:
                logger.info("\nChecking previous tree for prune safety ...")
                safe = check_old_tree_safe(prev, shared, logger)
                if safe:
                    logger.info(f"Auto-pruning previous tree: {prev.name} ...")
                    shutil.rmtree(prev)
                    logger.info(f"Previous tree removed: {prev.name}")

    # ------------------------------------------------------------------
    # PREV-STATUS
    # ------------------------------------------------------------------
    elif args.prev_status:
        prev = previous_tree_path()
        if not prev.exists():
            logger.info("No previous backup tree found.")
        else:
            logger.info(f"Previous tree: {prev}")
            logger.info(f"Current tree:  {shared}")
            logger.info("\nChecking which files in previous tree are missing from current tree ...")
            check_old_tree_safe(prev, shared, logger)

# ------------------------------------------------------------------
    # PREV-PRUNE
    # ------------------------------------------------------------------
    elif args.prev_prune:
        prev = previous_tree_path()
        if not prev.exists():
            logger.info("No previous backup tree found — nothing to prune.")
        else:
            logger.info(f"Checking previous tree for prune safety ...")
            safe = check_old_tree_safe(prev, shared, logger)
            if safe:
                if not args.dry_run:
                    logger.info(f"Pruning previous tree: {prev.name} ...")
                    shutil.rmtree(prev)
                    logger.info(f"Previous tree removed: {prev.name}")
                    logger.info("Cleaning stale sidecar locations from pruned tree ...")
                    clean_sidecars(shared, dry_run=False, logger=logger)
                else:
                    logger.info(f"[DRY-RUN] Would remove: {prev}")
            else:
                logger.warning("Previous tree NOT pruned — run --recover first.")

    # ------------------------------------------------------------------
    # CLEAN-SIDECARS
    # ------------------------------------------------------------------
    elif args.clean_sidecars:
        clean_sidecars(shared, args.dry_run, logger)

    elapsed = datetime.now(timezone.utc) - run_start
    hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    elapsed_str = (
        f"{hours}h {minutes}m {seconds}s" if hours
        else f"{minutes}m {seconds}s" if minutes
        else f"{seconds}s"
    )
    logger.info(
        f"ai_model_manager finished "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  "
        f"(took {elapsed_str})\n"
        f"{'=' * 60}"
    )


if __name__ == "__main__":
    main()
