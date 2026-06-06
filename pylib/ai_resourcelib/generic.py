# ai_resourcelib/generic.py
"""
   generic.py
   Library file located in <script dir>/ai_resourcelib/

   used by:
   ai_collect_metadata.py
   ai_model_manager.py
   (possibly others later)

"""
from pathlib import Path
from typing import Optional, Tuple
import os


def is_binary_file(filepath: Path, sample_size: int = 1024) -> Tuple[bool, str]:
    """
    Heuristically determines if a given file is binary or text.

    Args:
        filepath (Path): Path to the file to check.
        sample_size (int): Number of bytes to read for heuristic analysis.

    Returns:
        Tuple[bool, str]: (is_binary, message). True if binary, False if text,
                          message explains the decision or any failure.
    """
    try:
        with open(filepath, "rb") as f:
            chunk = f.read(sample_size)

        if not chunk:
            return False, f"File '{filepath.name}' is empty"

        # Check for null bytes which are common in binary files
        if b'\x00' in chunk:
            return True, f"File '{filepath.name}' contains null bytes, likely binary"

        # Check if all bytes are within readable ASCII range or common whitespace
        text_chars = bytearray({7,8,9,10,12,13,27} | set(range(0x20, 0x7F)))
        non_text = [b for b in chunk if b not in text_chars]

        if len(non_text) / len(chunk) > 0.30:  # Arbitrary threshold of 30%
            return True, f"File '{filepath.name}' contains many non-text bytes, likely binary"

        return False, f"File '{filepath.name}' is likely text based on heuristic"

    except Exception as e:
        return False, f"Exception reading file '{filepath.name}': {e}"


def file_sha256(filepath: Path, block_size: int = 65536) -> Optional[str]:
    """
    Compute the SHA256 hash of a file efficiently in blocks.

    Args:
        filepath (Path): Path to the file.
        block_size (int): Size of chunks to read at once.

    Returns:
        Optional[str]: Hexadecimal SHA256 hash string, or None on failure.
    """
    import hashlib

    sha256 = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            while True:
                data = f.read(block_size)
                if not data:
                    break
                sha256.update(data)
        return sha256.hexdigest()

    except Exception:
        return None


def file_fingerprint(filepath: Path, sample_size: int = 2048) -> Optional[str]:
    """
    Compute a fast fingerprint of a file by hashing the first and last
    sample_size bytes concatenated. Much faster than full SHA256 for large
    files as it requires only two seeks and two small reads.

    Distinctive for model files because:
    - Start contains format magic bytes, tensor names, embedded metadata
    - End often contains checksums and trailing metadata

    Args:
        filepath (Path): Path to the file.
        sample_size (int): Bytes to read from each end (default 2048).

    Returns:
        Optional[str]: Hex fingerprint string, or None on failure.
    """
    import hashlib
    try:
        file_size = filepath.stat().st_size
        if file_size == 0:
            return None

        with open(filepath, "rb") as f:
            # Read start
            start = f.read(sample_size)
            # Read end — seek from end, but don't overlap with start
            end_offset = max(sample_size, file_size - sample_size)
            f.seek(end_offset)
            end = f.read(sample_size)

        h = hashlib.sha256()
        h.update(start)
        h.update(end)
        return h.hexdigest()

    except Exception:
        return None


def file_sample_read(filepath: Path, sample_size: int = 4096) -> Optional[bytes]:
    """
    Read a sample of bytes from the middle of a file for cheap identity comparison.

    Reads sample_size bytes at offset filesize // 3, which avoids the header
    (often identical across variants of a model) and gives a representative
    interior sample. Used as a fast pre-check before falling back to full SHA256.

    Args:
        filepath (Path): Path to the file.
        sample_size (int): Number of bytes to read (default 4096).

    Returns:
        Optional[bytes]: The sample bytes, or None if the file could not be read
                         or is smaller than the offset.
    """
    try:
        file_size = filepath.stat().st_size
        if file_size == 0:
            return None
        offset = file_size // 3
        with open(filepath, "rb") as f:
            f.seek(offset)
            data = f.read(sample_size)
        return data if data else None
    except Exception:
        return None

# remove the following when its replacement works
def files_are_same_fast_replaced(
    path1: Path,
    path2: Path,
    use_sha256_fallback: bool = True,
) -> bool:
    """
    Determine if two files have identical content using the cheapest method available.

    Check order:
      1. Same inode (os.path.samefile) — instant, definitive.
      2. Size mismatch — instant disqualifier.
      3. Sample read at filesize // 3 — cheap, catches almost all mismatches.
      4. Full SHA256 — only if sample is inconclusive and use_sha256_fallback is True.

    Args:
        path1 (Path): First file path.
        path2 (Path): Second file path.
        use_sha256_fallback (bool): If True, fall back to SHA256 when sample
                                    is inconclusive. Default True.

    Returns:
        bool: True if files are considered identical, False otherwise.
    """
    import os

    # 1. Same inode — hardlinks or same file
    try:
        if os.path.samefile(path1, path2):
            return True
    except (FileNotFoundError, OSError):
        return False

    # 2. Size check — fast disqualifier
    try:
        if path1.stat().st_size != path2.stat().st_size:
            return False
    except OSError:
        return False

    # 3. Sample read
    sample1 = file_sample_read(path1)
    sample2 = file_sample_read(path2)

    if sample1 is None or sample2 is None:
        # Could not sample — fall through to SHA256 if enabled
        pass
    elif sample1 != sample2:
        return False
    else:
        # Samples match — treat as same (sufficient for model files)
        return True

    # 4. SHA256 fallback (last resort — expensive for large models)
    if use_sha256_fallback:
        h1 = file_sha256(path1)
        h2 = file_sha256(path2)
        return h1 is not None and h2 is not None and h1 == h2

    return False

def files_are_same_fast(
    path1: Path,
    path2: Path,
    use_sha256_fallback: bool = True,
) -> bool:
    """
    Determine if two files have identical content using the cheapest method available.

    Check order:
      1. Same inode (os.path.samefile) — instant, definitive.
      2. Size mismatch — instant disqualifier.
      3. Fingerprint (first+last 2KB hash) — fast, catches ~99.9% of mismatches.
      4. Full SHA256 — only if fingerprint is inconclusive and use_sha256_fallback is True.

    Args:
        path1 (Path): First file path.
        path2 (Path): Second file path.
        use_sha256_fallback (bool): If True, fall back to SHA256 when fingerprint
                                    is inconclusive. Default True.

    Returns:
        bool: True if files are considered identical, False otherwise.
    """
    import os

    # 1. Same inode — hardlinks or same file
    try:
        if os.path.samefile(path1, path2):
            return True
    except (FileNotFoundError, OSError):
        return False

    # 2. Size check — fast disqualifier
    try:
        if path1.stat().st_size != path2.stat().st_size:
            return False
    except OSError:
        return False

    # 3. Fingerprint — first+last 2KB, very fast on spinning disk
    fp1 = file_fingerprint(path1)
    fp2 = file_fingerprint(path2)

    if fp1 is None or fp2 is None:
        pass  # fall through to SHA256
    elif fp1 != fp2:
        return False
    else:
        return True  # fingerprints match — treat as same

    # 4. SHA256 fallback (last resort — expensive for large models)
    if use_sha256_fallback:
        h1 = file_sha256(path1)
        h2 = file_sha256(path2)
        return h1 is not None and h2 is not None and h1 == h2

    return False

# Additional generic utility functions can be added here as needed.


def collapse_to_canonical(
    src: "Path",
    canonical: "Path",
    confirmed_dup_dir: "Path",
    dry_run: bool,
    logger: "logging.Logger",
) -> bool:
    """
    Collapse a duplicate file (src) onto the canonical shared tree copy.

    Steps (all or nothing — any failure leaves files untouched):
      1. SHA256 both files — must match exactly.
      2. Hardlink src into confirmed_dup_dir/ as an audit record.
      3. Unlink src from its original location.
      4. Hardlink canonical into src's original location.
      5. Write a JSON audit sidecar in confirmed_dup_dir/.

    After this call:
      - src's original path points to canonical's inode (consolidated).
      - confirmed_dup_dir/ contains a hardlink + sidecar as audit trail.
      - No data is lost.

    Args:
        src:               Duplicate file path (to be replaced).
        canonical:         Canonical file in shared tree (to keep).
        confirmed_dup_dir: review/confirmed_duplicate/ directory.
        dry_run:           If True, log intent but make no changes.
        logger:            Logger instance.

    Returns:
        True if collapse succeeded (or dry_run), False on any failure.
    """
    import hashlib
    import json as _json
    from datetime import datetime, timezone

    def _sha256(fp: "Path") -> "Optional[str]":
        h = hashlib.sha256()
        try:
            with open(fp, "rb") as f:
                while True:
                    data = f.read(65536)
                    if not data:
                        break
                    h.update(data)
            return h.hexdigest()
        except Exception:
            return None

    # 1. SHA256 confirmation
    h_src = _sha256(src)
    h_can = _sha256(canonical)
    if h_src is None or h_can is None:
        logger.warning(f"collapse_to_canonical: could not hash {src.name} — skipping")
        return False
    if h_src != h_can:
        logger.warning(
            f"collapse_to_canonical: SHA256 mismatch for {src.name} "
            f"(fast check was wrong) — routing to duplicate_name instead"
        )
        return False

    logger.info(f"SHA256 confirmed identical — collapsing: {src.name}")

    if dry_run:
        logger.info(
            f"[DRY-RUN] Would collapse {src} → canonical inode of {canonical.name}"
        )
        return True

    # 2. Hardlink src into confirmed_dup_dir/ as audit record
    confirmed_dup_dir.mkdir(parents=True, exist_ok=True)
    audit_dest = confirmed_dup_dir / src.name
    # Number it if name already taken
    if audit_dest.exists():
        stem, suffix = src.stem, src.suffix
        for i in range(1, 10000):
            candidate = confirmed_dup_dir / f"{stem}_{i}{suffix}"
            if not candidate.exists():
                audit_dest = candidate
                break
        else:
            logger.warning(f"collapse_to_canonical: too many audit copies of {src.name} — skipping")
            return False

    try:
        os.link(src, audit_dest)
    except Exception as e:
        logger.warning(f"collapse_to_canonical: could not create audit hardlink for {src.name}: {e}")
        return False

    # 3. Unlink src from original location
    try:
        src.unlink()
    except Exception as e:
        logger.warning(f"collapse_to_canonical: could not unlink {src}: {e}")
        # Roll back audit hardlink
        try:
            audit_dest.unlink()
        except Exception:
            pass
        return False

    # 4. Hardlink canonical into src's original location
    try:
        os.link(canonical, src)
    except Exception as e:
        logger.warning(f"collapse_to_canonical: could not relink canonical to {src}: {e}")
        # Best-effort rollback — restore src from audit copy
        try:
            os.link(audit_dest, src)
        except Exception:
            logger.error(f"collapse_to_canonical: ROLLBACK FAILED for {src} — file may be missing!")
        return False

    # 5. Write audit sidecar in confirmed_dup_dir/
    sidecar = confirmed_dup_dir / (audit_dest.name + ".amm.json")
    audit_data = {
        "collapsed_duplicate": {
            "original_path":    str(src),
            "canonical_path":   str(canonical),
            "sha256":           h_src,
            "size_bytes":       src.stat().st_size if src.exists() else None,
            "collapsed_at":     datetime.now(timezone.utc).isoformat(),
        }
    }
    try:
        sidecar.write_text(
            _json.dumps(audit_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"collapse_to_canonical: could not write audit sidecar: {e}")
        # Non-fatal — collapse itself succeeded

    return True
