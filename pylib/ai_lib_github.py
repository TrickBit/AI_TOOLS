#!/usr/bin/env python3
# =============================================================================
# ai_lib_github.py  —  GitHub API comms for the AI installer stack
# =============================================================================
# All GitHub API calls for the ai_installer suite go through this module.
# Nothing else in the stack calls the GitHub API directly.
#
# Called by:
#   ai_lib_apps.py      — get_required_python(), get_latest_app_version()
#   ai_lib_optional.py  — get_latest_release(), get_release_assets(), wheel_available()
#   ai_installer.py     — get_latest_app_version() for menu display
#
# Returns plain values (str, list, bool) — no JSON writes, no side effects.
#
# Auth: token read from $GITHUB_TOKEN env var.
#   Authenticated:   5000 req/hour
#   Unauthenticated:   60 req/hour (adequate for low-volume interactive use)
#
# Requires: requests>=2.28.0
# Present in Debian 13 system Python — no venv needed.
# If missing: pip install --break-system-packages requests
# =============================================================================

import os
import sys
import requests

# ---------------------------------------------------------------------------
# GitHub API base
# ---------------------------------------------------------------------------

_API_BASE = "https://api.github.com"


def _headers() -> dict:
    """Build request headers. Adds auth token if available."""
    h = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _get(url: str) -> dict | list | None:
    """
    GET a GitHub API URL. Returns parsed JSON on success.
    Returns None on any error (network, auth, rate limit, 404).
    Errors reported to stderr — caller decides how to handle None.
    """
    try:
        resp = requests.get(url, headers=_headers(), timeout=10)
    except requests.exceptions.RequestException as e:
        print(f"[ai_lib_github] network error: {e}", file=sys.stderr)
        return None

    if resp.status_code == 403:
        # Rate limit or auth problem — surface clearly
        remaining = resp.headers.get("X-RateLimit-Remaining", "?")
        print(
            f"[ai_lib_github] 403 from {url} — rate limit remaining: {remaining}",
            file=sys.stderr,
        )
        return None

    if resp.status_code == 404:
        print(f"[ai_lib_github] 404 not found: {url}", file=sys.stderr)
        return None

    if not resp.ok:
        print(
            f"[ai_lib_github] HTTP {resp.status_code} from {url}",
            file=sys.stderr,
        )
        return None

    try:
        return resp.json()
    except ValueError as e:
        print(f"[ai_lib_github] JSON parse error from {url}: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# App repo map
# ---------------------------------------------------------------------------

# Maps installer app keys to GitHub owner/repo strings.
# Update here when repos change — one place, picked up everywhere.
_APP_REPOS = {
    "automatic":      "AUTOMATIC1111/stable-diffusion-webui",
    "wan2gp":         "deepbeepmeep/Wan2GP",
    "frampackstudio": "lllyasviel/FramePack",
    "invokeai":       "invoke-ai/InvokeAI",
    "comfyui":        "comfyanonymous/ComfyUI",
}


def get_app_repo(app: str) -> str | None:
    """
    Return the GitHub owner/repo string for an app key.
    Returns None if the app key is not in the registry.

    Example:
        get_app_repo("wan2gp")  →  "deepbeepmeep/Wan2GP"
    """
    return _APP_REPOS.get(app)


# ---------------------------------------------------------------------------
# Release info
# ---------------------------------------------------------------------------

def get_latest_release(owner_repo: str) -> str | None:
    """
    Return the tag name of the latest release for a repo.
    Uses /releases/latest — returns the most recent non-prerelease, non-draft release.
    Returns None on error or if no releases exist.

    Example:
        get_latest_release("comfyanonymous/ComfyUI")  →  "v0.3.43"
    """
    url = f"{_API_BASE}/repos/{owner_repo}/releases/latest"
    data = _get(url)
    if data is None:
        return None
    tag = data.get("tag_name")
    if not tag:
        print(
            f"[ai_lib_github] no tag_name in latest release for {owner_repo}",
            file=sys.stderr,
        )
        return None
    return tag


def get_latest_commit(owner_repo: str, branch: str = "master") -> str | None:
    """
    Return the short SHA of the latest commit on a branch.
    Falls back to trying 'main' if 'master' returns 404.
    Returns None on error.

    Used for git-clone apps (A1111, Wan2GP, FramePack, ComfyUI) where
    the working state is tracked by commit rather than release tag.

    Example:
        get_latest_commit("comfyanonymous/ComfyUI")  →  "0b04660b"
    """
    url = f"{_API_BASE}/repos/{owner_repo}/commits/{branch}"
    data = _get(url)

    # Try 'main' if 'master' came back None (404 logged to stderr already)
    if data is None and branch == "master":
        url = f"{_API_BASE}/repos/{owner_repo}/commits/main"
        data = _get(url)

    if data is None:
        return None

    sha = data.get("sha", "")
    if not sha:
        print(
            f"[ai_lib_github] no sha in commit response for {owner_repo}",
            file=sys.stderr,
        )
        return None

    # Return short SHA (8 chars) to match what git log --short produces
    return sha[:8]


def get_releases(owner_repo: str, count: int = 5) -> list[dict]:
    """
    Return up to `count` recent releases for a repo.
    Each dict contains tag_name and assets (list of {name, browser_download_url}).
    Returns empty list on error.
    """
    url  = f"{_API_BASE}/repos/{owner_repo}/releases?per_page={count}"
    data = _get(url)
    return data if isinstance(data, list) else []


def get_tags(owner_repo: str, count: int = 20) -> list[dict]:
    """
    Return up to `count` tags for a repo.
    Each dict has at least: name (tag name).
    Returns empty list on error.
    """
    url  = f"{_API_BASE}/repos/{owner_repo}/tags?per_page={count}"
    data = _get(url)
    return data if isinstance(data, list) else []


def get_release_by_tag(owner_repo: str, tag: str) -> dict | None:
    """
    Return the release associated with a specific tag, or None if none exists.
    Each dict contains tag_name and assets (list of {name, browser_download_url}).
    Returns None on 404 (tag exists but has no release) or any other error.
    """
    url  = f"{_API_BASE}/repos/{owner_repo}/releases/tags/{tag}"
    data = _get(url)
    return data if isinstance(data, dict) else None


def get_release_assets(owner_repo: str) -> list[str]:
    """
    Return a list of asset filenames from the latest release of a repo.
    Returns empty list on error or if no assets exist.

    Used by wheel_available() to check for pre-built wheels before
    deciding whether to build from source.

    Example:
        get_release_assets("deepbeepmeep/kernels")
        →  ["sageattention-2.2.0-cp311-cp311-linux_x86_64.whl", ...]
    """
    url = f"{_API_BASE}/repos/{owner_repo}/releases/latest"
    data = _get(url)
    if data is None:
        return []

    assets = data.get("assets", [])
    return [a["name"] for a in assets if "name" in a]


def get_release_assets_with_urls(owner_repo: str) -> list[dict]:
    """
    Return a list of asset dicts from the latest release of a repo.
    Each dict has: name, url (browser_download_url), size_mb.
    Returns empty list on error or if no assets exist.

    Used by ai_lib_wheels.search() to find downloadable prebuilt wheels.

    Example:
        get_release_assets_with_urls("mjun0812/flash-attention-prebuild-wheels")
        →  [
              {
                "name":    "flash_attn-2.8.3+cu130torch2.12-cp311-cp311-linux_x86_64.whl",
                "url":     "https://github.com/.../releases/download/.../flash_attn-...",
                "size_mb": 234,
              },
              ...
           ]
    """
    url  = f"{_API_BASE}/repos/{owner_repo}/releases/latest"
    data = _get(url)
    if data is None:
        return []

    assets = data.get("assets", [])
    result = []
    for a in assets:
        name     = a.get("name", "")
        dl_url   = a.get("browser_download_url", "")
        size_b   = a.get("size", 0)
        if name and dl_url:
            result.append({
                "name":    name,
                "url":     dl_url,
                "size_mb": size_b // 1024**2 if size_b else None,
            })
    return result


# ---------------------------------------------------------------------------
# Wheel availability
# ---------------------------------------------------------------------------

def wheel_available(assets: list[str], py_tag: str) -> bool:
    """
    Return True if any asset in the list looks like a wheel for py_tag.
    py_tag is a CPython tag string, e.g. "cp311", "cp312".

    Checks for the tag appearing in the filename — simple substring match
    is sufficient for the wheel naming convention used by these repos.

    Example:
        wheel_available(["sageattention-2.2.0-cp311-cp311-linux_x86_64.whl"], "cp311")
        →  True
        wheel_available(["sageattention-2.2.0-cp311-cp311-linux_x86_64.whl"], "cp312")
        →  False
    """
    for name in assets:
        if name.endswith(".whl") and py_tag in name:
            return True
    return False


# ---------------------------------------------------------------------------
# Python version requirements
# ---------------------------------------------------------------------------

def get_required_python(app: str) -> str:
    """
    Return the required Python version string for an app.

    STUB — hardcoded values matching ai_conventions.md config.python table.
    Replace with real fetch from repo metadata (pyproject.toml / setup.cfg)
    once that logic is implemented.

    Returns a pyenv-compatible version string, e.g. "3.11.9".
    Falls back to "3.11.9" for unknown apps.
    """
    # STUB — replace with real fetch from GitHub when implemented
    _REQUIRED = {
        "automatic":      "3.10.6",
        "wan2gp":         "3.11.9",
        "frampackstudio": "3.11.9",
        "invokeai":       "3.12.12",
        "comfyui":        "3.12.12",
    }
    version = _REQUIRED.get(app)
    if version is None:
        print(
            f"[ai_lib_github] get_required_python: unknown app '{app}', defaulting to 3.11.9",
            file=sys.stderr,
        )
        return "3.11.9"
    return version


# ---------------------------------------------------------------------------
# Convenience: latest version for display
# ---------------------------------------------------------------------------

def get_latest_app_version(app: str) -> str | None:
    """
    Return a human-readable version/commit string for display in the menu.
    For release-tracked apps (invokeai): returns latest release tag.
    For commit-tracked apps (all others): returns latest short commit SHA.
    Returns None if the repo is unknown or the API call fails.

    Example:
        get_latest_app_version("wan2gp")    →  "23a9aa1"
        get_latest_app_version("invokeai")  →  "v6.13.0"
    """
    # Apps tracked by pip release tag rather than git commit
    _RELEASE_TRACKED = {"invokeai"}

    owner_repo = get_app_repo(app)
    if owner_repo is None:
        print(
            f"[ai_lib_github] get_latest_app_version: unknown app '{app}'",
            file=sys.stderr,
        )
        return None

    if app in _RELEASE_TRACKED:
        return get_latest_release(owner_repo)
    else:
        return get_latest_commit(owner_repo)


# ---------------------------------------------------------------------------
# Rate limit check — useful for debugging
# ---------------------------------------------------------------------------

def get_rate_limit() -> dict | None:
    """
    Return current rate limit info from the GitHub API.
    Useful for debugging token auth issues.

    Returns dict with keys: limit, used, remaining, reset (epoch seconds).
    Returns None on error.
    """
    data = _get(f"{_API_BASE}/rate_limit")
    if data is None:
        return None
    try:
        core = data["resources"]["core"]
        return {
            "limit":     core["limit"],
            "used":      core["used"],
            "remaining": core["remaining"],
            "reset":     core["reset"],
        }
    except (KeyError, TypeError) as e:
        print(f"[ai_lib_github] unexpected rate_limit response: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Quick self-test when run directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    print("=== ai_lib_github.py self-test ===\n")

    # Rate limit / auth check
    print("Rate limit:")
    rl = get_rate_limit()
    if rl:
        print(f"  limit={rl['limit']}  used={rl['used']}  remaining={rl['remaining']}")
        auth = "authenticated" if rl["limit"] > 60 else "unauthenticated (60/hr)"
        print(f"  → {auth}")
    else:
        print("  (failed)")

    print()

    # Test each app
    for app_key in ("automatic", "wan2gp", "frampackstudio", "invokeai", "comfyui"):
        repo    = get_app_repo(app_key)
        py_ver  = get_required_python(app_key)
        version = get_latest_app_version(app_key)
        print(f"{app_key:20s}  repo={repo}")
        print(f"{'':20s}  required_python={py_ver}  latest={version}")
        print()

    # Test wheel check for nunchaku (used by ai_lib_optional.py)
    print("Nunchaku wheel check (cp311):")
    assets = get_release_assets("deepbeepmeep/kernels")
    if assets:
        print(f"  assets found: {len(assets)}")
        avail = wheel_available(assets, "cp311")
        print(f"  cp311 wheel available: {avail}")
    else:
        print("  no assets (or repo not found)")
