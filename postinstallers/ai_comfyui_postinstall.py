#!/usr/bin/env python3
# =============================================================================
# ai_comfyui_postinstall.py  —  ComfyUI workflow pack installer
# =============================================================================
# PURPOSE:
#   Read comfyui_workflows.ini, present an interactive picker, then for each
#   selected workflow pack:
#     1. Clone or update custom nodes into ComfyUI custom_nodes/
#     2. Download missing model files into the shared resource tree
#     3. Hardlink models from shared tree into ComfyUI's own models/ dirs
#     4. Symlink workflow JSONs into ComfyUI user workflows dir
#     5. Record everything in ai_installer.json under "comfyui_workflows"
#
# Also installs ComfyUI-Manager (comfyui_manager pip package) on first run
# and adds --enable-manager to config.comfyui_flags in ai_installer.json.
#
# REPEATABILITY:
#   Safe to re-run at any time. Files already present are skipped (not
#   re-downloaded). Nodes already cloned are git-pulled. Hardlinks and
#   symlinks are recreated if missing. State in ai_installer.json is updated
#   on every run.
#
#   If the ini file is lost, `ai_tools comfyui reinstall <id>` reads the
#   JSON record and rebuilds from that — no ini required for reinstall.
#
# USAGE (via ai_tools dispatch):
#   ai_tools comfyui setup                    — interactive picker
#   ai_tools comfyui reinstall <workflow-id>  — reinstall from JSON record
#   ai_tools comfyui status                   — show installed workflow state
#
# USAGE (direct):
#   python3 ai_comfyui_postinstall.py setup
#   python3 ai_comfyui_postinstall.py reinstall ltx-director-sulphur
#   python3 ai_comfyui_postinstall.py status
#
# PRE:  ComfyUI installed (ai_comfyui_install.sh run successfully).
#       ai_config.sh / ai_config.py readable (for paths and JSON gateway).
#       comfyui_workflows.ini present in AI_Tools/ (for setup; not for reinstall).
# POST: Selected workflow packs installed; ai_installer.json updated.
# =============================================================================

import sys
import os
import json
import shutil
import subprocess
import curses
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone

# =============================================================================
# sys.path — ensure pylib is importable
# This script lives in AI_Tools/postinstallers/ — pylib is one level up.
# =============================================================================
_HERE      = Path(__file__).parent.resolve()   # .../AI_Tools/postinstallers/
_AI_TOOLS  = _HERE.parent                       # .../AI_Tools/
_PYLIB     = _AI_TOOLS / "pylib"
if str(_PYLIB) not in sys.path:
    sys.path.insert(0, str(_PYLIB))

import ai_config  # sole JSON gateway

# Point ai_config at the correct JSON file — one level up in AI_Tools/
os.environ.setdefault("AI_INSTALLER_JSON", str(_AI_TOOLS / "ai_installer.json"))

# =============================================================================
# Paths — derived from ai_installer.json config (same pattern as ai_installer.py)
# =============================================================================
def _get_paths():
    """
    Purpose: Resolve all runtime paths from config and environment.
    Returns dict of path strings. Raises RuntimeError if ComfyUI not installed.
    """
    # AI_SHARED_ROOT — base of the shared video resource tree
    shared_root = ai_config.load_all().get("config", {}).get("shared_root") or "/mnt/BACKUP_4.0_TB/AI-Shared-Resources"
    shared_video = Path(shared_root) / "video"

    # ComfyUI install location
    _cfg      = ai_config.load_all().get("config", {})
    _target   = _cfg.get("active_target") or str(_AI_TOOLS.parent)
    _appsub   = _cfg.get("apps_subdir") or "AI_Apps"
    ai_apps   = str(Path(_target) / _appsub)
    app_dir   = Path(ai_apps) / "ComfyUI"
    venv_dir = app_dir / "venv"
    venv_pip = venv_dir / "bin" / "pip"

    if not app_dir.exists():
        raise RuntimeError(
            f"ComfyUI not found at {app_dir}\n"
            f"Run the main installer first: ai_tools install comfyui"
        )
    if not (venv_dir / "bin" / "python").exists():
        raise RuntimeError(
            f"ComfyUI venv not found at {venv_dir}\n"
            f"Run the main installer first: ai_tools install comfyui"
        )

    return {
        "shared_root":    str(shared_root),
        "shared_video":   str(shared_video),
        "app_dir":        str(app_dir),
        "venv_dir":       str(venv_dir),
        "venv_pip":       str(venv_pip),
        "custom_nodes":   str(app_dir / "custom_nodes"),
        "models_dir":     str(app_dir / "models"),
        "user_workflows": str(app_dir / "user" / "default" / "workflows"),
        "yaml_file":      str(app_dir / "extra_model_paths.yaml"),  # obsolete — scheduled for removal
        "ini_file":       str(_HERE / "comfyui_workflows.ini"),  # beside script in postinstallers/
    }

# =============================================================================
# ComfyUI model-type key → subdir under ComfyUI models/
# Used when hardlinking shared tree files into ComfyUI's own models/ dirs.
# =============================================================================
COMFYUI_MODEL_SUBDIRS = {
    "checkpoints":           "checkpoints",
    "diffusion_models":      "diffusion_models",
    "vae":                   "vae",
    "text_encoders":         "text_encoders",
    "clip":                  "text_encoders",
    "loras":                 "loras",
    "unet":                  "unet",
    "controlnet":            "controlnet",
    "latent_upscale_models": "latent_upscale_models",
}

# Which yaml key to use for each shared_dest path fragment.
# Postinstall uses this to decide where to hardlink a model inside ComfyUI.
DEST_TO_YAML_KEY = {
    "video/Models/":         "diffusion_models",
    "video/VAE/":            "vae",
    "video/TextEncoders/":   "text_encoders",
    "video/LoRAs/":          "loras",
    "video/upscale_models/": "latent_upscale_models",
}

# =============================================================================
# INI PARSER
# =============================================================================
def parse_ini(ini_path: str) -> dict:
    """
    Purpose: Parse comfyui_workflows.ini into a dict keyed by workflow id.
    Pre:  ini_path exists and is readable.
    Post: Returns {workflow_id: {name, purpose, nodes, models, workflows, yaml}}
          Raises FileNotFoundError or ValueError on parse error.

    Format handled:
      :workflow <id>
      :name <display name>
      :purpose
          free text lines
      :nodes
          dirname  url
      :models
          filename  url  shared_dest
      :workflows
          filename  url
      :yaml
          comfyui_key  shared_subdir
      # comment lines and blank lines ignored everywhere
    """
    path = Path(ini_path)
    if not path.exists():
        raise FileNotFoundError(f"Workflow ini not found: {ini_path}")

    workflows = {}
    current_id   = None
    current_wf   = None
    current_sect = None  # "nodes" | "models" | "workflows" | "yaml" | "purpose"

    for lineno, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()

        # Skip comments and blanks
        if not line or line.startswith("#"):
            continue

        # Section headers
        if line.startswith(":workflow "):
            current_id = line.split(None, 1)[1].strip()
            current_wf = {
                "name":      current_id,
                "purpose":   [],
                "nodes":     [],
                "models":    [],
                "workflows": [],
                "yaml":      {},
            }
            workflows[current_id] = current_wf
            current_sect = None
            continue

        if current_wf is None:
            continue  # lines before first :workflow block

        if line.startswith(":name "):
            current_wf["name"] = line.split(None, 1)[1].strip()
            current_sect = None
            continue

        if line in (":purpose", ":nodes", ":models", ":workflows", ":yaml"):
            current_sect = line[1:]
            continue

        # Data lines — parse based on current section
        if current_sect == "purpose":
            current_wf["purpose"].append(line)

        elif current_sect == "nodes":
            parts = line.split()
            if len(parts) >= 2:
                current_wf["nodes"].append({
                    "dirname": parts[0],
                    "url":     parts[1],
                })

        elif current_sect == "models":
            parts = line.split()
            if len(parts) >= 3:
                current_wf["models"].append({
                    "filename":    parts[0],
                    "url":         parts[1],
                    "shared_dest": parts[2],
                })

        elif current_sect == "workflows":
            parts = line.split()
            if len(parts) >= 2:
                # filename may contain spaces — everything except last token is filename
                current_wf["workflows"].append({
                    "filename": " ".join(parts[:-1]),
                    "url":      parts[-1],
                })

        elif current_sect == "yaml":
            parts = line.split()
            if len(parts) >= 2:
                current_wf["yaml"][parts[0]] = parts[1]

    return workflows

# =============================================================================
# CURSES PICKER
# =============================================================================
def pick_workflows(workflows: dict) -> list:
    """
    Purpose: Present an interactive curses picker for workflow selection.
    Pre:  workflows is a non-empty dict from parse_ini().
    Post: Returns list of selected workflow ids. Empty list = user cancelled.
    """
    ids    = list(workflows.keys())
    names  = [workflows[i]["name"] for i in ids]
    sel    = [False] * len(ids)

    def _draw(stdscr, cursor):
        stdscr.clear()
        h, w = stdscr.getmaxyx()
        stdscr.addstr(0, 0, "ComfyUI Workflow Pack Installer", curses.A_BOLD)
        stdscr.addstr(1, 0, "─" * min(w - 1, 60))
        stdscr.addstr(2, 0, "SPACE/ENTER toggle  ↑↓ move  A select all  N none  Q/ESC quit  R run")
        stdscr.addstr(3, 0, "─" * min(w - 1, 60))

        for i, (wf_id, name) in enumerate(zip(ids, names)):
            row = 4 + i
            if row >= h - 2:
                break
            marker  = "[x]" if sel[i] else "[ ]"
            line    = f"  {marker}  {name}  ({wf_id})"
            attr    = curses.A_REVERSE if i == cursor else curses.A_NORMAL
            stdscr.addstr(row, 0, line[:w - 1], attr)

        status = f"  {sum(sel)} of {len(ids)} selected"
        stdscr.addstr(min(4 + len(ids) + 1, h - 1), 0, status)
        stdscr.refresh()

    def _run(stdscr):
        curses.curs_set(0)
        cursor = 0
        while True:
            _draw(stdscr, cursor)
            key = stdscr.getch()
            if key in (ord('q'), ord('Q'), 27):   # Q or ESC
                return []
            elif key in (ord('r'), ord('R'), 10):  # R or Enter
                return [ids[i] for i, s in enumerate(sel) if s]
            elif key in (ord('a'), ord('A')):
                sel[:] = [True] * len(sel)
            elif key in (ord('n'), ord('N')):
                sel[:] = [False] * len(sel)
            elif key == curses.KEY_UP:
                cursor = max(0, cursor - 1)
            elif key == curses.KEY_DOWN:
                cursor = min(len(ids) - 1, cursor + 1)
            elif key in (ord(' '), ):
                sel[cursor] = not sel[cursor]

    return curses.wrapper(_run)

# =============================================================================
# HELPERS — output
# =============================================================================
def _step(msg):  print(f"\n==> {msg}")
def _good(msg):  print(f"  \033[32m✔\033[0m  {msg}")
def _warn(msg):  print(f"  WARN: {msg}")
def _info(msg):  print(f"  {msg}")
def _skip(msg):  print(f"  --   {msg} (already present)")

# =============================================================================
# HELPER — run subprocess
# =============================================================================
def _run(cmd: list, cwd=None, check=True) -> bool:
    """
    Purpose: Run a subprocess command, print output live.
    Returns True on success, False on failure (when check=False).
    """
    try:
        subprocess.run(cmd, cwd=cwd, check=check)
        return True
    except subprocess.CalledProcessError as e:
        _warn(f"Command failed: {' '.join(cmd)}: {e}")
        return False

# =============================================================================
# CLONE / UPDATE NODE
# =============================================================================
def install_node(node: dict, custom_nodes_dir: str, venv_pip: str) -> dict:
    """
    Purpose: Clone a custom node if not present, git-pull if it is,
      then install its pip requirements.
    Pre:  custom_nodes_dir exists, venv_pip is the venv pip binary.
    Post: Node repo present and up to date; requirements installed.
    Returns status dict for JSON record.
    """
    dirname  = node["dirname"]
    url      = node["url"]
    node_dir = Path(custom_nodes_dir) / dirname
    status   = {"url": url, "path": str(node_dir), "status": "unknown",
                "updated_at": _now()}

    if (node_dir / ".git").exists():
        _info(f"{dirname}: already installed — pulling")
        ok = _run(["git", "-C", str(node_dir), "pull", "--quiet"], check=False)
        status["status"] = "updated" if ok else "pull_failed"
    else:
        _info(f"{dirname}: cloning")
        ok = _run(["git", "clone", "--quiet", url, str(node_dir)], check=False)
        status["status"] = "cloned" if ok else "clone_failed"

    if not ok:
        _warn(f"{dirname}: git operation failed — non-fatal, continuing")
        return status

    # Install requirements
    req_file = None
    for f in ("requirements.txt", "requirements_versions.txt"):
        candidate = node_dir / f
        if candidate.exists():
            req_file = candidate
            break

    if req_file:
        ok = _run([venv_pip, "install", "-r", str(req_file), "--quiet"], check=False)
        if ok:
            _good(f"{dirname}: requirements installed")
            status["requirements"] = "installed"
        else:
            _warn(f"{dirname}: requirements had errors — non-fatal")
            status["requirements"] = "errors"
    else:
        _info(f"{dirname}: no requirements file")
        status["requirements"] = "none"

    return status

# =============================================================================
# DOWNLOAD MODEL
# =============================================================================
def download_model(model: dict, shared_root: str) -> dict:
    """
    Purpose: Download a model file into the shared resource tree if not present.
    Pre:  shared_root exists and is writable; model has filename, url, shared_dest.
    Post: File present at dest_path. Returns status dict for JSON record.
    """
    filename   = model["filename"]
    url        = model["url"]
    shared_dest = model["shared_dest"]  # e.g. "video/Models/"

    dest_dir  = Path(shared_root) / shared_dest
    dest_path = dest_dir / filename

    record = {
        "url":         url,
        "shared_dest": shared_dest,
        "shared_path": str(dest_path),
        "size_bytes":  None,
        "status":      "unknown",
        "downloaded_at": None,
        "hardlinked_to": None,
    }

    dest_dir.mkdir(parents=True, exist_ok=True)

    if dest_path.exists():
        size = dest_path.stat().st_size
        _skip(f"{filename} ({_fmt_size(size)})")
        record["status"]     = "present"
        record["size_bytes"] = size
        return record

    _info(f"Downloading: {filename}")
    _info(f"  → {dest_path}")

    tmp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")
    try:
        def _progress(block_count, block_size, total_size):
            if total_size > 0:
                pct = min(100, block_count * block_size * 100 // total_size)
                done = min(40, pct * 40 // 100)
                bar  = "=" * done + "-" * (40 - done)
                print(f"\r    [{bar}] {pct}%", end="", flush=True)

        urllib.request.urlretrieve(url, str(tmp_path), reporthook=_progress)
        print()  # newline after progress bar
        tmp_path.rename(dest_path)
        size = dest_path.stat().st_size
        _good(f"{filename} downloaded ({_fmt_size(size)})")
        record["status"]        = "downloaded"
        record["size_bytes"]    = size
        record["downloaded_at"] = _now()

    except Exception as e:
        _warn(f"Download failed for {filename}: {e}")
        if tmp_path.exists():
            tmp_path.unlink()
        record["status"] = "download_failed"

    return record

# =============================================================================
# HARDLINK MODEL INTO COMFYUI
# =============================================================================
def hardlink_model(filename: str, shared_path: str, shared_dest: str,
                   models_dir: str) -> str | None:
    """
    Purpose: Hardlink a model from the shared tree into ComfyUI's own models/ dir.
      Hardlinks are zero-cost (same inode) when source and dest are on the
      same filesystem. If different filesystems, falls back to symlink.
    Pre:  shared_path exists. models_dir is ComfyUI's models/ directory.
    Post: File accessible in ComfyUI models/ dir. Returns link path or None on fail.
    """
    yaml_key = DEST_TO_YAML_KEY.get(shared_dest)
    if not yaml_key:
        _warn(f"No yaml key mapping for shared_dest '{shared_dest}' — skipping hardlink")
        return None

    comfy_subdir = COMFYUI_MODEL_SUBDIRS.get(yaml_key)
    if not comfy_subdir:
        _warn(f"No ComfyUI subdir for yaml key '{yaml_key}' — skipping hardlink")
        return None

    link_dir  = Path(models_dir) / comfy_subdir
    link_path = link_dir / filename
    src_path  = Path(shared_path)

    if not src_path.exists():
        _warn(f"Source not found for hardlink: {src_path}")
        return None

    link_dir.mkdir(parents=True, exist_ok=True)

    if link_path.exists():
        # Check if it's already the same inode (already hardlinked)
        if link_path.stat().st_ino == src_path.stat().st_ino:
            _skip(f"hardlink {comfy_subdir}/{filename}")
            return str(link_path)
        else:
            # Exists but different inode — remove and relink
            link_path.unlink()

    try:
        os.link(str(src_path), str(link_path))
        _good(f"hardlinked → {comfy_subdir}/{filename}")
        return str(link_path)
    except OSError:
        # Cross-filesystem — fall back to symlink
        try:
            link_path.symlink_to(src_path)
            _good(f"symlinked → {comfy_subdir}/{filename} (cross-fs)")
            return str(link_path)
        except OSError as e:
            _warn(f"Link failed for {filename}: {e}")
            return None

# =============================================================================
# WORKFLOW JSON — download and symlink
# =============================================================================
def install_workflow_json(wf_file: dict, shared_video: str,
                          user_workflows_dir: str) -> dict:
    """
    Purpose: Download a workflow JSON to the shared ComfyWorkflows/ dir if
      not present, then symlink it into ComfyUI's user workflows dir.
    Pre:  shared_video exists. user_workflows_dir will be created if needed.
    Post: JSON present in shared tree; symlinked into ComfyUI. Returns status dict.
    """
    filename = wf_file["filename"]
    url      = wf_file["url"]

    shared_dir  = Path(shared_video) / "ComfyWorkflows"
    shared_path = shared_dir / filename
    link_dir    = Path(user_workflows_dir) / "AI-Shared"
    link_path   = link_dir / filename

    record = {
        "url":         url,
        "shared_path": str(shared_path),
        "status":      "unknown",
        "symlinked_to": str(link_path),
    }

    shared_dir.mkdir(parents=True, exist_ok=True)
    link_dir.mkdir(parents=True, exist_ok=True)

    # Download if missing
    if not shared_path.exists():
        _info(f"Downloading workflow: {filename}")
        try:
            urllib.request.urlretrieve(url, str(shared_path))
            _good(f"workflow downloaded: {filename}")
            record["status"] = "downloaded"
        except Exception as e:
            _warn(f"Workflow download failed: {filename}: {e}")
            record["status"] = "download_failed"
            return record
    else:
        _skip(f"workflow {filename}")
        record["status"] = "present"

    # Symlink into ComfyUI user workflows
    if link_path.exists() or link_path.is_symlink():
        if link_path.is_symlink() and link_path.resolve() == shared_path.resolve():
            _skip(f"workflow symlink {filename}")
            return record
        link_path.unlink()

    try:
        link_path.symlink_to(shared_path)
        _good(f"workflow symlinked → user/workflows/AI-Shared/{filename}")
    except OSError as e:
        _warn(f"Workflow symlink failed: {filename}: {e}")

    return record

# =============================================================================
# WRITE extra_model_paths.yaml
# =============================================================================
def write_yaml(yaml_entries: dict, shared_root: str, yaml_file: str):
    """
    Purpose: Write (or merge and overwrite) extra_model_paths.yaml from the
      accumulated yaml entries of all installed workflow packs.
      Backs up the existing file before overwriting.
    Pre:  yaml_entries is a dict of {comfyui_key: shared_subdir}.
          shared_root is the AI-Shared-Resources base path.
    Post: yaml_file written; old file backed up as .bak.
    """
    yaml_path = Path(yaml_file)
    if yaml_path.exists():
        bak = yaml_path.with_suffix(".yaml.bak")
        shutil.copy2(yaml_path, bak)
        _info(f"Backed up existing yaml → {bak.name}")

    lines = [
        "# extra_model_paths.yaml",
        "# Generated by ai_comfyui_postinstall.py — do not hand-edit.",
        "# Edit comfyui_workflows.ini and re-run: ai_tools comfyui setup",
        f"# Last written: {_now()}",
        "",
        "comfyui:",
        f"  base_path: {shared_root}",
        "",
    ]

    for key, subdir in sorted(yaml_entries.items()):
        # Strip leading "video/" from subdir for yaml (base_path already covers it)
        rel = subdir.removeprefix("video/")
        lines.append(f"  {key}: {rel}")

    yaml_path.write_text("\n".join(lines) + "\n")
    _good(f"extra_model_paths.yaml written → {yaml_file}")

# =============================================================================
# UTILITIES
# =============================================================================
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"

# =============================================================================
# JSON STATE — read / write via ai_config gateway
# =============================================================================
def _load_wf_state() -> dict:
    return ai_config.load_all().get("comfyui_workflows", {})

def _save_wf_state(state: dict):
    data = ai_config.load_all()
    data["comfyui_workflows"] = state
    ai_config.save_all(data)

# =============================================================================
# INSTALL ONE WORKFLOW PACK
# =============================================================================
def install_workflow_pack(wf_id: str, wf_def: dict, paths: dict):
    """
    Purpose: Install a single workflow pack end-to-end.
    Pre:  ComfyUI present, paths resolved, wf_def from parse_ini().
    Post: Nodes cloned, models downloaded+hardlinked, yaml updated, JSON updated.
    """
    _step(f"Installing: {wf_def['name']} ({wf_id})")

    state      = _load_wf_state()
    wf_record  = state.get(wf_id, {
        "status":       "installing",
        "installed_at": _now(),
        "name":         wf_def["name"],
        "purpose":      " ".join(wf_def["purpose"]),
        "nodes":        {},
        "models":       {},
        "workflows":    {},
        "yaml_written": False,
    })
    wf_record["status"]     = "installing"
    wf_record["updated_at"] = _now()

    # ── 1. Custom nodes ──────────────────────────────────────────────────────
    _step("Custom nodes")
    for node in wf_def["nodes"]:
        node_status = install_node(node, paths["custom_nodes"], paths["venv_pip"])
        wf_record["nodes"][node["dirname"]] = node_status

    apply_patches(paths)

    # ── 2. Models — download + hardlink ──────────────────────────────────────
    _step("Models")
    for model in wf_def["models"]:
        fname = model["filename"]

        # Download into shared tree
        dl_record = download_model(model, paths["shared_root"])

        # Hardlink into ComfyUI models/ dir
        if dl_record["status"] in ("present", "downloaded"):
            link = hardlink_model(
                fname,
                dl_record["shared_path"],
                model["shared_dest"],
                paths["models_dir"],
            )
            dl_record["hardlinked_to"] = link

        wf_record["models"][fname] = dl_record

    # ── 3. Workflow JSONs ─────────────────────────────────────────────────────
    _step("Workflow JSONs")
    for wf_file in wf_def["workflows"]:
        wf_status = install_workflow_json(
            wf_file,
            paths["shared_video"],
            paths["user_workflows"],
        )
        wf_record["workflows"][wf_file["filename"]] = wf_status

    # ── 4. extra_model_paths.yaml — skipped ──────────────────────────────────
    # Models are hardlinked into ComfyUI's own models/ dirs (step 2 above).
    # We leave extra_model_paths.yaml alone — app configs are not our concern.
    wf_record["yaml_written"] = False

    # ── 5. Save state ─────────────────────────────────────────────────────────
    wf_record["status"] = "installed"
    state[wf_id] = wf_record
    _save_wf_state(state)
    _good(f"{wf_def['name']} — recorded in ai_installer.json")

# =============================================================================
# REINSTALL FROM JSON RECORD
# =============================================================================
def reinstall_from_record(wf_id: str, paths: dict):
    """
    Purpose: Reinstall a workflow pack using only the JSON record — no ini needed.
      Reconstructs the wf_def from the stored record and runs install_workflow_pack.
    Pre:  wf_id exists in ai_installer.json comfyui_workflows.
    Post: Pack reinstalled; record updated.
    """
    state = _load_wf_state()
    if wf_id not in state:
        print(f"ERROR: No record for workflow '{wf_id}' in ai_installer.json")
        print("  Run 'ai_tools comfyui setup' with the ini file to install it first.")
        sys.exit(1)

    rec = state[wf_id]

    # Reconstruct wf_def from record
    wf_def = {
        "name":    rec.get("name", wf_id),
        "purpose": [rec.get("purpose", "")],
        "nodes": [
            {"dirname": d, "url": info["url"]}
            for d, info in rec.get("nodes", {}).items()
        ],
        "models": [
            {"filename": f, "url": info["url"], "shared_dest": info["shared_dest"]}
            for f, info in rec.get("models", {}).items()
        ],
        "workflows": [
            {"filename": f, "url": info["url"]}
            for f, info in rec.get("workflows", {}).items()
        ],
        "yaml": rec.get("yaml_entries", {}),
    }

    install_workflow_pack(wf_id, wf_def, paths)

# =============================================================================
# STATUS
# =============================================================================
def show_status(paths: dict):
    """
    Purpose: Print installed workflow state from ai_installer.json.
    """
    state = _load_wf_state()
    if not state:
        print("No ComfyUI workflow packs recorded in ai_installer.json.")
        return

    print("\nComfyUI Workflow Packs\n" + "─" * 40)
    for wf_id, rec in state.items():
        status = rec.get("status", "unknown")
        name   = rec.get("name", wf_id)
        updated = rec.get("updated_at", rec.get("installed_at", "?"))
        print(f"\n  {name} ({wf_id})")
        print(f"    Status:  {status}  [{updated}]")

        models  = rec.get("models", {})
        present = sum(1 for m in models.values() if m.get("status") in ("present", "downloaded"))
        missing = sum(1 for m in models.values() if m.get("status") not in ("present", "downloaded"))
        print(f"    Models:  {present} present, {missing} missing")

        nodes = rec.get("nodes", {})
        n_ok  = sum(1 for n in nodes.values() if n.get("status") in ("cloned", "updated"))
        print(f"    Nodes:   {n_ok}/{len(nodes)} installed")

        if missing:
            print("    Missing models:")
            for fname, info in models.items():
                if info.get("status") not in ("present", "downloaded"):
                    print(f"      - {fname}")

# =============================================================================
# COMFYUI MANAGER
# =============================================================================
# =============================================================================
# COMFYUI MANAGER
# =============================================================================
def install_manager(paths: dict) -> None:
    """
    Purpose: Install comfyui_manager and required extras into the ComfyUI venv,
      and record --enable-manager in config.comfyui_flags so the runner picks it up.
    Pre:  ComfyUI venv present, manager_requirements.txt in app_dir.
    Post: comfyui_manager, matrix-nio, onnx installed; ai_installer.json updated.
    Idempotent — safe to re-run.
    """
    _step("ComfyUI Manager")
    app_dir  = Path(paths["app_dir"])
    venv_pip = paths["venv_pip"]
    req_file = app_dir / "manager_requirements.txt"

    if not req_file.exists():
        _warn(f"manager_requirements.txt not found at {req_file} — skipping")
        return

    # Check if already installed
    try:
        result = subprocess.run(
            [venv_pip, "show", "comfyui_manager"],
            capture_output=True, text=True
        )
        already = result.returncode == 0
    except OSError:
        already = False

    if already:
        _info("comfyui_manager already installed")
    else:
        _info("Installing comfyui_manager...")
        try:
            subprocess.run(
                [venv_pip, "install", "-r", str(req_file)],
                check=True
            )
            _good("comfyui_manager installed")
        except subprocess.CalledProcessError as e:
            _warn(f"comfyui_manager install failed (non-fatal): {e}")
            return

    # Extra packages needed by manager features and custom nodes
    # matrix-nio: ComfyUI-Manager matrix sharing feature
    # onnx:       WanVideoWrapper FantasyPortrait nodes
    _pip_install_if_missing(venv_pip, "matrix-nio", "matrix_nio")
    # _pip_install_if_missing(venv_pip, "onnx",       "onnx")
    _pip_install_if_missing(venv_pip, "onnx",        "onnx")
    _pip_install_if_missing(venv_pip, "onnxruntime",  "onnxruntime")
    # Record --enable-manager in config.comfyui_flags if not already there
    found, current = ai_config.get("config", "comfyui_flags")
    if not found or "--enable-manager" not in current:
        ai_config.set("config", "comfyui_flags", "--enable-manager")
        _good("--enable-manager added to config.comfyui_flags")
    else:
        _info("--enable-manager already in config.comfyui_flags")


def _pip_install_if_missing(venv_pip: str, pkg: str, import_name: str) -> None:
    """Install a pip package if not already present. Non-fatal on failure."""
    try:
        result = subprocess.run(
            [venv_pip, "show", import_name],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            _info(f"{pkg} already installed")
            return
    except OSError:
        pass

    _info(f"Installing {pkg}...")
    try:
        subprocess.run([venv_pip, "install", pkg], check=True)
        _good(f"{pkg} installed")
    except subprocess.CalledProcessError as e:
        _warn(f"{pkg} install failed (non-fatal): {e}")

# =============================================================================
# SOURCE PATCHES — applied after every custom node clone/pull
# =============================================================================
# Patch strings use exact content; idempotent check is "before not in file".
# Add more entries to apply_patches() as needed.

_KORNIA_BEFORE = (
    "from kornia.geometry.transform.pyramid import (\n"
    "    PyrUp,\n"
    "    build_laplacian_pyramid,\n"
    "    build_pyramid,\n"
    "    find_next_powerof_two,\n"
    "    is_powerof_two,\n"
    "    pad,\n"
    ")"
)
_KORNIA_AFTER = (
    "from kornia.geometry.transform.pyramid import (\n"
    "    PyrUp,\n"
    "    build_laplacian_pyramid,\n"
    "    build_pyramid,\n"
    "    find_next_powerof_two,\n"
    "    is_powerof_two,\n"
    ")\n"
    "from torch.nn.functional import pad  # kornia removed pad in 0.8.3"
)


def apply_patches(paths: dict) -> None:
    """
    Apply post-git-pull source patches to custom nodes. Idempotent, non-fatal.
    Called after every node install/update so patches survive git pull.
    """
    _step("Applying patches")

    # ComfyUI-LTXVideo/pyramid_blending.py — kornia removed pad in 0.8.3
    target = (Path(paths["custom_nodes"])
              / "ComfyUI-LTXVideo" / "pyramid_blending.py")
    if not target.exists():
        _info("pyramid_blending.py: not found (ComfyUI-LTXVideo not installed — skip)")
        return

    content = target.read_text()
    if _KORNIA_BEFORE not in content:
        _info("pyramid_blending.py: already patched")
        return

    target.write_text(content.replace(_KORNIA_BEFORE, _KORNIA_AFTER, 1))
    _good("pyramid_blending.py: patched (kornia pad → torch.nn.functional)")


# =============================================================================
# MAIN
# =============================================================================
def main():
    args = sys.argv[1:]
    cmd  = args[0] if args else "setup"

    try:
        paths = _get_paths()
    except RuntimeError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    if not Path(paths["shared_video"]).exists():
        print(f"ERROR: Shared video path not found: {paths['shared_video']}")
        print("  Is the backup drive mounted?")
        sys.exit(1)

    # ── status ───────────────────────────────────────────────────────────────
    if cmd == "status":
        show_status(paths)
        return

    # ── reinstall <id> ───────────────────────────────────────────────────────
    if cmd == "reinstall":
        if len(args) < 2:
            print("Usage: ai_tools comfyui reinstall <workflow-id>")
            state = _load_wf_state()
            if state:
                print("Available workflow ids:")
                for wf_id in state:
                    print(f"  {wf_id}")
            sys.exit(1)
        reinstall_from_record(args[1], paths)
        return

    # ── setup ────────────────────────────────────────────────────────────────
    if cmd == "setup":
        # Manager first — independent of workflow packs
        install_manager(paths)

        ini_path = paths["ini_file"]
        try:
            workflows = parse_ini(ini_path)
        except FileNotFoundError:
            print(f"ERROR: Workflow ini not found: {ini_path}")
            print("  Create comfyui_workflows.ini in AI_Tools/ first.")
            sys.exit(1)

        if not workflows:
            print("No workflow packs found in ini file.")
            sys.exit(0)

        selected = pick_workflows(workflows)
        if not selected:
            print("No workflows selected — nothing to do.")
            return

        print(f"\nInstalling {len(selected)} workflow pack(s)...")
        for wf_id in selected:
            install_workflow_pack(wf_id, workflows[wf_id], paths)

        print("\n" + "=" * 60)
        print("  ComfyUI workflow setup complete.")
        print(f"  Installed: {', '.join(selected)}")
        print(f"  Start ComfyUI: ai_tools run comfyui")
        print("=" * 60)
        return

    print(f"Unknown command: {cmd}")
    print("Usage: ai_tools comfyui [setup|reinstall <id>|status]")
    sys.exit(1)


if __name__ == "__main__":
    main()
