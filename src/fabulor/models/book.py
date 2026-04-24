from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


@dataclass
class Book:
    path: str
    title: str = "Unknown"
    author: str = "Unknown Author"
    narrator: Optional[str] = None
    duration: float = 0.0
    progress: float = 0.0
    cover_path: Optional[str] = None
    folder_name_raw: Optional[str] = None
    year: Optional[int] = None
    id: Optional[int] = None
    date_added: Optional[datetime] = None
    last_played: Optional[datetime] = None

    def __post_init__(self):
        if not self.path:
            raise ValueError("Book path must not be empty")

    @classmethod
    def from_dict(cls, data: dict) -> Book:
        def _parse_dt(value):
            if value is None:
                return None
            try:
                return datetime.fromisoformat(value)
            except (TypeError, ValueError):
                return None

        return cls(
            path=data.get("path", ""),
            title=data.get("title", "Unknown"),
            author=data.get("author", "Unknown Author"),
            narrator=data.get("narrator"),
            duration=data.get("duration", 0.0),
            progress=data.get("progress", 0.0),
            cover_path=data.get("cover_path"),
            folder_name_raw=data.get("folder_name_raw"),
            year=data.get("year"),
            id=data.get("id"),
            date_added=_parse_dt(data.get("date_added")),
            last_played=_parse_dt(data.get("last_played")),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "path": self.path,
            "title": self.title,
            "author": self.author,
            "narrator": self.narrator,
            "duration": self.duration,
            "progress": self.progress,
            "cover_path": self.cover_path,
            "folder_name_raw": self.folder_name_raw,
            "year": self.year,
            "date_added": self.date_added.isoformat() if self.date_added else None,
            "last_played": self.last_played.isoformat() if self.last_played else None,
        }

    @property
    def progress_percentage(self) -> float:
        if not self.duration:
            return 0.0
        return min(self.progress / self.duration * 100, 100.0)

    @property
    def remaining_time(self) -> float:
        return max(self.duration - self.progress, 0.0)

    @property
    def is_started(self) -> bool:
        return self.progress > 0.0
