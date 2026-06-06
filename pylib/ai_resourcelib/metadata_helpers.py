# ai_resourcelib/metadata_helpers.py
"""
   metadata_helpers.py
   Library file located in <script dir>/ai_resourcelib/

   used by:
   ai_collect_metadata.py
   (possibley others later)

"""
import json
import yaml
import ast
import re
import zipfile
import tarfile
import pickle
from pathlib import Path
from typing import Any, Dict

# ========================
# Robust embedded JSON extraction
# ========================

def extract_keyvalues(s: str) -> dict:
    """
    Best-effort regex to extract top-level key-value pairs from a messy
    JSON-ish or Python dict-ish string.

    Handles values which can be:
    - Quoted strings (with escaped quotes and backslashes),
    - Simple dict/list blocks (non-nested),
    - Numbers, booleans, null literals.

    Returns a dictionary of keys to cleaned string values.
    """
    entry_pat = re.compile(
        r'"([^"]+)"\s*:\s*'                 # key = "some_text":
        r'(?:'                             # Non-capturing group for values
            r'"(.*?)(?<!\\)"'              # quoted string (non-greedy)
            r'|'                          # OR
            r'\{[^\{\}]*\}'                # simple dict block
            r'|'                          # OR
            r'\[[^\[\]]*\]'                # simple list block
            r'|'                          # OR
            r'[0-9.\-eE]+'                 # numbers (ints, floats)
            r'|'                          # OR
            r'true|false|null'             # literals
        r')',
        re.DOTALL | re.IGNORECASE
    )

    res = {}
    for match in entry_pat.findall(s):
        key = match[0]
        # Pick first non-empty group among value captures
        val = None
        for group in match[1:]:
            if group:
                val = group
                break
        if val is None:
            val = ''
        if val.startswith('"') and val.endswith('"'):
            val = val[1:-1].replace('\\"', '"').replace('\\\\', '\\')
        res[key] = val
    return res


def extract_first_brace_chunk(s: str) -> str:
    """
    Extract the first balanced {...} chunk from the string s.
    Returns the chunk including braces, or empty string if none found.
    """
    start = s.find('{')
    if start == -1:
        return ''
    brace_level = 0
    for i in range(start, len(s)):
        c = s[i]
        if c == '{':
            brace_level += 1
        elif c == '}':
            brace_level -= 1
            if brace_level == 0:
                return s[start:i+1]
    return ''


def recursive_json_parse(obj):
    """
    Recursively parse strings that contain JSON in values,
    converting nested JSON strings to dictionaries/lists.
    """
    if isinstance(obj, dict):
        return {k: recursive_json_parse(v) for k, v in obj.items()}
    if isinstance(obj, str):
        try:
            parsed = json.loads(obj)
            return recursive_json_parse(parsed)
        except Exception:
            return obj
    return obj


def extract_metadata_from_file(filepath: Path) -> dict:
    """
    Main extraction function.

    Reads the file as binary, extracts metadata chunk,
    attempts full JSON parsing, falls back to literal_eval,
    then regex extraction if all else fails.
    Finally, recursively parses nested JSON strings.

    Returns the recovered metadata dictionary.
    """
    with open(filepath, "rb") as f:
        data = f.read()

    start = data.find(b'{')
    if start == -1:
        raise ValueError(f"No '{{' found in file {filepath}")

    # Decode from first brace position to end as UTF-8 with replacement
    prelim_text = data[start:].decode("utf-8", errors="replace")
    metadata_str = extract_first_brace_chunk(prelim_text)
    if not metadata_str:
        raise ValueError(f"Could not find balanced '{{}}' chunk in file {filepath}")

    # 1) Try JSON parse
    try:
        meta = json.loads(metadata_str)
    except Exception:
        # 2) fallback literal_eval
        try:
            meta = ast.literal_eval(metadata_str)
        except Exception:
            # 3) fallback regex best-effort extraction
            meta = extract_keyvalues(metadata_str)

    # Recursively parse nested JSON string values if possible
    meta = recursive_json_parse(meta)

     # If meta is empty dict or null, treat as failure
    if not meta or (isinstance(meta, dict) and len(meta) == 0):
        return {"success": False, "error": "No valid metadata extracted"}
    else:
        return {"success": True, "metadata": meta}

# ========================
# JSON serialization helper (used by safetensors and torch extractors)
# ========================

def _serialize_value(val):
    """
    Convert PyTorch / numpy field values to JSON-serializable forms.

    Tensors and arrays become descriptive strings; bytes are decoded where
    possible; primitives pass through unchanged.
    """
    try:
        import torch
        import numpy as np
    except ImportError:
        try:
            return str(val)
        except Exception:
            return repr(val)

    if isinstance(val, torch.Tensor):
        return f"Tensor(shape={list(val.shape)}, dtype={val.dtype})"

    if isinstance(val, np.ndarray):
        return f"ndarray(shape={val.shape}, dtype={val.dtype})"

    if isinstance(val, bytes):
        try:
            return val.decode('utf-8')
        except UnicodeDecodeError:
            return f"bytes[{len(val)}]"

    if isinstance(val, (int, float, str, bool)):
        return val

    try:
        return str(val)
    except Exception:
        return repr(val)


# ========================
# Safe Tensor Loader Metadata Extraction
# ========================

def _read_safetensors_header_direct(filepath: Path) -> dict:
    """
    Read a safetensors file header using only the binary format spec.

    Safetensors layout:
        bytes 0-7   : little-endian uint64 — byte length of the header JSON
        bytes 8-8+N : UTF-8 JSON header containing tensor descriptors and
                      an optional '__metadata__' key with user metadata

    This reads exactly 8 + N bytes regardless of file size, so a 20GB model
    is as fast as a 100MB model.

    Returns:
        dict: {
            "success": bool,
            "error": str or None,
            "keys": list[str],   # tensor keys (excluding '__metadata__')
            "metadata": dict,    # contents of '__metadata__', or {}
        }
    """
    import struct

    MAX_HEADER_BYTES = 100 * 1024 * 1024  # 100 MB sanity cap

    try:
        with open(filepath, 'rb') as f:
            prefix = f.read(8)
            if len(prefix) < 8:
                return {"success": False, "error": "File too small to be safetensors", "keys": [], "metadata": {}}
            header_length = struct.unpack_from('<Q', prefix)[0]
            if header_length == 0 or header_length > MAX_HEADER_BYTES:
                return {"success": False, "error": f"Implausible header length: {header_length}", "keys": [], "metadata": {}}
            header_bytes = f.read(header_length)
            if len(header_bytes) < header_length:
                return {"success": False, "error": "File truncated within header", "keys": [], "metadata": {}}

        header = json.loads(header_bytes.decode('utf-8'))
        metadata = header.pop('__metadata__', {}) or {}
        keys = list(header.keys())
        return {
            "success": True,
            "error": None,
            "keys": keys,
            "metadata": {k: _serialize_value(v) for k, v in metadata.items()},
        }

    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return {"success": False, "error": f"Header parse failed: {e}", "keys": [], "metadata": {}}
    except Exception as e:
        return {"success": False, "error": f"Direct header read failed: {e}", "keys": [], "metadata": {}}


def extract_safetensors_metadata(filepath: Path) -> dict:
    """
    Extract keys and metadata from a .safetensors file.

    Primary path: direct binary header read — reads only 8 + N header bytes,
    completely independent of file size. A 20GB model is as fast as a 100MB one.

    Fallback: safetensors.safe_open, used only if the direct read fails
    (e.g. non-standard header encoding) and the package is available.

    Returns:
        dict: {
            "success": bool,
            "error": str or None,
            "keys": list[str],   # tensor keys in the safetensors file
            "metadata": dict,    # user metadata from '__metadata__' block
        }
    """
    result = _read_safetensors_header_direct(filepath)
    if result["success"]:
        return result

    # Direct read failed — attempt safe_open fallback
    direct_error = result["error"]
    try:
        from safetensors import safe_open
        with safe_open(str(filepath), framework="pt") as f:
            keys = list(f.keys())
            raw_metadata = f.metadata() or {}
        return {
            "success": True,
            "error": None,
            "keys": keys,
            "metadata": {k: _serialize_value(v) for k, v in raw_metadata.items()},
        }
    except ImportError:
        return {
            "success": False,
            "error": f"Direct read failed ({direct_error}); safetensors package not available for fallback",
            "keys": [],
            "metadata": {},
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Direct read failed ({direct_error}); safe_open fallback also failed: {e}",
            "keys": [],
            "metadata": {},
        }

# ========================
# Torch Loader Metadata Extraction
# ========================

def extract_torch_checkpoint_metadata(filepath: Path) -> dict:
    """
    Extract detailed metadata from a PyTorch checkpoint file.

    Returns:
        dict: {
            "success": bool,
            "model_class_name": str or None,
            "is_full_model": bool,
            "total_tensors": int,
            "tensor_key_samples": list[str],
            "metadata_keys": list[str],
            "metadata_snippet": dict,
            "metadata": dict,
            "error": str (if failed),
            "raw_object_type": str,
        }
    """
    import time
    import logging
    t0 = time.perf_counter()
    logging.info(f"torch: importing ...")
    import torch
    logging.info(f"torch: imported ({time.perf_counter() - t0:.1f}s)")

    result = {
        "success": False,
        "model_class_name": None,
        "is_full_model": False,
        "total_tensors": 0,
        "tensor_key_samples": [],
        "metadata_keys": [],
        "metadata_snippet": {},
        "metadata": {},
        "error": None,
        "raw_object_type": "unknown"
    }

    try:
        logging.info(f"torch.load: loading {filepath.name} ...")
        t1 = time.perf_counter()
        obj = torch.load(str(filepath), map_location="cpu")
        logging.info(f"torch.load: loaded {filepath.name} ({time.perf_counter() - t1:.1f}s)")
    except Exception as e:
        error_message = str(e)
        phrase = "In PyTorch"
        index = error_message.find(phrase)
        if index != -1:
            error_message = error_message[: index -1].strip()
        result["error"] = f"Torch load failed: {error_message}"
        return result

    try:
        import torch.nn as nn

        metadata_values = {}
        metadata_snippet = {}
        total_tensors = 0
        tensor_key_samples = []
        model_class_name = None

        if isinstance(obj, nn.Module):
            model_class_name = obj.__class__.__name__
            result["model_class_name"] = model_class_name
            result["raw_object_type"] = type(obj).__name__
            result["is_full_model"] = True
            metadata_values["model_class_name"] = model_class_name
        elif isinstance(obj, dict):
            possible_state_dicts = [
                obj.get("state_dict"),
                obj.get("model"),
                obj.get("params"),
                obj,
            ]
            state_dict = None
            for candidate in possible_state_dicts:
                if isinstance(candidate, dict):
                    if any(isinstance(v, torch.Tensor) for v in candidate.values()):
                        state_dict = candidate
                        break

            if state_dict:
                for k, v in state_dict.items():
                    if isinstance(v, torch.Tensor):
                        total_tensors += 1
                        if len(tensor_key_samples) < 5:
                            tensor_key_samples.append(
                                f"{k} (shape={list(v.shape)}, dtype={v.dtype})"
                            )

            for key in ["meta", "config", "hyperparameters", "ss_network_module"]:
                if key in obj:
                    metadata_snippet[key] = obj[key]

            for k, v in obj.items():
                try:
                    metadata_values[k] = _serialize_value(v)
                except Exception:
                    metadata_values[k] = str(type(v))
            result["raw_object_type"] = "dict"
        else:
            metadata_values["loaded_object_type"] = type(obj).__name__
            result["raw_object_type"] = type(obj).__name__

        metadata_values.update({
            "total_tensors": total_tensors,
            "tensor_key_samples": tensor_key_samples,
            "metadata_keys": list(metadata_snippet.keys()),
            "metadata_snippet": metadata_snippet,
        })
        result.update({
            "success": True,
            "error": None,
            "metadata": metadata_values,
            "metadata_snippet": metadata_snippet,
            "total_tensors": total_tensors,
            "tensor_key_samples": tensor_key_samples,
            "metadata_keys": list(metadata_snippet.keys()),
        })

    except Exception as e:
        result["success"] = False
        result["error"] = f"Torch Metadata extraction failed: {e}"

    return result





# ========================
# Atomic Archive/Zip handling Helpers
# ========================

def extract_archive_model_metadata(filepath: Path) -> dict:
    """
    Extract metadata from a model checkpoint file that might be a zip archive.

    Args:
        filepath (Path): Path to a file.

    Returns:
        dict: Info including top-level keys, presence of data.pkl, version, or error on failure.
    """
    if not filepath.exists():
        return {"success": False, "error": f"File '{filepath}' does not exist"}

    try:
        if zipfile.is_zipfile(filepath):
            with zipfile.ZipFile(filepath, 'r') as z:
                namelist = z.namelist()
                top_level_dirs = {p.split('/')[0] for p in namelist if p.strip()}

                metadata = {
                    "success": True,
                    "metadata_keys": [],
                    "data_pkl_present": False,
                    "resource_version": None,
                }

                for top_dir in top_level_dirs:
                    data_pkl_path = f"{top_dir}/data.pkl"
                    if data_pkl_path in namelist:
                        metadata["data_pkl_present"] = True
                        try:
                            with z.open(data_pkl_path) as f:
                                data_pkl = pickle.load(f)
                                if isinstance(data_pkl, dict):
                                    metadata["metadata_keys"].extend(list(data_pkl.keys()))
                                else:
                                    metadata["metadata_keys"].append(f"data.pkl content type: {type(data_pkl).__name__}")
                        except Exception as e:
                            metadata.setdefault("warnings", []).append(f"Failed to load data.pkl: {str(e)}")

                    version_path = f"{top_dir}/version"
                    if version_path in namelist:
                        try:
                            with z.open(version_path) as f:
                                version_text = f.read().decode('utf-8').strip()
                                metadata["version"] = version_text
                        except Exception as e:
                            metadata.setdefault("warnings", []).append(f"Failed to read version file: {str(e)}")

                if not metadata["metadata_keys"] and not metadata["version"] and not metadata["data_pkl_present"]:
                    metadata["metadata_keys"] = [f"Top-level dirs: {list(top_level_dirs)}"]

                return metadata

        # Future extension for tar archives...

        return {"success": False, "error": "File is not a recognized zip archive"}

    except Exception as e:
        return {"success": False, "error": f"Exception processing archive: {str(e)}"}

# ========================
# Atomic onnx handling Helper
# ========================

def extract_onnx_metadata(filepath: Path) -> dict:
    """
    Load and validate ONNX model metadata.

    Returns:
        dict with success status, metadata, or error details.
    """
    try:
        import onnx
    except ImportError:
        return {"success": False, "error": "onnx not installed"}

    try:
        size_bytes = filepath.stat().st_size
        model = onnx.load(str(filepath))
        onnx.checker.check_model(model)

        return {
            "success": True,
            "ai_resource_type": "onnx",
            "file_size_bytes": size_bytes,
            "note": "ONNX model loaded and validated successfully",
        }
    except Exception as e:
        return {
            "success": False,
            "file_size_bytes": None,
            "error": f"File is not a valid ONNX model (validation failed): {str(e)}"
        }


# ========================
# Atomic Pruning/Deduplication Helpers
# ========================

def prune_duplicate_strings(strings_list):
    """
    Remove duplicate strings while preserving original order.

    Args:
        strings_list (list[str])

    Returns:
        list[str] deduplicated
    """
    seen = set()
    result = []
    for s in strings_list:
        if s not in seen:
            seen.add(s)
            result.append(s)
    return result

def prune_redundant_derived_metadata(derived_metadata: dict, current_version: str) -> dict:
    """
    Prune older derived_metadata versions identical to current_version.

    Args:
        derived_metadata (dict): keyed by version strings
        current_version (str): active version key

    Returns:
        pruned derived_metadata dict
    """
    if current_version not in derived_metadata or not isinstance(derived_metadata[current_version], dict):
        return derived_metadata

    current_metadata = derived_metadata[current_version].get("metadata")
    if current_metadata is None:
        return derived_metadata

    keys_to_delete = []
    for ver, data in derived_metadata.items():
        if ver == current_version:
            continue
        if isinstance(data, dict) and data.get("success", False):
            meta = data.get("metadata")
            try:
                if json.dumps(meta, sort_keys=True) == json.dumps(current_metadata, sort_keys=True):
                    keys_to_delete.append(ver)
            except Exception:
                pass

    for k in keys_to_delete:
        del derived_metadata[k]

    return derived_metadata

def prune_duplicate_metadata_entries(metadata_list):
    """
    Deduplicate list of metadata dicts by JSON serialization.

    Args:
        metadata_list (list[dict])

    Returns:
        list[dict] deduplicated
    """
    seen = set()
    result = []
    for item in metadata_list:
        try:
            rep = json.dumps(item, sort_keys=True)
        except Exception:
            rep = None
        if rep not in seen:
            seen.add(rep)
            result.append(item)
    return result

def prune_strings_in_nested(obj):
    """
    Recursively prune duplicate strings inside lists of strings in nested structures.

    Args:
        obj (any nested dict/list/...)

    Returns:
        cleaned nested structure
    """
    if isinstance(obj, list):
        if all(isinstance(i, str) for i in obj):
            return prune_duplicate_strings(obj)
        else:
            return [prune_strings_in_nested(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: prune_strings_in_nested(v) for k, v in obj.items()}
    else:
        return obj


# ========================
# Sidecar Metadata Parsing (Stub)
# ========================

def parse_sidecar_metadata(filepath: Path) -> Dict[str, Any]:
    """
    Stub parser for text-based sidecar files (txt, json, yaml, prompts, etc.).

    Returns:
        dict with success, reason, filepath, function name, and optional payload.
    """
    result = {
        "success": False,
        "reason": "This is a stub parser. Implement sidecar data extraction here.",
        "file": str(filepath),
        "function": "parse_sidecar_metadata",
        "payload": None
    }
    return result


# ========================
# Text vs Binary Heuristic
# ========================

def is_likely_text_file(path: Path, sample_size=1024) -> bool:
    """
    Heuristic to detect if a file is text or binary based on checked bytes.

    Args:
        path (Path)
        sample_size (int): bytes to sample from head and tail

    Returns:
        bool: True if likely text, False if binary or unreadable
    """
    try:
        file_size = path.stat().st_size
        if file_size == 0:
            return False

        with open(path, 'rb') as f:
            start_chunk = f.read(sample_size)
            if file_size > sample_size * 2:
                f.seek(-sample_size, 2)
                end_chunk = f.read(sample_size)
                chunk = start_chunk + end_chunk
            else:
                chunk = start_chunk

        for byte in chunk:
            if byte < 0x20 and byte not in (0x09, 0x0A, 0x0D):
                return False
        return True

    except Exception:
        return False


# ========================
# Helper functions for filenames and folders
# ========================

def get_with_default(mapping: dict, key, default=None):
    """
    Retrieve value from dict or default if key missing.
    """
    return mapping.get(key, default)

def assign_extension_for_file(
    filepath: Path,
    resource_folder_name: str,
    resource_type: str,
    extension_mapping: dict
) -> Path:
    """
    Return Path with proper extension added if none exists,
    based on resource_type or fallback.
    """
    if filepath.suffix == '':
        ext = get_with_default(extension_mapping, resource_type, default='.unknown')
        return filepath.with_suffix(ext)
    return filepath

def is_file_under_folder(filepath: Path, folder_names: set) -> bool:
    """
    Check if filepath lives under any folder in folder_names.
    """
    p = filepath.parent
    while p != p.parent:
        if p.name.lower() in folder_names:
            return True
        p = p.parent
    return False

def get_resource_folder_name(filepath: Path, folder_names: set) -> str:
    """
    Get nearest folder name from filepath parents in folder_names.
    """
    p = filepath.parent
    while p != p.parent:
        if p.name.lower() in folder_names:
            return p.name
        p = p.parent
    return ''

def match_resource_folder_pattern(folder_name: str, ai_folders: set) -> str:
    """
    Check if folder_name contains or starts with any ai_folders pattern.

    Returns matched pattern or None.
    """
    folder_name_lower = folder_name.lower()
    for pattern in ai_folders:
        if pattern in folder_name_lower:
            return pattern
    return None

def should_process_file(filepath: Path, ai_folder_names: set) -> bool:
    """
    Decide whether to process file (true) or skip (false).

    Always process if under AI resource folder, skip likely text files.
    """
    if not is_file_under_folder(filepath, ai_folder_names):
        return False
    if is_likely_text_file(filepath):
        return False
    return True

