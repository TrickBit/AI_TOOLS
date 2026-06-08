#!/usr/bin/env python3
# =============================================================================
# ai_workflow_prep.py  —  Resolve and link models for a ComfyUI workflow
# =============================================================================
# Parses a ComfyUI workflow JSON, walks every node looking for model filenames,
# searches the shared model tree and ComfyUI model dirs, hardlinks found models
# into the correct ComfyUI directories, and patches the workflow with any
# substitute filenames (best VRAM-fit variants).
#
# Usage:
#   python3 ai_workflow_prep.py \
#     --workflow path/to/workflow.json \
#     --comfyui  /mnt/BACKUP_4.0_TB/AI_Apps/ComfyUI \
#     --shared   /mnt/BACKUP_4.0_TB/AI-Shared-Resources \
#     --vram     12
#
#   Optional:
#     --out      path/to/workflow_patched.json  (default: <workflow>_patched.json)
#     --map      path/to/ai_comfy_model_map.json
#     --yes      auto-accept symlink when hardlink fails (cross-filesystem)
#
# Standalone — no dependency on the AI_Tools stack.
# Requires: Python 3.9+, ai_comfy_model_map.py in the same directory.
# =============================================================================

import json
import os
import re
import sys
import argparse
import errno
import subprocess
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ai_comfy_model_map  # noqa: E402

MODEL_EXTENSIONS: frozenset[str] = frozenset(
    ai_comfy_model_map.MODEL_EXTENSIONS
)

# Known download URLs: filename → (url, shared_subdir).
# shared_subdir is relative to the --shared root (e.g. 'video/Models').
KNOWN_URLS: dict[str, tuple[str, str]] = {
    "Wan2_1_mocha-14B-preview_fp8_e4m3fn_scaled_KJ.safetensors": (
        "https://huggingface.co/Kijai/WanVideo_comfy_fp8_scaled/resolve/main/MoCha/"
        "Wan2_1_mocha-14B-preview_fp8_e4m3fn_scaled_KJ.safetensors",
        "video/Models",
    ),
    "umt5-xxl-enc-bf16.safetensors": (
        "https://huggingface.co/Kijai/WanVideo_comfy/resolve/main/umt5-xxl-enc-bf16.safetensors",
        "video/TextEncoders",
    ),
    "sam2.1_hiera_base_plus.safetensors": (
        "https://huggingface.co/Kijai/sam2-safetensors/resolve/main/sam2.1_hiera_base_plus.safetensors",
        "video/Models",
    ),
    "Wan2_1_VAE_bf16.safetensors": (
        "https://huggingface.co/Kijai/WanVideo_comfy/resolve/main/Wan2_1_VAE_bf16.safetensors",
        "video/VAE",
    ),
    "lightx2v_T2V_14B_cfg_step_distill_v2_lora_rank64_bf16_.safetensors": (
        "https://huggingface.co/Kijai/WanVideo_comfy/resolve/main/Lightx2v/"
        "lightx2v_T2V_14B_cfg_step_distill_v2_lora_rank64_bf16.safetensors",
        "video/LoRAs",
    ),
}


def _lookup_url(filename: str) -> tuple[str, str] | None:
    """Return (url, shared_subdir) for filename, or None if unknown."""
    return KNOWN_URLS.get(filename)


# Patterns stripped from file stems to identify the model family.
# Applied in order, repeatedly until stable.
_STEM_STRIP_RES = [
    re.compile(r'[-_]fp(8|16|32)$', re.IGNORECASE),
    re.compile(r'[-_]bf16$',         re.IGNORECASE),
    re.compile(r'[-_]q[0-9]+[_km]*[0-9]*$', re.IGNORECASE),  # q4_k, q5_k_m, q8_0 …
    re.compile(r'[-_]gguf$',          re.IGNORECASE),
]


# =============================================================================
# Model-map helpers
# =============================================================================

def load_or_build_map(
    map_path: Path, comfyui_path: Path
) -> dict:
    """Load existing model map or regenerate if missing / comfyui_path changed."""
    if map_path.exists():
        try:
            existing = json.loads(map_path.read_text())
            if existing.get("comfyui_path") == str(comfyui_path.resolve()):
                return existing
            print(
                f"  map: comfyui_path changed — regenerating {map_path}",
                file=sys.stderr,
            )
        except Exception:
            pass
    print(f"  map: building {map_path}", file=sys.stderr)
    return ai_comfy_model_map.build_map(comfyui_path, map_path)


# =============================================================================
# Workflow parsing — supports both UI and API JSON formats
# =============================================================================

def _model_basename(val: str) -> str:
    """Normalize backslashes to forward slashes and return the final path component."""
    return val.replace("\\", "/").split("/")[-1]


def _is_model_filename(val: Any) -> bool:
    if not isinstance(val, str):
        return False
    return Path(_model_basename(val)).suffix.lower() in MODEL_EXTENSIONS


def parse_workflow_refs(workflow: dict) -> list[dict]:
    """Return a list of model references found in the workflow.

    Each entry:
      {
        "node_id":    str,
        "node_type":  str,
        "location":   "widgets_values" | "inputs",
        "index":      int | str,   # list index (widgets) or input key (API)
        "filename":   str,
      }

    Handles both the ComfyUI UI format (nodes[].widgets_values) and the
    API prompt format ({node_id: {class_type:…, inputs:{…}}}).
    """
    refs: list[dict] = []

    # ---- UI format: workflow["nodes"] is a list ----
    if "nodes" in workflow and isinstance(workflow["nodes"], list):
        for node in workflow["nodes"]:
            node_id = str(node.get("id", ""))
            node_type = node.get("type", "")
            wv = node.get("widgets_values", [])
            for idx, val in enumerate(wv):
                if _is_model_filename(val):
                    refs.append({
                        "node_id":   node_id,
                        "node_type": node_type,
                        "location":  "widgets_values",
                        "index":     idx,
                        "filename":  _model_basename(val),
                    })
            # Some nodes (e.g. DownloadAndLoadSAM2Model) store the model name
            # in a named input rather than widgets_values.
            # In UI format node["inputs"] is a list of connection objects — skip it.
            _inputs = node.get("inputs")
            if isinstance(_inputs, dict):
                for key, val in _inputs.items():
                    if isinstance(val, str) and _is_model_filename(val):
                        refs.append({
                            "node_id":   node_id,
                            "node_type": node_type,
                            "location":  "inputs",
                            "index":     key,
                            "filename":  _model_basename(val),
                        })
        return refs

    # ---- API format: top-level keys are node IDs ----
    for node_id, node in workflow.items():
        if not isinstance(node, dict) or "class_type" not in node:
            continue
        node_type = node["class_type"]
        inputs = node.get("inputs", {})
        for key, val in inputs.items():
            if _is_model_filename(val):
                refs.append({
                    "node_id":   node_id,
                    "node_type": node_type,
                    "location":  "inputs",
                    "index":     key,
                    "filename":  _model_basename(val),
                })

    return refs


def patch_workflow(workflow: dict, patches: list[dict]) -> dict:
    """Apply filename patches to a workflow dict (mutates in place, returns it)."""
    # patches: list of {"node_id", "location", "index", "new_filename"}
    patch_map: dict[str, list[dict]] = {}
    for p in patches:
        patch_map.setdefault(p["node_id"], []).append(p)

    if "nodes" in workflow and isinstance(workflow["nodes"], list):
        for node in workflow["nodes"]:
            node_id = str(node.get("id", ""))
            for p in patch_map.get(node_id, []):
                if p["location"] == "inputs":
                    node.setdefault("inputs", {})[p["index"]] = p["new_filename"]
                else:
                    node["widgets_values"][p["index"]] = p["new_filename"]
    else:
        for node_id, node in workflow.items():
            if not isinstance(node, dict):
                continue
            for p in patch_map.get(node_id, []):
                node.setdefault("inputs", {})[p["index"]] = p["new_filename"]

    return workflow


# =============================================================================
# File search
# =============================================================================

def _walk_files(root: Path):
    """Yield all files under root recursively."""
    try:
        for entry in root.rglob("*"):
            if entry.is_file():
                yield entry
    except PermissionError:
        pass


def find_exact_in_dirs(filename: str, dirs: list[str]) -> Path | None:
    """Search a list of directories for an exact filename match (case-sensitive)."""
    for d in dirs:
        p = Path(d) / filename
        if p.exists():
            return p
    return None


def find_exact_in_shared(filename: str, shared_path: Path) -> Path | None:
    """Recursively search the shared model tree for an exact filename."""
    for f in _walk_files(shared_path):
        if f.name == filename:
            return f
    return None


# =============================================================================
# VRAM scoring and variant search
# =============================================================================

def stem_model_name(filename: str) -> str:
    """Strip quant/dtype suffix from a model filename stem."""
    stem = Path(filename).stem
    changed = True
    while changed:
        changed = False
        for pat in _STEM_STRIP_RES:
            new = pat.sub("", stem)
            if new != stem:
                stem = new
                changed = True
    return stem.lower()


def vram_score(filename: str, vram_gb: int) -> int:
    """Score a candidate model file for VRAM fit. Higher = better."""
    name = filename.lower()
    ext  = Path(filename).suffix.lower()
    is_gguf = ext == ".gguf"

    if vram_gb <= 12:
        if is_gguf and re.search(r'q[45]', name):    return 100
        if is_gguf and re.search(r'q6',    name):    return 90
        if is_gguf and re.search(r'q8',    name):    return 80
        if is_gguf:                                   return 70
        if "fp8"  in name:                            return 60
        if "bf16" in name or "fp16" in name:          return 30
        return 20

    elif vram_gb <= 16:
        if "fp8"  in name:                            return 100
        if is_gguf and re.search(r'q[678]', name):   return 90
        if is_gguf:                                   return 80
        if "bf16" in name:                            return 70
        if "fp16" in name:                            return 65
        if is_gguf and re.search(r'q[45]', name):    return 60
        return 20

    else:
        if "bf16" in name:                            return 100
        if "fp16" in name:                            return 90
        if "fp8"  in name:                            return 70
        if is_gguf and re.search(r'q[678]', name):   return 60
        if is_gguf:                                   return 50
        return 20


def find_best_variant(
    filename: str, shared_path: Path, vram_gb: int
) -> Path | None:
    """Search shared tree for best VRAM-fit variant of a model family."""
    target_stem = stem_model_name(filename)
    if not target_stem:
        return None

    candidates: list[tuple[int, Path]] = []
    for f in _walk_files(shared_path):
        if f.suffix.lower() not in MODEL_EXTENSIONS:
            continue
        if stem_model_name(f.name) == target_stem:
            candidates.append((vram_score(f.name, vram_gb), f))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


# =============================================================================
# Linking
# =============================================================================

def _try_hardlink(src: Path, dest: Path) -> tuple[bool, int, str]:
    try:
        os.link(str(src), str(dest))
        return True, 0, ""
    except OSError as e:
        return False, e.errno, str(e)


def _try_symlink(src: Path, dest: Path) -> tuple[bool, str]:
    try:
        dest.symlink_to(src)
        return True, ""
    except OSError as e:
        return False, str(e)


def link_model(
    src: Path,
    dest_dir: Path,
    *,
    auto_symlink: bool = False,
) -> str:
    """Hardlink src into dest_dir. Returns a short action string.

    auto_symlink: if True, use symlink on cross-filesystem without prompting.
    Returns one of: 'already_linked' | 'already_present' | 'hardlinked' |
                    'symlinked' | 'skipped' | 'error:<msg>'
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name

    if dest.exists():
        try:
            if dest.stat().st_ino == src.stat().st_ino:
                return "already_linked"
        except OSError:
            pass
        return "already_present"

    ok, eno, err = _try_hardlink(src, dest)
    if ok:
        return "hardlinked"

    if eno == errno.EXDEV:
        print(
            f"\n  Hardlink not possible (cross-filesystem).\n"
            f"  Source:      {src}\n"
            f"  Destination: {dest}\n"
            f"  ComfyUI may or may not follow symlinks depending on version/settings.",
            file=sys.stderr,
        )
        if auto_symlink:
            use_sym = True
        else:
            answer = input("  Use symlink instead? [y/N]: ").strip().lower()
            use_sym = answer == "y"

        if use_sym:
            ok2, err2 = _try_symlink(src, dest)
            return "symlinked" if ok2 else f"error:{err2}"
        return "skipped"

    return f"error:{err}"


# =============================================================================
# Main prep logic
# =============================================================================

def prep_workflow(
    workflow_path: Path,
    comfyui_path:  Path,
    shared_path:   Path,
    vram_gb:       int,
    out_path:      Path,
    map_path:      Path,
    auto_symlink:  bool = False,
    _rerun:        bool = False,
) -> None:
    workflow = json.loads(workflow_path.read_text())
    model_map = load_or_build_map(map_path, comfyui_path)

    node_cat:   dict[str, str]  = model_map.get("node_type_to_category", {})
    model_dirs: dict[str, list] = model_map.get("model_dirs", {})

    refs = parse_workflow_refs(workflow)
    if not refs:
        print("No model references found in workflow.")
        return

    # Deduplicate by (node_type, filename) so we only search once per unique pair.
    seen_files: dict[tuple[str, str], tuple[Path | None, str, str]] = {}
    # key: (category, filename)
    # value: (resolved_src_path | None, new_filename, action)

    patches: list[dict] = []

    report_exact:   list[str] = []
    report_variant: list[str] = []
    report_missing: list[str] = []
    missing_downloads: list[tuple[str, str]] = []  # (filename, category)

    for ref in refs:
        filename  = ref["filename"]
        node_type = ref["node_type"]
        category  = node_cat.get(node_type, "")
        comfy_dirs = model_dirs.get(category, [])
        cache_key  = (category, filename)

        if cache_key not in seen_files:
            # Step 1: already present in ComfyUI dirs?
            found_local = find_exact_in_dirs(filename, comfy_dirs)
            if found_local:
                seen_files[cache_key] = (found_local, filename, "already_present")

            else:
                # Step 2: exact match in shared tree?
                found_shared = find_exact_in_shared(filename, shared_path)
                if found_shared:
                    dest_dir = Path(comfy_dirs[0]) if comfy_dirs else None
                    if dest_dir:
                        action = link_model(found_shared, dest_dir, auto_symlink=auto_symlink)
                    else:
                        action = "no_dest_dir"
                    seen_files[cache_key] = (found_shared, filename, action)

                else:
                    # Step 3: best VRAM-fit variant?
                    variant = find_best_variant(filename, shared_path, vram_gb)
                    if variant:
                        dest_dir = Path(comfy_dirs[0]) if comfy_dirs else None
                        if dest_dir:
                            action = link_model(variant, dest_dir, auto_symlink=auto_symlink)
                        else:
                            action = "no_dest_dir"
                        seen_files[cache_key] = (variant, variant.name, action)
                    else:
                        seen_files[cache_key] = (None, filename, "missing")

        src, new_filename, action = seen_files[cache_key]

        # Patch the workflow if the filename changed
        if new_filename != filename and action not in ("missing", "skipped", "no_dest_dir"):
            patches.append({
                "node_id":     ref["node_id"],
                "location":    ref["location"],
                "index":       ref["index"],
                "new_filename": new_filename,
            })

        # Build report entries
        category_label = f"[{category}]" if category else "[unknown]"
        if action == "already_present" or action == "already_linked":
            report_exact.append(f"  {filename}  {category_label}  — already present")
        elif action in ("hardlinked", "symlinked"):
            link_type = action
            if new_filename != filename:
                dest_dir_str = str(Path(comfy_dirs[0])) if comfy_dirs else "?"
                report_variant.append(
                    f"  {filename}\n"
                    f"    → variant: {new_filename}\n"
                    f"    → {link_type} into {dest_dir_str}"
                )
            else:
                dest_dir_str = str(Path(comfy_dirs[0])) if comfy_dirs else "?"
                report_exact.append(
                    f"  {filename}  {category_label}  → {link_type} into {dest_dir_str}"
                )
        elif action == "skipped":
            report_missing.append(f"  {filename}  {category_label}  — cross-filesystem, symlink declined")
        elif action == "missing":
            report_missing.append(f"  {filename}  {category_label}  — not found, needs download")
            missing_downloads.append((filename, category))
        elif action == "no_dest_dir":
            report_missing.append(f"  {filename}  {category_label}  — unknown category, no dest dir")
        else:
            report_missing.append(f"  {filename}  {category_label}  — {action}")

    # Apply patches and write output
    if patches:
        patch_workflow(workflow, patches)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(workflow, indent=2) + "\n")

    # Print report
    print(f"\n=== Workflow prep: {workflow_path.name} ===\n")
    if report_exact:
        print("Found / linked:")
        print("\n".join(report_exact))
    if report_variant:
        print("\nBest variant substituted:")
        print("\n".join(report_variant))
    if report_missing:
        print("\nMissing (needs download or manual placement):")
        print("\n".join(report_missing))
    if missing_downloads and not _rerun:
        seen_dl: set[str] = set()
        dl_cmds: list[tuple[str, str, str]] = []   # (fname, dest_dir, url)
        cmd_lines: list[str] = []
        for fname, _cat in missing_downloads:
            if fname in seen_dl:
                continue
            seen_dl.add(fname)
            entry = _lookup_url(fname)
            if entry:
                url, subdir = entry
                dest_dir = str(shared_path / subdir)
                dl_cmds.append((fname, dest_dir, url))
                cmd_lines.append(f"  wget -O {str(Path(dest_dir) / fname)!r} {url!r}")
            else:
                cmd_lines.append(f"  # {fname} — URL unknown, find and download manually")
        print("\nDownload commands:")
        print("\n".join(cmd_lines))
        if dl_cmds:
            answer = input("\nDownload missing models now? [y/N]: ").strip().lower()
            if answer == "y":
                downloaded_any = False
                for fname, dest_dir, url in dl_cmds:
                    print(f"\n  → {fname}")
                    Path(dest_dir).mkdir(parents=True, exist_ok=True)
                    result = subprocess.run(
                        ["wget", "-O", str(Path(dest_dir) / fname), url],
                        check=False,
                    )
                    if result.returncode == 0:
                        downloaded_any = True
                    else:
                        print(f"  wget failed (exit {result.returncode}) — skipping", file=sys.stderr)
                if downloaded_any:
                    print("\nRe-running link/patch step after downloads...\n")
                    prep_workflow(
                        workflow_path=workflow_path,
                        comfyui_path=comfyui_path,
                        shared_path=shared_path,
                        vram_gb=vram_gb,
                        out_path=out_path,
                        map_path=map_path,
                        auto_symlink=auto_symlink,
                        _rerun=True,
                    )
                    return
            else:
                print("Run the wget commands above when ready, then re-run this script.")
    if patches:
        print(f"\nWorkflow patched with {len(patches)} filename substitution(s).")
    print(f"\nOutput: {out_path}")


# =============================================================================
# Entry point
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resolve and link models for a ComfyUI workflow."
    )
    parser.add_argument(
        "--workflow", required=True, metavar="PATH",
        help="Path to the ComfyUI workflow JSON",
    )
    parser.add_argument(
        "--comfyui", required=True, metavar="PATH",
        help="Path to the ComfyUI installation directory",
    )
    parser.add_argument(
        "--shared", required=True, metavar="PATH",
        help="Path to the AI-Shared-Resources directory",
    )
    parser.add_argument(
        "--vram", type=int, default=12, metavar="GB",
        help="Available VRAM in GB — used to pick best model variant (default: 12)",
    )
    parser.add_argument(
        "--out", metavar="PATH",
        help="Output path for patched workflow (default: <workflow>_patched.json)",
    )
    parser.add_argument(
        "--map", metavar="PATH",
        default=str(SCRIPT_DIR.parent / "ai_comfy_model_map.json"),
        help="Path to ai_comfy_model_map.json (generated if missing)",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="Auto-accept symlink when hardlink fails (cross-filesystem)",
    )
    args = parser.parse_args()

    workflow_path = Path(args.workflow)
    comfyui_path  = Path(args.comfyui)
    shared_path   = Path(args.shared)
    map_path      = Path(args.map)

    if not workflow_path.exists():
        print(f"error: workflow not found: {workflow_path}", file=sys.stderr)
        sys.exit(1)
    if not (comfyui_path / "folder_paths.py").exists():
        print(f"error: not a ComfyUI directory: {comfyui_path}", file=sys.stderr)
        sys.exit(1)
    if not shared_path.exists():
        print(f"error: shared resources not found: {shared_path}", file=sys.stderr)
        sys.exit(1)

    if args.out:
        out_path = Path(args.out)
    else:
        out_path = workflow_path.parent / (workflow_path.stem + "_patched" + workflow_path.suffix)

    prep_workflow(
        workflow_path = workflow_path,
        comfyui_path  = comfyui_path,
        shared_path   = shared_path,
        vram_gb       = args.vram,
        out_path      = out_path,
        map_path      = map_path,
        auto_symlink  = args.yes,
    )


if __name__ == "__main__":
    main()
