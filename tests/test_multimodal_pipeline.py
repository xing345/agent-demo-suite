"""Multimodal pipeline: storage, adapters, dedup, versions, splits, experiments."""

import pytest

from packages.multimodal.adapters import DependencyMissing, ImageAdapter, TextAdapter
from packages.multimodal.datasets import DatasetState
from packages.multimodal.dedup import find_near_duplicates, hamming, simhash
from packages.multimodal.experiments import ExperimentRegistry, compare_metrics
from packages.multimodal.lora import LoRAConfig, QLoRAConfig, UnavailableRunner
from packages.multimodal.split import split_ids
from packages.multimodal.storage import ContentAddressedStore


def test_store_is_content_addressed_and_idempotent(tmp_path) -> None:
    store = ContentAddressedStore(tmp_path / "uploads")

    first = store.put(b"hello", filename="a.txt")
    second = store.put(b"hello", filename="b.txt")

    assert first.sha256 == second.sha256
    assert first.path == second.path
    assert first.path.read_bytes() == b"hello"
    assert len(list((tmp_path / "uploads").rglob("*.txt"))) == 1


def test_text_adapter_normalises_whitespace() -> None:
    adapter = TextAdapter()

    assert adapter.normalize(b"  hello \r\n world  ") == "hello world"


def test_image_adapter_raises_when_backend_is_missing() -> None:
    adapter = ImageAdapter(backend=None)

    with pytest.raises(DependencyMissing, match="image"):
        adapter.normalize(b"\x89PNG")


def test_image_adapter_uses_injected_backend() -> None:
    adapter = ImageAdapter(backend=lambda raw: {"width": 2, "height": 2, "format": "PNG"})

    assert adapter.normalize(b"bytes")["width"] == 2


def test_simhash_detects_near_duplicates() -> None:
    left = simhash("the quick brown fox jumps over the lazy dog")
    right = simhash("the quick brown fox jumps over the lazy cat")
    other = simhash("completely different content about databases")

    assert hamming(left, right) == 9  # one-word change in a nine-word sentence
    assert hamming(left, other) > 10
    assert find_near_duplicates(
        [("a", "the quick brown fox jumps over the lazy dog"),
         ("b", "the quick brown fox jumps over the lazy cat"),
         ("c", "completely different content about databases")],
        threshold=10,
    ) == [("a", "b")]


def test_dataset_version_changes_only_when_content_changes(tmp_path) -> None:
    store = ContentAddressedStore(tmp_path / "uploads")
    state = DatasetState(dataset_id="d1")

    asset = store.put(b"alpha", filename="a.txt")
    assert state.add(asset) is True
    assert state.add(asset) is False  # duplicate content ignored

    first = state.freeze()
    second = state.freeze()
    state.add(store.put(b"beta", filename="b.txt"))
    third = state.freeze()

    assert first["version"] == 1
    assert second["version"] == 1
    assert third["version"] == 2
    assert third["file_count"] == 2
    assert third["dataset_hash"] != first["dataset_hash"]


def test_split_is_deterministic_and_lossless() -> None:
    ids = [f"doc-{index}" for index in range(10)]

    first = split_ids(ids, train_ratio=0.8, seed=7)
    second = split_ids(ids, train_ratio=0.8, seed=7)

    assert first == second
    assert len(first["train"]) == 8
    assert len(first["val"]) == 2
    assert sorted(first["train"] + first["val"]) == sorted(ids)


def test_split_rejects_invalid_ratio() -> None:
    with pytest.raises(ValueError):
        split_ids(["a", "b"], train_ratio=1.5)


def test_lora_config_validation() -> None:
    config = LoRAConfig(rank=8, alpha=16, learning_rate=0.0002, epochs=3)

    assert config.dropout == 0.0
    with pytest.raises(ValueError):
        LoRAConfig(rank=0, alpha=16, learning_rate=0.0002, epochs=3)
    assert QLoRAConfig(rank=8, alpha=16, learning_rate=0.0002, epochs=3).quant_bits == 4


def test_unavailable_runner_reports_reason_and_refuses_training() -> None:
    runner = UnavailableRunner()

    status = runner.probe()
    assert status.available is False
    assert status.reason == "no_cuda"
    with pytest.raises(DependencyMissing):
        runner.train(LoRAConfig(rank=8, alpha=16, learning_rate=0.0002, epochs=1), "d1")


def test_experiment_records_unavailable_without_metrics() -> None:
    registry = ExperimentRegistry(runner=UnavailableRunner())

    record = registry.create(
        name="baseline",
        dataset_id="d1",
        dataset_version=1,
        config=LoRAConfig(rank=8, alpha=16, learning_rate=0.0002, epochs=1),
    )

    assert record.status == "unavailable"
    assert record.metrics is None
    assert record.error == "no_cuda"
    assert registry.get(record.experiment_id) is record


def test_experiment_records_real_runner_metrics() -> None:
    class FakeRunner:
        def probe(self):
            from packages.multimodal.lora import RunnerStatus

            return RunnerStatus(available=True, reason=None, device="cpu")

        def train(self, config, dataset_ref):
            return {"loss": 0.5, "steps": 10}

    registry = ExperimentRegistry(runner=FakeRunner())
    record = registry.create(
        name="fake",
        dataset_id="d1",
        dataset_version=1,
        config=LoRAConfig(rank=4, alpha=8, learning_rate=0.001, epochs=1),
    )

    assert record.status == "completed"
    assert record.metrics == {"loss": 0.5, "steps": 10}


def test_compare_metrics_reports_deltas_and_nulls() -> None:
    deltas = compare_metrics({"accuracy": 0.5, "loss": 1.0}, {"accuracy": 0.7, "f1": 0.6})

    assert deltas["accuracy"] == pytest.approx(0.2)
    assert deltas["loss"] is None
    assert deltas["f1"] is None