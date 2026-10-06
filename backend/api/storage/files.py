import uuid
from pathlib import Path

from api.config import get_settings


def uploads_dir() -> Path:
    path = get_settings().data_path / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_upload(data: bytes, suffix: str) -> Path:
    path = uploads_dir() / f"{uuid.uuid4()}{suffix}"
    path.write_bytes(data)
    return path
