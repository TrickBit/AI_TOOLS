# ai_resourcelib/ai_resource_tree.py
"""
   ai_resource_tree.py
   Library file located in <script dir>/ai_resourcelib/

   Provides functions to build resource folder trees and hardlink AI asset files
   by resource category based on extracted metadata.

   used by:
   ai_collect_metadata.py
   ai_model_manager.py
   (possibly others later)

"""
from pathlib import Path
from typing import Dict, Optional, List
import os
import logging
from ai_resourcelib.generic import files_are_same_fast
from ai_resourcelib.metadata_structure import FOLDER_ABOUT, ABOUT_FILENAME, DIRECTORY_HINTS

# Internal: Resource category relative directory templates.
# These map to the canonical AI-Shared-Resources/ tree structure.
# %s is replaced with the base directory at runtime via dir_map().
#
# Checkpoints are split by file extension at link time:
#   .safetensors  → image/Checkpoints/safetensors/
#   .ckpt         → image/Checkpoints/ckpt/
#   other/unknown → image/Checkpoints/other/
# The orchestrator resolves the correct key before calling find_matching_target_dir().
#
_dir_map_templates = {
    # --- Image model components ---
    "checkpoint_safetensors":  "%s/image/Checkpoints/safetensors",
    "checkpoint_ckpt":         "%s/image/Checkpoints/ckpt",
    "checkpoint_other":        "%s/image/Checkpoints/other",
    "lora":                    "%s/image/Lora",
    "embedding":               "%s/image/Embeddings",
    "textual_inversion":       "%s/image/Embeddings",
    "controlnet":              "%s/image/ControlNet",
    "vae":                     "%s/image/VAE",
    "hypernetwork":            "%s/image/Hypernetworks",
    "upscaler":                "%s/image/Upscalers",
    # --- Video model components ---
    "lora_video":              "%s/video/Lora",
    "video_diffusion":         "%s/video/Models",
    "video_vae":               "%s/video/VAE",
    "text_encoder":            "%s/video/TextEncoders",
    "video_upscaler":          "%s/video/Upscalers",
    # --- Shared / cross-domain ---
    "llm":                     "%s/shared/LLM",
    "audio_tts":               "%s/shared/AudioSpeech",
    "audio_speech":            "%s/shared/AudioSpeech",
    "audio_separator":         "%s/shared/AudioSeparator",
    "detector":                "%s/shared/Detectors",
    "depth_estimator":         "%s/shared/DepthEstimators",
    "optical_flow":            "%s/shared/DepthEstimators",  # small, lives alongside depth
    # --- Fallback ---
    "review":           "%s/review/unknown_type",
    "suspect":          "%s/review/unknown_type",  # suspect goes to review for human triage
    "duplicate_name":   "%s/review/duplicate_name",
    "confirmed_duplicate": "%s/review/confirmed_duplicate",
}


def dir_map(base_directory: str) -> Dict[str, Path]:
    """
    Return a new dictionary mapping resource categories to absolute Path objects,
    resolved relative to the given base directory.

    Args:
        base_directory (str): The base directory path to inject.

    Returns:
        Dict[str, Path]: Mapping from resource category (lowercase keys)
                         to absolute Path objects.
    """
    return {key: Path(value % base_directory) for key, value in _dir_map_templates.items()}


def checkpoint_key_for_file(filepath: Path) -> str:
    """
    Return the correct _dir_map_templates key for a checkpoint file based on
    its extension. Checkpoints are stored in separate subdirs by format.

    Args:
        filepath (Path): Path to the checkpoint file.

    Returns:
        str: One of 'checkpoint_safetensors', 'checkpoint_ckpt', 'checkpoint_other'.
    """
    ext = filepath.suffix.lower()
    if ext == ".safetensors":
        return "checkpoint_safetensors"
    elif ext == ".ckpt":
        return "checkpoint_ckpt"
    else:
        return "checkpoint_other"


def apply_directory_hint(resource_type: str, filepath: Path) -> str:
    """
    If resource_type is 'unknown', attempt to improve the classification by
    checking the file's parent directory name against DIRECTORY_HINTS.

    Args:
        resource_type (str): Current classification result.
        filepath (Path): Path to the file being classified.

    Returns:
        str: Improved resource type if a hint matched, otherwise original type.
    """
    if resource_type != "unknown":
        return resource_type
    # Check parent chain, not just immediate parent
    for parent in filepath.parents:
        parent_lower = parent.name.lower()
        for hint_key, hint_type in DIRECTORY_HINTS.items():
            if hint_key in parent_lower:
                return hint_type
    return resource_type


def files_are_same(path1: Path, path2: Path) -> bool:
    """
    Determine if two files are effectively the same either by inode,
    sample read, or full SHA256 hash.

    Delegates to files_are_same_fast() in generic.py which applies the
    cheapest check first. Kept here for backward compatibility with callers
    that import from ai_resource_tree.

    Args:
        path1 (Path): First file path.
        path2 (Path): Second file path.

    Returns:
        bool: True if files are the same, False otherwise.
    """
    return files_are_same_fast(path1, path2)


def find_matching_target_dir(
    resource_type: str,
    target_dir_map: Dict[str, Path],
    default_dir_key: str = "review"
) -> Optional[Path]:
    """
    Find the best matching target directory Path for a given resource type.
    Matching is case-insensitive with exact first, then substring fallback.
    If no match, the default directory ('review') is returned if available.

    Args:
        resource_type (str): The resource type string (e.g., 'lora', 'embedding').
        target_dir_map (Dict[str, Path]): Mapping resource types → target Paths.
        default_dir_key (str): Resource type key used for unknown types fallback.

    Returns:
        Optional[Path]: The matching target directory Path if found, else None.
    """
    resource_type_lower = resource_type.lower()

    # Exact match
    for key, path in target_dir_map.items():
        if key == resource_type_lower:
            return path

    # Fuzzy substring match
    for key, path in target_dir_map.items():
        if resource_type_lower in key or key in resource_type_lower:
            return path

    # Fallback to default directory if available
    return target_dir_map.get(default_dir_key)


def insert_suffix_into_sidecar_name(filename: str, suffix: str) -> str:
    """
    Insert suffix before the main extension(s) in a sidecar file name.
    Handles multiple extensions like '.pt.meta.json'.

    Example: 'model.pt.meta.json' + '_1' -> 'model_1.pt.meta.json'

    Args:
        filename (str): Original sidecar filename.
        suffix (str): Suffix string (including underscore, e.g. '_1').

    Returns:
        str: Modified sidecar filename with suffix inserted.
    """
    if not suffix:
        return filename

    parts = filename.split('.')
    if len(parts) <= 1:
        # No extension at all
        return filename + suffix

    base = parts[0]
    rest = parts[1:]
    new_base = base + suffix
    return new_base + '.' + '.'.join(rest)


def _write_about_file(directory: Path, resource_type: str, log_info_func) -> None:
    """
    Write a _ABOUT_.txt file into a newly created resource directory.
    Content is looked up from FOLDER_ABOUT by resource_type key.
    Skips silently if no entry exists for that type.

    Args:
        directory (Path): The newly created directory.
        resource_type (str): Lowercase resource type key.
        log_info_func (callable): Logger for info messages.
    """
    content = FOLDER_ABOUT.get(resource_type)
    if not content:
        return
    about_path = directory / ABOUT_FILENAME
    try:
        about_path.write_text(content, encoding='utf-8')
        log_info_func(f"Written {ABOUT_FILENAME} in {directory}")
    except Exception as e:
        # Non-fatal — log and continue
        logging.warning(f"Could not write {ABOUT_FILENAME} in {directory}: {e}")


def build_resource_tree_and_link_files(
    file_to_type_map: Dict[Path, str],
    target_dir_map: Dict[str, Path],
    file_sidecars_map: Optional[Dict[Path, List[Path]]] = None,
    link_method: str = "hardlink",  # or "symlink"
    logger: Optional[logging.Logger] = None
) -> None:
    """
    Create resource tree directories and link files from original locations into them
    according to their resource types.

    Sidecar files are linked with the same rename suffix as their main files,
    preserving their association.

    Args:
        file_to_type_map (Dict[Path, str]): Map of main file paths to their resource types.
            Sidecar files should NOT be in this map; use file_sidecars_map instead.
        target_dir_map (Dict[str, Path]): Map of resource type keys (lowercase) to target Path directories.
        file_sidecars_map (Optional[Dict[Path, List[Path]]]): Optional map linking main files to their sidecar Paths.
        link_method (str): "hardlink" (default) or "symlink" — method of linking files.
        logger (Optional[logging.Logger]): Logger to send info/warning/error messages. If None, logging is silent.

    Notes:
        - Only creates directories for resource types present in files.
        - Duplicate/collision detection avoids overwriting different files.
        - Sidecars follow renaming of their main files to stay linked.
    """
    def _log_info(msg: str):
        if logger:
            logger.info(msg)

    def _log_warn(msg: str):
        if logger:
            logger.warning(msg)

    def _log_error(msg: str):
        if logger:
            logger.error(msg)

    created_dirs = set()  # type: set[Path]

    for main_file, resource_type in file_to_type_map.items():
        resource_type_lower = resource_type.lower()
        target_base_dir = find_matching_target_dir(resource_type_lower, target_dir_map)

        if target_base_dir is None:
            _log_warn(f"No matching directory for resource type '{resource_type}', skipping file: {main_file}")
            continue

        if target_base_dir not in created_dirs:
            try:
                target_base_dir.mkdir(parents=True, exist_ok=True)
                created_dirs.add(target_base_dir)
                _write_about_file(target_base_dir, resource_type_lower, _log_info)
            except Exception as e:
                _log_error(f"Failed to create directory {target_base_dir}: {e}")
                continue

        # Determine destination for the main file, handling collisions
        dest_path = target_base_dir / main_file.name

        if dest_path.exists():
            if files_are_same(main_file, dest_path):
                _log_info(f"File already linked or duplicate destination {dest_path}, skipping link.")
                # Still link sidecars if any with the same dest_path stem (no suffix)
                suffix = ""
                _link_sidecars_follow_suffix(
                    main_file,
                    suffix,
                    target_base_dir,
                    file_sidecars_map,
                    link_method,
                    _log_info,
                    _log_warn,
                    _log_error,
                )
                continue
            else:
                # Naming collision — add numeric suffix
                for i in range(1, 1000):
                    candidate = target_base_dir / f"{main_file.stem}_{i}{main_file.suffix}"
                    if not candidate.exists():
                        dest_path = candidate
                        suffix = f"_{i}"
                        _log_warn(f"Name collision for {main_file.name}, renaming to {dest_path.name}")
                        break
                else:
                    _log_error(f"Too many naming collisions for {main_file.name} in {target_base_dir}, skipping.")
                    continue
        else:
            suffix = ""

        # Link main file
        _link_file(main_file, dest_path, link_method, _log_info, _log_error)

        # Link sidecars using same suffix
        _link_sidecars_follow_suffix(
            main_file,
            suffix,
            target_base_dir,
            file_sidecars_map,
            link_method,
            _log_info,
            _log_warn,
            _log_error,
        )


def _link_file(
    src: Path,
    dest: Path,
    link_method: str,
    log_info_func,
    log_error_func,
) -> None:
    """
    Internal helper to link a file via hardlink or symlink with logging.

    Args:
        src (Path): Source file path.
        dest (Path): Destination path.
        link_method (str): "hardlink" or "symlink".
        log_info_func (callable): Logger for info messages.
        log_error_func (callable): Logger for errors.
    """
    try:
        if not src.exists():
            log_error_func(f"Source file does not exist, cannot link: {src}")
            return
        if dest.is_symlink():
            target = dest.resolve()
            if target.is_file():
                dest.unlink()
            else:
                log_error_func(f"Destination {dest} is a symlink but does not point to a file; skipping unlink to avoid data loss.")
                return
        elif dest.exists():
            log_error_func(f"Destination {dest} exists and is not a symlink; skipping link to avoid overwriting real file.")
            return

        if link_method == "symlink":
            dest.symlink_to(src.resolve())
            log_info_func(f"Symlinked {src} → {dest}")
        else:
            try:
                os.link(src.resolve(), dest)
                log_info_func(f"Hardlinked {src} → {dest}")
            except OSError as e:
                import errno as errno_mod
                if e.errno == errno_mod.EXDEV:
                    # Cross-device link — source and destination are on different filesystems.
                    # Fall back to symlink silently (this is expected behaviour).
                    dest.symlink_to(src.resolve())
                    log_info_func(f"Symlinked (cross-device fallback) {src} → {dest}")
                else:
                    raise
    except Exception as e:
        log_error_func(f"Failed to link {src} to {dest}: {e}")


def _link_sidecars_follow_suffix(
    main_file: Path,
    suffix: str,
    target_base_dir: Path,
    file_sidecars_map: Optional[Dict[Path, List[Path]]],
    link_method: str,
    log_info_func,
    log_warn_func,
    log_error_func,
) -> None:
    """
    Internal helper to link sidecar files associated with main_file applying the same suffix
    in their filenames as main file renaming.

    Args:
        main_file (Path): The main file path.
        suffix (str): Suffix to insert (including underscore), e.g., "_1" or empty string.
        target_base_dir (Path): Directory to link files into.
        file_sidecars_map (Optional[Dict[Path, List[Path]]]): Mapping main files to their sidecars.
        link_method (str): "hardlink" or "symlink".
        log_info_func, log_warn_func, log_error_func: Logging callables.
    """
    if not file_sidecars_map:
        return

    sidecars = file_sidecars_map.get(main_file, [])
    for sidecar_path in sidecars:
        new_name = insert_suffix_into_sidecar_name(sidecar_path.name, suffix)
        dest_sidecar_path = target_base_dir / new_name

        if dest_sidecar_path.exists():
            if files_are_same(sidecar_path, dest_sidecar_path):
                log_info_func(f"Sidecar file already linked: {dest_sidecar_path}, skipping.")
                continue
            else:
                # Collision handling for sidecars (rare, but use numbered suffixes)
                for i in range(1, 1000):
                    candidate_name = insert_suffix_into_sidecar_name(
                        sidecar_path.name,
                        f"{suffix}_{i}" if suffix else f"_{i}",
                    )
                    candidate_path = target_base_dir / candidate_name
                    if not candidate_path.exists():
                        dest_sidecar_path = candidate_path
                        log_warn_func(f"Name collision for sidecar {sidecar_path.name}. Renaming to {dest_sidecar_path.name}")
                        break
                else:
                    log_error_func(f"Too many collisions for sidecar {sidecar_path.name} in {target_base_dir}, skipping.")
                    continue

        _link_file(sidecar_path, dest_sidecar_path, link_method, log_info_func, log_error_func)
