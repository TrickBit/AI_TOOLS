# LTX Director + Sulphur 2 — ComfyUI Setup Notes
**Jethro / RTX 3060 12GB / Driver 610 / CUDA 13.3**
*Generated June 2026*

---

## System context

| Item | Detail |
|------|--------|
| GPU | RTX 3060 12GB (Ampere / GA106) |
| Driver | 610.43.02 |
| CUDA (nvcc) | 13.3 |
| RAM | 32 GB |
| SageAttention | 2.2.0+cu130 built and cached at `/mnt/BACKUP_4.0_TB/AI_Collected_Wheels/localbuild/` |

**Why GGUF not FP8 safetensors:**
The RTX 3060 is Ampere — no native FP8 silicon. FP8 safetensors run via software emulation on Ampere, which is slower and uses more VRAM than GGUF + ComfyUI-GGUF's quantised inference. The video creator was on an RTX 5060 (Blackwell, native FP8). The video itself says at 5:34: *"if you're stuck on 8 or 12 gigs using Ampere... GGUFs are going to give you the best stability."*

---

## Downloads completed

All files landed in:
```
/mnt/BACKUP_4.0_TB/AI-Shared-Resources/video/_ltxdirector_incoming/
```

### Round 1 — models (34 min, ~57 GB)

| File | Size | Destination folder |
|------|------|--------------------|
| `sulphur_dev-Q5_K_M.gguf` | 16.1 GB | `Models/` → `unet/` |
| `sulphur_dev-Q6_K.gguf` | 17.8 GB | `Models/` → `unet/` |
| `sulphur_lora_rank_768.safetensors` | 10.3 GB | `LoRAs/` → `loras/` |
| `ltx-2.3-22b-distilled-lora-1.1_fro90_ceil72_condsafe.safetensors` | ~2 GB | `LoRAs/` → `loras/` |
| `gemma_3_12B_it_fp4_mixed.safetensors` | 9.5 GB | `TextEncoders/` → `text_encoders/` |
| `ltx-2.3_text_projection_bf16.safetensors` | ~600 MB | `TextEncoders/` → `text_encoders/` |
| `LTX23_video_vae_bf16.safetensors` | ~1 GB | `VAE/` → `vae/` |

### Round 2 — workflows + small models

| File | Size | Destination folder |
|------|------|--------------------|
| `LTX Director Example Workflow (Fixed).json` | tiny | `~/bin/scripts/AI_Tools/comfy workflows/` |
| `LTX Director Example Workflow Subgraphs v2.json` | tiny | `~/bin/scripts/AI_Tools/comfy workflows/` |
| `LTX I2V First Last Frame 2 Stage Workflow v6.json` | tiny | `~/bin/scripts/AI_Tools/comfy workflows/` |
| `LTX I2V First Last Frame 3 Stage Workflow v6.json` | tiny | `~/bin/scripts/AI_Tools/comfy workflows/` |
| `LTX I2V FFLF Custom Audio Workflow - SUPPORTS LATEST COMFYUI VERSION - V3.json` | tiny | `~/bin/scripts/AI_Tools/comfy workflows/` |
| `taeltx2_3.safetensors` | 23.5 MB | `VAE/` → `vae/` |
| `ltx-2.3-spatial-upscaler-x2-1.1.safetensors` | 996 MB | `upscale_models/` |

---

## Where files go in ComfyUI

ComfyUI's own `models/` tree is exposed to the shared drive via `extra_model_paths.yaml`.
The physical files live under `/mnt/BACKUP_4.0_TB/AI-Shared-Resources/video/`.
ComfyUI sees them via the yaml mapping — no copying needed.

```
ComfyUI/models/
│
├── unet/                         ← GGUF main models (ComfyUI-GGUF UnetLoader)
│   ├── sulphur_dev-Q5_K_M.gguf   PRIMARY for RTX 3060
│   └── sulphur_dev-Q6_K.gguf     optional higher quality
│
├── text_encoders/                ← LTX 2.3 text stack (NOT the old T5 loader)
│   ├── gemma_3_12B_it_fp4_mixed.safetensors   slot 1
│   └── ltx-2.3_text_projection_bf16.safetensors  slot 2
│
├── vae/
│   ├── LTX23_video_vae_bf16.safetensors   full quality decoder (final output)
│   └── taeltx2_3.safetensors              tiny VAE for latent previews
│
├── loras/
│   ├── sulphur_lora_rank_768.safetensors               use WITH sulphur_dev GGUFs
│   └── ltx-2.3-...-lora-1.1_fro90_ceil72_condsafe.safetensors
│
└── upscale_models/
    ├── ltx-2.3-spatial-upscaler-x2-1.1.safetensors   NEW v1.1 — use this
    └── ltxv_0.9.7_spatial_upscaler.safetensors        ✓ already present

ComfyUI/custom_nodes/             ← installed by ai_comfyui_postinstall.sh
    WhatDreamsCost-ComfyUI/       ← LTX Director node
    ComfyUI-GGUF/                 ← loads the .gguf files above
    ComfyUI-LTXVideo/             ← required by Director node
    ComfyUI-KJNodes/              ← required by Director node
    ComfyUI-IPAdapter-plus/
    ComfyUI-VideoHelperSuite/
    ComfyUI-WanVideoWrapper/
    ComfyUI-Advanced-ControlNet/
```

---

## Which ComfyUI node loads what

| File type | ComfyUI node |
|-----------|-------------|
| `.gguf` main model | **Unet Loader (GGUF)** — under "bootleg" category |
| Gemma 3 12B + projection | **LTXAVTextEncoderLoader** — two slots, one file each |
| Video VAE / tiny VAE | **VAELoader** |
| LoRA files | **LoraLoader** |
| Spatial upscaler | **UpscaleModelLoader** |
| Workflow JSON | Drag onto canvas, or Load Workflow button |

---

## Critical: T5 is dead for LTX 2.3

Your existing `t5-v1_1-xxl-encoder-Q8_0.gguf` is **only** for LTX 0.9.x workflows.
LTX 2.3 and Sulphur 2 both use **Gemma 3 12B** as the text encoder.

- Use `LTXAVTextEncoderLoader` — **not** the old T5 or CLIP loader nodes
- Slot 1: `gemma_3_12B_it_fp4_mixed.safetensors`
- Slot 2: `ltx-2.3_text_projection_bf16.safetensors`
- Pointing an LTX 2.3 workflow at T5 will silently produce garbage output

---

## VAE: two files, two jobs

| File | Size | Purpose |
|------|------|---------|
| `taeltx2_3.safetensors` | 23.5 MB | Tiny AutoEncoder — **fast latent previews** during generation. Workflows hardcode this exact filename — do not rename. |
| `LTX23_video_vae_bf16.safetensors` | ~1 GB | Full-quality VAE — **final frame decode**. Used in the output stage. |

These are NOT interchangeable. Workflows typically have two VAELoader nodes — one for each.
Your existing `taeltx_2.safetensors` is the equivalent for LTX 2.x — keep it for those workflows.

---

## LoRA usage rules

| LoRA | Use with | Notes |
|------|----------|-------|
| `sulphur_lora_rank_768.safetensors` | `sulphur_dev-Q*.gguf` only | Speed-up distill LoRA. Do NOT use with `sulphur_distil_*` models |
| `ltx-2.3-...-lora-1.1_condsafe.safetensors` | Standard LTX 2.3 models | `condsafe` variant is most stable |
| `ltx-2.3-22b-ic-lora-hdr-scene-emb.safetensors` | Already present ✓ | IC-LoRA for HDR scene embedding |

---

## VRAM limits at 12 GB (from the video)

| Resolution | Max clip length |
|------------|----------------|
| 1080p | ~8 seconds |
| 1600×900 | 10–12 seconds |
| 720p | longer clips |

Width and height must be **divisible by 32**.

---

## Scripts

| Script | Purpose |
|--------|---------|
| `ai_comfyui_install.sh` | Main ComfyUI installer |
| `ai_comfyui_postinstall.sh` | Installs custom nodes + writes `extra_model_paths.yaml` |
| `ai_comfyui_download_ltxdirector.sh` | Downloads all models above (resumable, safe to re-run) |

Start ComfyUI after install with: `ai_comfy`

---

## Source URLs (for re-downloading)

```bash
# Sulphur 2 GGUFs
https://huggingface.co/vantagewithai/Sulphur-2-Base-GGUF/resolve/main/sulphur_dev-Q5_K_M.gguf
https://huggingface.co/vantagewithai/Sulphur-2-Base-GGUF/resolve/main/sulphur_dev-Q6_K.gguf

# LoRAs
https://huggingface.co/SulphurAI/Sulphur-2-base/resolve/main/sulphur_lora_rank_768.safetensors
https://huggingface.co/Kijai/LTX2.3_comfy/resolve/main/loras/ltx-2.3-22b-distilled-lora-1.1_fro90_ceil72_condsafe.safetensors

# Text encoders
https://huggingface.co/Comfy-Org/ltx-2/resolve/main/split_files/text_encoders/gemma_3_12B_it_fp4_mixed.safetensors
https://huggingface.co/Kijai/LTX2.3_comfy/resolve/main/text_encoders/ltx-2.3_text_projection_bf16.safetensors

# VAE
https://huggingface.co/Kijai/LTX2.3_comfy/resolve/main/vae/LTX23_video_vae_bf16.safetensors
https://huggingface.co/Kijai/LTX2.3_comfy/resolve/main/vae/taeltx2_3.safetensors

# Upscaler
https://huggingface.co/Lightricks/LTX-2.3/resolve/main/ltx-2.3-spatial-upscaler-x2-1.1.safetensors

# Workflow JSONs (WhatDreamsCost repo)
https://raw.githubusercontent.com/WhatDreamsCost/WhatDreamsCost-ComfyUI/main/example_workflows/LTX%20Director%20Example%20Workflow%20(Fixed).json
https://raw.githubusercontent.com/WhatDreamsCost/WhatDreamsCost-ComfyUI/main/example_workflows/LTX%20Director%20Example%20Workflow%20Subgraphs%20v2.json
https://raw.githubusercontent.com/WhatDreamsCost/WhatDreamsCost-ComfyUI/main/example_workflows/LTX%20I2V%20First%20Last%20Frame%202%20Stage%20Workflow%20v6.json
https://raw.githubusercontent.com/WhatDreamsCost/WhatDreamsCost-ComfyUI/main/example_workflows/LTX%20I2V%20First%20Last%20Frame%203%20Stage%20Workflow%20v6.json
https://raw.githubusercontent.com/WhatDreamsCost/WhatDreamsCost-ComfyUI/main/example_workflows/LTX%20I2V%20FFLF%20Custom%20Audio%20Workflow%20-%20SUPPORTS%20LATEST%20COMFYUI%20VERSION%20-%20V3.json
```

---

## Reference

- Video: https://www.youtube.com/watch?v=aCRzCyn5yIE
- WhatDreamsCost node repo: https://github.com/WhatDreamsCost/WhatDreamsCost-ComfyUI
- Sulphur 2 GGUF repo: https://huggingface.co/vantagewithai/Sulphur-2-Base-GGUF
- Kijai LTX 2.3 comfy repo: https://huggingface.co/Kijai/LTX2.3_comfy
- Awesome LTX2 model list: https://github.com/wildminder/awesome-ltx2
