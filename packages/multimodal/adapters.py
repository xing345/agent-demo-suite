"""Per-modality adapters.

Heavy backends (Pillow, faster-whisper, ffmpeg) are injected. When a backend is
absent the adapter raises ``DependencyMissing`` instead of returning fake data.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class DependencyMissing(RuntimeError):
    """An optional backend is not installed; no substitute data is produced."""


class TextAdapter:
    name = "text"

    def normalize(self, raw: bytes) -> str:
        text = raw.decode("utf-8", errors="replace")
        return " ".join(text.split())


class _BackendAdapter:
    name = "generic"

    def __init__(self, *, backend: Callable[[bytes], Any] | None = None) -> None:
        self.backend = backend

    def require(self) -> Callable[[bytes], Any]:
        if self.backend is None:
            raise DependencyMissing(
                f"{self.name} backend not installed; install the optional dependency"
            )
        return self.backend


class ImageAdapter(_BackendAdapter):
    name = "image"

    def normalize(self, raw: bytes) -> dict[str, Any]:
        """Return image metadata from the injected loader (Pillow by default)."""
        return dict(self.require()(raw))


class AudioAdapter(_BackendAdapter):
    name = "audio"

    def transcribe(self, raw: bytes) -> dict[str, Any]:
        """Return ``{"text": ..., "segments": [...]}`` from faster-whisper."""
        return dict(self.require()(raw))


class VideoAdapter(_BackendAdapter):
    name = "video"

    def extract_frames(self, raw: bytes) -> list[bytes]:
        """Return extracted frame bytes from ffmpeg."""
        frames = self.require()(raw)
        return list(frames)