#!/usr/bin/env python3
# =============================================================================
# ai_comfy_model_map.py  —  Parse ComfyUI folder_paths and write model dir map
# =============================================================================
# Reads ComfyUI's folder_names_and_paths dict and writes a JSON recipe that
# maps model categories to their on-disk directories, plus a node-type →
# category lookup table. Used by ai_workflow_prep.py to know where to link
# model files.
#
# Tries a live import of folder_paths first (ComfyUI added to sys.path
# temporarily). Falls back to a static AST parse if the import chain fails.
#
# Usage:
#   python3 ai_comfy_model_map.py --comfyui /path/to/ComfyUI
#   python3 ai_comfy_model_map.py --comfyui /path/to/ComfyUI --out map.json
#
# Output JSON keys:
#   generated_at, comfyui_version, comfyui_path, model_dirs, node_type_to_category
#
# Standalone — no dependency on the AI_Tools stack.
# Requires: Python 3.9+
# =============================================================================

import ast
import json
import os
import re
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ImportError:
    tomllib = None  # type: ignore[assignment]

SCRIPT_DIR = Path(__file__).parent
DEFAULT_OUT = SCRIPT_DIR.parent / "ai_comfy_model_map.json"

# Node type → ComfyUI model category.
# This is the hardcoded mapping that ai_workflow_prep.py uses when it scans
# workflow nodes for required models.
NODE_TYPE_TO_CATEGORY: dict[str, str] = {
    # Diffusion model (unet) loaders
    "UNETLoader":             "diffusion_models",
    "UnetLoaderGGUF":         "diffusion_models",
    "DiffusionModelLoader":   "diffusion_models",
    # Checkpoint loaders
    "CheckpointLoaderSimple": "checkpoints",
    "CheckpointLoader":       "checkpoints",
    "ImageOnlyCheckpointLoader": "checkpoints",
    # VAE
    "VAELoader":              "vae",
    "VAELoaderKJ":            "vae",
    # CLIP / text encoders
    "CLIPLoader":             "text_encoders",
    "DualCLIPLoader":         "text_encoders",
    # LoRA
    "LoraLoader":             "loras",
    "LoraLoaderModelOnly":    "loras",
    # Upscale
    "UpscaleModelLoader":     "upscale_models",
    # CLIP Vision
    "CLIPVisionLoader":       "clip_vision",
    # Audio VAE
    "AudioVAELoader":         "audio_encoders",
    "LowVramAudioVAELoader":  "audio_encoders",
    "LTXVAudioVAELoader":     "audio_encoders",
    # WanVideoWrapper
    "WanVideoModelLoader":    "diffusion_models",
    "WanVideoLoraSelectMulti":"loras",
    "WanVideoVAELoader":      "vae",
    "WanVideoTextEncodeCached":"text_encoders",
    # Detection / segmentation
    "DownloadAndLoadSAM2Model":"detection",
}

MODEL_EXTENSIONS: set[str] = {
    ".safetensors", ".gguf", ".pt", ".bin", ".ckpt", ".pth", ".pt2", ".sft",
}


# =============================================================================
# Version detection
# =============================================================================

def get_comfyui_version(comfyui_path: Path) -> str:
    """Read ComfyUI version from pyproject.toml."""
    toml_path = comfyui_path / "pyproject.toml"
    if not toml_path.exists():
        return "unknown"
    text = toml_path.read_text()
    if tomllib is not None:
        try:
            data = tomllib.loads(text)
            return data.get("project", {}).get("version", "unknown")
        except Exception:
            pass
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return m.group(1) if m else "unknown"


# =============================================================================
# Static AST parse of folder_paths.py
# =============================================================================

def _eval_os_path_join(node: ast.expr, variables: dict[str, str]) -> str | None:
    """Evaluate an ast.Call that represents os.path.join(…) with known variables."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr == "join"):
        return None
    parts: list[str] = []
    for arg in node.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            parts.append(arg.value)
        elif isinstance(arg, ast.Name) and arg.id in variables:
            parts.append(variables[arg.id])
        elif isinstance(arg, ast.Call):
            val = _eval_os_path_join(arg, variables)
            if val is None:
                return None
            parts.append(val)
        else:
            return None
    return os.path.join(*parts) if parts else None


def _parse_folder_paths_static(comfyui_path: Path) -> dict[str, list[str]]:
    """Parse folder_paths.py with AST — no ComfyUI imports required."""
    fp_file = comfyui_path / "folder_paths.py"
    source = fp_file.read_text()
    tree = ast.parse(source)

    variables: dict[str, str] = {
        "base_path":  str(comfyui_path),
        "models_dir": str(comfyui_path / "models"),
    }

    result: dict[str, list[str]] = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not (
            isinstance(target, ast.Subscript)
            and isinstance(target.value, ast.Name)
            and target.value.id == "folder_names_and_paths"
        ):
            continue
        slice_node = target.slice
        if not (isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, str)):
            continue
        category = slice_node.value

        val = node.value
        if not isinstance(val, ast.Tuple) or len(val.elts) < 1:
            continue
        dirs_node = val.elts[0]
        if not isinstance(dirs_node, ast.List):
            continue

        dirs: list[str] = []
        for elt in dirs_node.elts:
            p = _eval_os_path_join(elt, variables)
            if p:
                dirs.append(p)
        if dirs:
            result[category] = dirs

    return result


# =============================================================================
# Dynamic import of folder_paths
# =============================================================================

def _import_folder_paths(comfyui_path: Path) -> dict[str, list[str]]:
    """Import folder_paths from ComfyUI. Temporarily clears sys.argv so
    ComfyUI's argparse does not see our CLI arguments."""
    saved_argv = sys.argv[:]
    saved_path = sys.path[:]
    known_modules = set(sys.modules.keys())

    sys.argv = [sys.argv[0]]
    sys.path.insert(0, str(comfyui_path))
    try:
        import folder_paths  # type: ignore[import]
        raw = dict(folder_paths.folder_names_and_paths)
        return {k: list(v[0]) for k, v in raw.items()}
    finally:
        sys.argv = saved_argv
        sys.path[:] = saved_path
        for key in list(sys.modules.keys()):
            if key not in known_modules:
                del sys.modules[key]


def load_folder_paths(comfyui_path: Path) -> dict[str, list[str]]:
    """Return folder_names_and_paths as {category: [dir, …]}.
    Tries live import first; falls back to static AST parse on any failure."""
    try:
        result = _import_folder_paths(comfyui_path)
        print("  folder_paths: loaded via import", file=sys.stderr)
        return result
    except Exception as e:
        print(f"  folder_paths: import failed ({e}), using static parse", file=sys.stderr)
        return _parse_folder_paths_static(comfyui_path)


# =============================================================================
# Map builder
# =============================================================================

def build_map(comfyui_path: Path, out_path: Path) -> dict:
    """Build and write the model map JSON. Returns the map dict."""
    comfyui_path = comfyui_path.resolve()
    model_dirs = load_folder_paths(comfyui_path)
    version = get_comfyui_version(comfyui_path)

    data = {
        "generated_at":          datetime.now(timezone.utc).isoformat(),
        "comfyui_version":        version,
        "comfyui_path":           str(comfyui_path),
        "model_dirs":             model_dirs,
        "node_type_to_category":  NODE_TYPE_TO_CATEGORY,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=2) + "\n")
    return data


# =============================================================================
# Entry point
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse ComfyUI folder_paths and write a model directory map JSON."
    )
    parser.add_argument(
        "--comfyui", required=True, metavar="PATH",
        help="Path to ComfyUI installation directory",
    )
    parser.add_argument(
        "--out", default=str(DEFAULT_OUT), metavar="PATH",
        help=f"Output JSON path (default: {DEFAULT_OUT})",
    )
    args = parser.parse_args()

    comfyui_path = Path(args.comfyui)
    out_path = Path(args.out)

    if not (comfyui_path / "folder_paths.py").exists():
        print(f"error: folder_paths.py not found in {comfyui_path}", file=sys.stderr)
        sys.exit(1)

    data = build_map(comfyui_path, out_path)

    cats = list(data["model_dirs"].keys())
    print(f"ComfyUI {data['comfyui_version']}  @  {comfyui_path}")
    print(f"{len(cats)} categories: {', '.join(cats)}")
    print(f"Written: {out_path}")


if __name__ == "__main__":
    main()
