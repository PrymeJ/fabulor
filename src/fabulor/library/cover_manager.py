from pathlib import Path
import platformdirs
import shutil

COVERS_DIR = Path(platformdirs.user_data_dir("fabulor", "fabulor")) / "covers"


def get_covers_dir() -> Path:
    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    return COVERS_DIR


def save_cover_image(book_hash: str, slot_index: int, source_path: str) -> str | None:
    """
    Copies source image into the covers data dir.
    Returns destination path string, or None on failure.
    Slot index 1–3 (slot 0 is scanner-managed).
    """
    try:
        dest = get_covers_dir() / f"{book_hash}_{slot_index}.jpg"
        shutil.copy2(source_path, dest)
        return str(dest)
    except Exception:
        return None


def delete_cover_file(file_path: str) -> None:
    """Silently deletes a cover file. No-op if file does not exist."""
    try:
        Path(file_path).unlink(missing_ok=True)
    except Exception:
        pass


def validate_cover_file(file_path: str) -> str | None:
    """
    Returns None if valid.
    Returns error string if invalid (too large, unreadable format).
    Max size: 5 MB.
    """
    try:
        size = Path(file_path).stat().st_size
        if size > 5 * 1024 * 1024:
            return "Image exceeds 5 MB limit."
        return None
    except Exception:
        return "Could not read file."
