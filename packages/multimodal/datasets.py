"""Dataset state and immutable version manifests."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from .storage import StoredAsset


@dataclass
class DatasetState:
    dataset_id: str
    assets: list[StoredAsset] = field(default_factory=list)
    version: int = 0
    dataset_hash: str | None = None
    duplicates_removed: int = 0

    def add(self, asset: StoredAsset) -> bool:
        """Add an asset; returns ``False`` when the content is already present."""
        if any(existing.sha256 == asset.sha256 for existing in self.assets):
            self.duplicates_removed += 1
            return False
        self.assets.append(asset)
        return True

    def add_many(self, assets: list[StoredAsset]) -> int:
        return sum(1 for asset in assets if self.add(asset))

    def content_hash(self) -> str:
        joined = "\n".join(sorted(asset.sha256 for asset in self.assets))
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()

    def freeze(self) -> dict[str, Any]:
        """Freeze the current content into a version; a no-op when unchanged."""
        digest = self.content_hash()
        if digest != self.dataset_hash:
            self.dataset_hash = digest
            self.version += 1
        return self.manifest()

    def manifest(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "version": self.version,
            "dataset_hash": self.dataset_hash,
            "file_count": len(self.assets),
            "total_bytes": sum(asset.size for asset in self.assets),
            "duplicates_removed": self.duplicates_removed,
            "asset_ids": [asset.sha256 for asset in self.assets],
        }