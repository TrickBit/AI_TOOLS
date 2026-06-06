# ai_resourcelib/metadata_structure.py
"""
   metadata_structure.py
   Library file located in <script dir>/ai_resourcelib/

   Used by:
     - ai_collect_metadata.py
     - (possibly others later)
"""

from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Any

# ----------------------------
# Resource type normalization dictionary
# ----------------------------
RESOURCE_TYPE_NORMALIZATION = {
    "safetensors_model": "safetensors",
    "pytorch_checkpoint": "model_checkpoint",
    "onnx_model": "onnx",
    "json_metadata": "json",
    # Add more mappings as needed to normalize type names
}

# ----------------------------
# Data-driven Classification rules (can be extended or loaded externally)
# Order matters on tie-breaks — more specific types should come first.
# ----------------------------
_CLASSIFICATION_RULES = {
    # --- LoRA / fine-tuning adapters ---
    "lora": [
        {"metadata_values_contains": ["ss_network_module:lora", "lora"]},
        {"raw_metadata_key_is": {"ss_network_module": ["lora"]}},
        {"keys_contains": ["lora_up", "lora_down", "lora_te", "lora_unet"]},
        {"model_class_name_contains": ["lora"]},
    ],
    # --- Hypernetworks ---
    "hypernetwork": [
        {"metadata_values_contains": ["hypernetwork"]},
        {"raw_metadata_key_is": {"ss_network_module": ["hypernetwork"]}},
        {"keys_contains": ["hypernet"]},
        {"model_class_name_contains": ["hypernetwork"]},
    ],
    # --- Textual inversions / embeddings ---
    "textual_inversion": [
        {"metadata_values_contains": ["textual inversion", "textual_inversion"]},
        {"keys_contains": ["<"]},           # token embeddings use <token> key names
    ],
    # --- VAE ---
    "vae": [
        {"keys_contains": ["encoder.down_blocks", "decoder.up_blocks"]},
        {"keys_contains": ["first_stage_model.encoder", "first_stage_model.decoder"]},
        {"model_class_name_contains": ["autoencoderKL", "AutoencoderKL"]},
    ],
    # --- ControlNet ---
    "controlnet": [
        {"metadata_values_contains": ["controlnet"]},
        {"keys_contains": ["controlnet_cond_embedding"]},
        {"model_class_name_contains": ["controlnet"]},
    ],
    # --- Full image-generation checkpoints ---
    "checkpoint": [
        {"keys_contains": ["model.diffusion_model", "first_stage_model", "cond_stage_model"]},
        {"model_class_name_contains": ["ldm", "diffusion"]},
    ],
    # --- LLMs (language models) ---
    "llm": [
        {"keys_contains": ["language_model", "lm_head", "transformer.h.", "model.layers"]},
        {"metadata_values_contains": ["gemma", "llama", "qwen", "mistral", "phi",
                                      "gpt", "falcon", "mamba"]},
        {"model_class_name_contains": ["causal", "language", "llm"]},
    ],
    # --- Video diffusion models ---
    "video_diffusion": [
        {"keys_contains": ["temporal_transformer", "motion_module", "time_embed",
                           "video_model", "transformer3d"]},
        {"metadata_values_contains": ["animatediff", "cogvideo", "ltx", "wan",
                                      "stable video", "svd"]},
    ],
    # --- Video / image upscalers ---
    "upscaler": [
        {"keys_contains": ["RRDB", "RRDBNet", "realesrgan", "spynet"]},
        {"metadata_values_contains": ["upscal", "esrgan", "realesrgan", "upsampl"]},
        {"model_class_name_contains": ["esrgan", "upscal", "rrdb"]},
    ],
    # --- Depth estimators ---
    "depth_estimator": [
        {"keys_contains": ["depth_head", "depth_anything", "relative_position_bias_table"]},
        {"metadata_values_contains": ["depth", "monocular"]},
        {"model_class_name_contains": ["depth"]},
    ],
    # --- Detectors / pose / segmentation ---
    "detector": [
        {"keys_contains": ["mask_decoder", "prompt_encoder", "image_encoder.patch_embed",
                           "detect", "pose", "hand", "face"]},
        {"metadata_values_contains": ["yolo", "sam", "segment anything",
                                      "mediapipe", "dwpose", "openpose"]},
        {"model_class_name_contains": ["detector", "yolo", "sam", "pose"]},
    ],
    # --- Audio TTS / voice ---
    "audio_tts": [
        {"keys_contains": ["decoder.embed_tokens", "flow.estimator", "vocoder",
                           "audio_encoder"]},
        {"metadata_values_contains": ["tts", "kokoro", "voice", "speech synthesis",
                                      "text to speech"]},
        {"model_class_name_contains": ["tts", "kokoro", "vocoder"]},
    ],
    # --- Audio speech encoders (wav2vec, whisper etc) ---
    "audio_speech": [
        {"keys_contains": ["wav2vec2", "whisper", "speech_encoder",
                           "feature_extractor.conv_layers"]},
        {"metadata_values_contains": ["wav2vec", "whisper", "speech recognition",
                                      "asr"]},
        {"model_class_name_contains": ["wav2vec", "whisper"]},
    ],
    # --- Audio source separation ---
    "audio_separator": [
        {"keys_contains": ["roformer", "separator", "bs_roformer"]},
        {"metadata_values_contains": ["roformer", "separator", "source separation",
                                      "music separation"]},
        {"model_class_name_contains": ["roformer", "separator"]},
    ],
    # Catch-all — no rules, always loses to any real match
    "unknown": [],
}

# ----------------------------
# Filename-based hints (fallback when metadata is absent/empty)
# Files matching these substrings go to review/ but carry a classification_hint
# in the meta.json so future runs can promote them to real rules.
# To promote: move the entry to _CLASSIFICATION_RULES with appropriate key patterns.
# ----------------------------
FILENAME_HINTS = {
    'depth_anything':   'depth_estimator',
    'depth_pro':        'depth_estimator',
    'midas':            'depth_estimator',
    'raft':             'optical_flow',
    'spynet':           'optical_flow',
    'yolox':            'detector',
    'yolov':            'detector',
    'matanyone':        'detector',
    'sam_vit':          'detector',
    'dwpose':           'detector',
    'openpose':         'detector',
    'wav2vec':          'audio_speech',
    'whisper':          'audio_speech',
    'roformer':         'audio_separator',
    'kokoro':           'audio_tts',
    'campplus':         'audio_tts',
    'pyannote':         'audio_tts',
    'realesrgan':       'upscaler',
    'esrgan':           'upscaler',
    'gemma':            'llm',
    'llama':            'llm',
    'qwen':             'llm',
    'mistral':          'llm',
    'ltx':              'video_diffusion',
    'wan2':             'video_diffusion',
    'cogvideo':         'video_diffusion',
    'animatediff':      'video_diffusion',
    'rife':             'video_upscaler',
    'inswapper':    'detector',
    'det_10g':      'detector',
    'genderage':    'detector',
    'w600k':        'detector',
    '2d106det':     'detector',
    'insightface':  'detector',
    'codeformer':       'upscaler',
    'blip':             'detector',
    'model_base_caption': 'detector',
    'realesr':          'upscaler',
    'gfpgan':           'upscaler',
    'parsenet':         'detector',
    'detection_resnet': 'detector',
    'ip-adapter':       'controlnet',
    'ip_adapter':       'controlnet',
    'flux':             'checkpoint',
    't2iadapter':       'controlnet',
    'z_image_turbo':    'checkpoint',
    't5':               'text_encoder',
    'dreamlike':        'checkpoint',
    'controlnet-tile':  'controlnet',
    'controlnet-union': 'controlnet',
    '1k3d68':           'detector',
    'bnb_llm':          'llm',
}

# ----------------------------
# Directory-name hints (fallback signal when header classification is uncertain)
# Matched against the lowercase name of the file's immediate parent directory.
# Lower precedence than FILENAME_HINTS — used only when both header and filename
# classification are inconclusive.
# Keys are lowercase directory name substrings; values are resource type strings.
# ----------------------------
DIRECTORY_HINTS = {
    'loras':             'lora',
    'lora':              'lora',
    'checkpoints':       'checkpoint',
    'ckpts':             'checkpoint',       # Wan2GP top-level model dir
    'controlnet':        'controlnet',
    'embeddings':        'embedding',
    'textual_inversion': 'embedding',
    'embedding':         'embedding',
    'vae':               'vae',
    'unet':              'checkpoint',
    'diffusion_models':  'video_diffusion',  # ComfyUI video model dir name
    'text_encoders':     'text_encoder',
    'upscale_models':    'upscaler',
    'upscalers':         'upscaler',
    'hypernetworks':     'hypernetwork',
    'llm':               'llm',
    'clip':              'text_encoder',
    'detectors':         'detector',
    'depth':             'depth_estimator',
    'stable-diffusion': 'checkpoint',
    'stable_diffusion': 'checkpoint',
    'safety_checker':   'detector',
    'safety-checker':   'detector',
}

# ----------------------------
# _ABOUT_.txt content for each output folder
# Written once when a folder is first created.
# ----------------------------
ABOUT_FILENAME = "_ABOUT_.txt"

FOLDER_ABOUT = {
    "lora": (
        "CATEGORY:  models/lora/image\n"
        "PURPOSE:   LoRA weights for image generation models (SD, SDXL etc).\n"
        "INCLUDES:  LoRA, LyCORIS, LoHa, LoKr variants for image models.\n"
        "FORMATS:   .safetensors .pt\n"
    ),
    "lora_video": (
        "CATEGORY:  models/lora/video\n"
        "PURPOSE:   LoRA weights for video generation models.\n"
        "INCLUDES:  LoRAs targeting Wan, LTX, CogVideo, AnimateDiff, SVD etc.\n"
        "FORMATS:   .safetensors .pt\n"
    ),
    "embedding": (
        "CATEGORY:  embedding\n"
        "PURPOSE:   Textual inversion embeddings / learned concept tokens.\n"
        "FORMATS:   .bin .pt .safetensors\n"
    ),
    "hypernetwork": (
        "CATEGORY:  hypernetwork\n"
        "PURPOSE:   Hypernetwork style models for diffusion fine-tuning.\n"
        "FORMATS:   .pt .safetensors\n"
    ),
    "vae": (
        "CATEGORY:  vae\n"
        "PURPOSE:   Variational Autoencoder models — encode/decode latent space.\n"
        "FORMATS:   .safetensors .pt\n"
    ),
    "controlnet": (
        "CATEGORY:  controlnet\n"
        "PURPOSE:   ControlNet conditioning models for guided image generation.\n"
        "FORMATS:   .safetensors .pt\n"
    ),
    "checkpoint": (
        "CATEGORY:  checkpoint\n"
        "PURPOSE:   Full image-generation model checkpoints (SD, SDXL etc).\n"
        "FORMATS:   .safetensors .ckpt\n"
    ),
    "text_encoder": (
        "CATEGORY:  text_encoder\n"
        "PURPOSE:   Text encoder components (CLIP, T5 etc).\n"
        "FORMATS:   .safetensors .bin\n"
    ),
    "tokenizer": (
        "CATEGORY:  tokenizer\n"
        "PURPOSE:   Tokenizer model files.\n"
        "FORMATS:   .model .bin\n"
    ),
    "scheduler": (
        "CATEGORY:  scheduler\n"
        "PURPOSE:   Diffusion scheduler / noise schedule models.\n"
        "FORMATS:   .bin .safetensors\n"
    ),
    "llm": (
        "CATEGORY:  llm\n"
        "PURPOSE:   Large Language Models — text generation, chat, instruction following.\n"
        "INCLUDES:  Gemma, Llama, Qwen, Mistral, Phi, GPT variants.\n"
        "NOTE:      LLMs are often needed by multiple apps simultaneously.\n"
        "           Hardlinks here avoid duplication across installs.\n"
        "FORMATS:   .safetensors .bin .gguf .ggml\n"
    ),
    "video_diffusion": (
        "CATEGORY:  video/diffusion\n"
        "PURPOSE:   Video generation diffusion models.\n"
        "INCLUDES:  LTX-Video, Wan, CogVideoX, AnimateDiff, Stable Video Diffusion.\n"
        "FORMATS:   .safetensors .pt .ckpt\n"
    ),
    "upscaler": (
        "CATEGORY:  video/upscaler\n"
        "PURPOSE:   Image and video upscaling / super-resolution models.\n"
        "INCLUDES:  RealESRGAN, ESRGAN, spatial and temporal upscalers.\n"
        "FORMATS:   .safetensors .pth .pt\n"
    ),
    "depth_estimator": (
        "CATEGORY:  depth\n"
        "PURPOSE:   Monocular depth estimation models.\n"
        "INCLUDES:  Depth Anything, MiDaS, Depth Pro.\n"
        "FORMATS:   .pth .pt .safetensors .onnx\n"
    ),
    "detector": (
        "CATEGORY:  detector\n"
        "PURPOSE:   Models that locate, identify, or segment regions within images.\n"
        "INCLUDES:  SAM (Segment Anything), YOLO, DWPose, face detectors,\n"
        "           hand landmark models, object detectors.\n"
        "FORMATS:   .pt .pth .onnx .bin\n"
    ),
    "audio_tts": (
        "CATEGORY:  audio/tts\n"
        "PURPOSE:   Text-to-speech and voice synthesis models.\n"
        "INCLUDES:  Kokoro, CamPlus, Pyannote speaker models.\n"
        "FORMATS:   .onnx .bin .pt\n"
    ),
    "audio_speech": (
        "CATEGORY:  audio/speech\n"
        "PURPOSE:   Speech recognition and audio encoding models.\n"
        "INCLUDES:  Wav2Vec2, Whisper and similar ASR models.\n"
        "FORMATS:   .bin .pt .safetensors\n"
    ),
    "audio_separator": (
        "CATEGORY:  audio/separator\n"
        "PURPOSE:   Audio / music source separation models.\n"
        "INCLUDES:  BS-Roformer and similar stem separation models.\n"
        "FORMATS:   .ckpt .pt\n"
    ),
    "review": (
        "CATEGORY:  review\n"
        "PURPOSE:   Files that could not be automatically classified.\n"
        "           Check original_src_path in the .meta.json sidecar to\n"
        "           identify where each file came from.\n"
        "           Check classification_hint in meta.json for a suggested type.\n"
    ),
    "suspect": (
        "CATEGORY:  suspect\n"
        "PURPOSE:   Files that appear malformed, truncated, or otherwise suspicious.\n"
    ),
}




class MetadataDict(dict):
    """
    A dict subclass that supports nested key access and setting using dot-separated paths.

    Provides methods:
    - set_value(path: str, value: Any): Set nested key by dot-path, raising on missing or invalid intermediate keys.
    - get_value(path: str) -> Any: Get nested key by dot-path, raising on missing keys.

    MetadataDict is a subclass of a normal Python dict with an additional setter and getter (as above)
    both accept dot notation to represent the path through the keys to the final key that the value will go into.
    Think of the dotted notation as the directory where you want to put the value,
    and it's ok and expected for the value to be a dictionary.
    The only thing you can't do is create a new key inside the boundaries of the predefined dictionary.
    Basically, the only way to make new keys is to assign a dictionary with keys into an existing key.

    Example:
        metadata = MetadataDict({
            "ai_resource_identity": {
                "resource_type": "unknown",
                "processing_info": {
                    "file_hash": "unset"
                }
            }
        })

        # Set nested value
        metadata.set_value('ai_resource_identity.processing_info.file_hash', "abc123")

        # Get nested value
        file_hash = metadata.get_value('ai_resource_identity.processing_info.file_hash')
        print(file_hash)  # Outputs: abc123
    """

    def __init__(self, data: dict = None):
        """
        Construct MetadataDict from a plain dict, bypassing the guarded __setitem__
        so that the initial key structure can be populated freely.
        Nested plain dicts are converted to MetadataDict recursively.
        """
        super().__init__()
        if data:
            for key, value in data.items():
                if isinstance(value, dict) and not isinstance(value, MetadataDict):
                    value = MetadataDict(value)
                dict.__setitem__(self, key, value)

    def __setitem__(self, key, value):
        if key not in self:
            raise KeyError(f"Attempt to add new key '{key}' is not allowed in MetadataDict")
        # Optionally allow nested dictionaries to become MetadataDict automatically
        if isinstance(value, dict) and not isinstance(value, MetadataDict):
            value = MetadataDict(value)
        super().__setitem__(key, value)

    def set_value(self, path: str, value: Any) -> None:
        """
        Set a value in the nested dict using a dot-separated path.

        Args:
            path (str): Dot-separated path of nested keys.
            value (Any): Value to set.

        Raises:
            KeyError: If any intermediate key in the path is missing.
            TypeError: If any intermediate value along the path is not a dict.
        """
        keys = path.split('.')
        current = self
        for key in keys[:-1]:
            if key not in current:
                raise KeyError(f"Key '{key}' missing in path '{path}'")
            # Force nested dicts to be MetadataDict instances
            if not isinstance(current[key], MetadataDict):
                if isinstance(current[key], dict):
                    current[key] = MetadataDict(current[key])
                else:
                    raise TypeError(f"Value at key '{key}' in path '{path}' is not a dict")
            current = current[key]
        # Setting the final key, ensure it must exist
        last_key = keys[-1]
        if last_key not in current:
            raise KeyError(f"Key '{last_key}' missing in path '{path}'")
        current[last_key] = value

    def get_value(self, path: str) -> Any:
        """
        Get a value from the nested dict using a dot-separated path.

        Args:
            path (str): Dot-separated path of nested keys.

        Returns:
            Any: Value at nested path

        Raises:
            KeyError: If any key in the path does not exist.
        """
        keys = path.split('.')
        current = self
        for key in keys:
            if not isinstance(current, dict):
                raise TypeError(f"Value at key '{key}' in path '{path}' is not a dict")
            if key not in current:
                raise KeyError(f"Key '{key}' missing in path '{path}'")
            current = current[key]
        return current

    def update(self, *args, **kwargs):
        """
        Override update to disallow adding new keys.
        """
        other = dict(*args, **kwargs)
        for key, value in other.items():
            if key not in self:
                raise KeyError(f"Attempt to add new key '{key}' is not allowed in MetadataDict")
            # For nested dictionaries, convert recursively
            if isinstance(value, dict) and not isinstance(value, MetadataDict):
                value = MetadataDict(value)
            self[key] = value

    def setdefault(self, key, default=None):
        """
        Override setdefault to prevent adding new keys.
        """
        if key not in self:
            raise KeyError(f"Attempt to add new key '{key}' via setdefault is not allowed in MetadataDict")
        return super().setdefault(key, default)

    def __repr__(self):
        """
        Override repr to indicate this is a MetadataDict.
        """
        return f"MetadataDict({super().__repr__()})"
# ----------------------------
# Metadata Prototype Dict with MetadataDict
# ----------------------------
def get_json_dict(script_version: str = "0.0.0") -> Dict[str, Any]:
    """
    Return the full metadata prototype dict with all keys set to default placeholders.
    """
    return MetadataDict({
        "ai_resource_identity": {
            "resource_type": "unset",
            "resource_type_certainty": "unset",
            "classification_hint": "unset",
            "resource_version": "unknown",
            "processing_info": {
                "file_hash": "unset",
                "extension_assigned": "unset",
                "assignment_reason": "unset",
                "original_src_path": "unset",
                "original_filename": "unset",
                "final_filename": "unset",
                "script_version": script_version,
                "processing_commenced": datetime.utcnow().isoformat() + "Z",
                "processing_completed": "unset",
                "processing_notes": "unset",
                "extraction_summary": {
                    "jsondata": {"success": False, "error": "unset"},
                    "safetensors": {"success": False, "error": "unset"},
                    "torch": {"success": False, "error": "unset"},
                    "archive": {"success": False, "error": "unset"},
                    "onnx": {"success": False, "error": "unset"},
                    "sidecar": {"success": False, "error": "unset"},
                },
            },
        },
        "embedded_metadata": {
            "jsondata": {"success": False, "metadata": {}},
            "safetensors": {"success": False, "metadata": {"keys": []}},
            "torch": {
                "success": False,
                "model_class_name": None,
                "total_tensors": 0,
                "tensor_key_samples": [],
                "metadata_keys": [],
                "metadata_snippet": {},
                "metadata": {},
                "error": "unset",
            },
            "archive": {"success": False, "error": "unset"},
            "onnx": {"success": False, "file_size_bytes": None, "error": "unset"},
            "sidecar": {},
        },
    })

# ----------------------------
# Summarize extraction status into main processing info
# ----------------------------
def json_dict_summarize(json_dict: MetadataDict) -> MetadataDict:
    """
    Update processing_info.extraction_summary.* flags from embedded metadata success/error.
    """
    for extractor in ['jsondata', 'safetensors', 'torch', "archive", "onnx", "sidecar"]:
        embedded_metadata = json_dict.get('embedded_metadata', {})
        extractor_data = embedded_metadata.get(extractor, {})
        success = extractor_data.get('success', False)
        json_dict.set_value(
            f'ai_resource_identity.processing_info.extraction_summary.{extractor}.success',
            success
        )
        error = extractor_data.get('error', "unknown")
        json_dict.set_value(
            f'ai_resource_identity.processing_info.extraction_summary.{extractor}.error',
            error
        )
    return json_dict

# ----------------------------
# Metadata Normalization (currently disabled)
# ----------------------------
def normalize_ai_resource(metadata: Dict, filepath: Path) -> Dict:
    """
    Normalize and enrich metadata in-place for better usability and size.

    Currently disabled (returns metadata as-is).
    """
    # Deliberate passthrough; move normalization out or implement later
    return metadata

# ----------------------------
# Certainty builder for boolean details
# ----------------------------
def build_certainty(details: Dict[str, bool]) -> Dict:
    """
    Build certainty scoring of classification flags.

    Args:
        details (Dict[str, bool]): Dictionary of boolean criteria flags.

    Returns:
        Dict: Summary with counts and score string.
    """
    total = len(details)
    count = sum(1 for v in details.values() if v)
    score = f"{count}/{total}"
    return {
        "count": count,
        "total": total,
        "score": score,
        "details": details
    }


# ----------------------------
# Data-driven AI resource classifier
# ----------------------------

def classify_ai_resource(
    embedded_metadata: dict,
    filepath: Path,
    rules: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Data-driven classification of AI resource using extractor outputs and rules.

    Args:
        embedded_metadata (dict): Extractor outputs (all extractors combined).
        filepath (Path): Filepath of resource.
        rules (Optional[Dict]): Classification rules dictionary.

    Returns:
        dict: {
            "resource_type": normalized resource type string,
            "source_rule": matched rule key, or None,
            "type_certainty": certainty dict as count/total,
        }
    """
    rules = rules or _CLASSIFICATION_RULES
    resource_type, matched_patterns = _classify_by_rules(embedded_metadata, rules)

    # Normalize resource type name if recognized
    normalized_type = RESOURCE_TYPE_NORMALIZATION.get(resource_type, resource_type)

    certainty = {
        "matched": int(normalized_type != "unknown"),
        "total": len(rules),
        "matched_patterns_count": len(matched_patterns),
        "matched_patterns": matched_patterns,
    }
    return {
        "resource_type": normalized_type,
        "source_rule": resource_type if resource_type in rules else None,
        "type_certainty": certainty,
    }

def _classify_by_rules(metadata: dict, rules: dict) -> (str, list):
    """
    Internal engine that applies classification rules over metadata.

    Accumulates ALL pattern matches across all resource types, then returns
    the type with the most matched patterns. On a tie, the first-listed type wins.
    Also returns the full list of matched patterns for logging/certainty reporting.
    """
    all_matched_patterns = []  # flat list for logging
    match_counts = {}          # resource_type -> count of matched patterns

    for resource_type, pattern_list in rules.items():
        count = 0
        for pattern in pattern_list:
            if _pattern_matches(metadata, pattern):
                all_matched_patterns.append(f"{resource_type}: {pattern}")
                count += 1
        if count > 0:
            match_counts[resource_type] = count

    if not match_counts:
        return "unknown", all_matched_patterns

    # Return type with highest match count; first-listed wins on tie (dict preserves order)
    best_type = max(match_counts, key=lambda t: match_counts[t])
    return best_type.lower(), all_matched_patterns

def _pattern_matches(metadata: dict, pattern: dict) -> bool:
    """
    Check if pattern dict matches metadata.

    Supports:
    - metadata_values_contains
    - raw_metadata_key_is
    - keys_contains
    - model_class_name_contains
    """
    if "metadata_values_contains" in pattern:
        all_values = []
        for extractor_data in metadata.values():
            if isinstance(extractor_data, dict):
                all_values.extend(_flatten_values_to_strings(extractor_data))
            elif isinstance(extractor_data, list):
                all_values.extend(str(x).lower() for x in extractor_data)
            elif isinstance(extractor_data, str):
                all_values.append(extractor_data.lower())
        for substr in pattern["metadata_values_contains"]:
            if any(substr.lower() in v for v in all_values):
                return True

    if "raw_metadata_key_is" in pattern:
        for extractor_data in metadata.values():
            if not isinstance(extractor_data, dict):
                continue
            rawmeta = extractor_data.get("raw_metadata")
            if not isinstance(rawmeta, dict):
                continue
            for key, vals in pattern["raw_metadata_key_is"].items():
                v = str(rawmeta.get(key, "")).lower()
                if any(val.lower() == v for val in vals):
                    return True

    if "keys_contains" in pattern:
        for extractor_data in metadata.values():
            if not isinstance(extractor_data, dict):
                continue
            keyslist = [k.lower() for k in extractor_data.get("keys", [])]
            for substr in pattern["keys_contains"]:
                if any(substr.lower() in k for k in keyslist):
                    return True

    if "model_class_name_contains" in pattern:
        for extractor_data in metadata.values():
            if not isinstance(extractor_data, dict):
                continue
            clsname = extractor_data.get("model_class_name", "")
            if isinstance(clsname, str):
                clsname = clsname.lower()
                for substr in pattern["model_class_name_contains"]:
                    if substr.lower() in clsname:
                        return True

    return False

def _flatten_values_to_strings(d: dict) -> list:
    """
    Recursively flatten all values in a dict or nested structure to a list of lowercased strings.
    """
    strings = []
    for v in d.values():
        if isinstance(v, str):
            strings.append(v.lower())
        elif isinstance(v, dict):
            strings.extend(_flatten_values_to_strings(v))
        elif isinstance(v, (list, tuple)):
            for item in v:
                if isinstance(item, str):
                    strings.append(item.lower())
                elif isinstance(item, dict):
                    strings.extend(_flatten_values_to_strings(item))
                else:
                    strings.append(str(item).lower())
        else:
            strings.append(str(v).lower())

    return strings

# ----------------------------
# Export control: only these symbols are public
# ----------------------------
__all__ = [
    "get_json_dict",
    "json_dict_summarize",
    "normalize_ai_resource",
    "build_certainty",
    "classify_ai_resource",
    "MetadataDict",
    "FILENAME_HINTS",
    "DIRECTORY_HINTS",
    "ABOUT_FILENAME",
    "FOLDER_ABOUT",
]

