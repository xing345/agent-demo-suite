"""Multimodal dataset pipeline and LoRA experiment scaffolding."""

from .adapters import AudioAdapter, DependencyMissing, ImageAdapter, TextAdapter, VideoAdapter
from .datasets import DatasetState
from .dedup import find_near_duplicates, hamming, simhash
from .experiments import ExperimentRecord, ExperimentRegistry, compare_metrics
from .lora import LoRAConfig, LoRARunner, QLoRAConfig, RunnerStatus, UnavailableRunner
from .split import split_ids
from .storage import ContentAddressedStore, StoredAsset

__all__ = [
    "AudioAdapter",
    "ContentAddressedStore",
    "DatasetState",
    "DependencyMissing",
    "ExperimentRecord",
    "ExperimentRegistry",
    "ImageAdapter",
    "LoRAConfig",
    "LoRARunner",
    "QLoRAConfig",
    "RunnerStatus",
    "StoredAsset",
    "TextAdapter",
    "UnavailableRunner",
    "VideoAdapter",
    "compare_metrics",
    "find_near_duplicates",
    "hamming",
    "simhash",
    "split_ids",
]