"""Content-addressed storage for uploaded multimodal assets."""

from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StoredAsset:
    sha256: str
    path: Path
    size: int
    media_type: str
    filename: str


class ContentAddressedStore:
    """Files are addressed by their sha256; identical uploads are stored once."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(
        self,
        data: bytes,
        *,
        filename: str,
        media_type: str | None = None,
    ) -> StoredAsset:
        digest = hashlib.sha256(data).hexdigest()
        suffix = Path(filename).suffix.lower()
        path = self.root / digest[:2] / f"{digest}{suffix}"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.stat().st_size != len(data):
            path.write_bytes(data)

        guessed = (
            media_type
            or mimetypes.guess_type(filename)[0]
            or "application/octet-stream"
        )
        return StoredAsset(
            sha256=digest,
            path=path,
            size=len(data),
            media_type=guessed,
            filename=filename,
        )