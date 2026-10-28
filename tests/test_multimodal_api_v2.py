"""HTTP surface for uploads, dataset versions, splits and experiments."""

import base64

from fastapi.testclient import TestClient

from apps.multimodal_lora.main import app

client = TestClient(app, raise_server_exceptions=False)


def _dataset(name: str = "demo") -> str:
    response = client.post("/datasets", json={"name": name, "source_types": ["text"]})
    assert response.status_code == 201
    return str(response.json()["dataset_id"])


def _upload(dataset_id: str, filename: str, content: bytes):
    return client.post(
        f"/datasets/{dataset_id}/files",
        json={
            "filename": filename,
            "content_base64": base64.b64encode(content).decode("ascii"),
        },
    )


def test_upload_is_content_addressed_and_deduplicated() -> None:
    dataset_id = _dataset()

    first = _upload(dataset_id, "a.txt", b"hello world")
    second = _upload(dataset_id, "a-copy.txt", b"hello world")

    assert first.status_code == 201
    assert first.json()["size"] == 11
    assert first.json()["duplicate"] is False
    assert second.status_code == 201
    assert second.json()["duplicate"] is True
    assert second.json()["sha256"] == first.json()["sha256"]


def test_version_increments_only_on_content_change() -> None:
    dataset_id = _dataset()
    _upload(dataset_id, "a.txt", b"alpha")

    assert client.post(f"/datasets/{dataset_id}/versions").json()["version"] == 1
    assert client.post(f"/datasets/{dataset_id}/versions").json()["version"] == 1

    _upload(dataset_id, "b.txt", b"beta")
    manifest = client.post(f"/datasets/{dataset_id}/versions").json()

    assert manifest["version"] == 2
    assert manifest["file_count"] == 2


def test_split_partitions_all_assets() -> None:
    dataset_id = _dataset()
    for index in range(4):
        _upload(dataset_id, f"f{index}.txt", f"content-{index}".encode())

    body = client.post(f"/datasets/{dataset_id}/split", params={"train_ratio": 0.75}).json()

    assert len(body["train"]) == 3
    assert len(body["val"]) == 1
    assert set(body["train"]).isdisjoint(body["val"])


def test_invalid_base64_and_empty_uploads_are_rejected() -> None:
    dataset_id = _dataset()

    bad = client.post(
        f"/datasets/{dataset_id}/files",
        json={"filename": "x.bin", "content_base64": "not-base64!!"},
    )
    empty = _upload(dataset_id, "empty.txt", b"")

    assert bad.status_code == 422
    assert empty.status_code == 422


def test_unknown_dataset_returns_404() -> None:
    response = client.post(
        "/datasets/missing/files",
        json={"filename": "x.txt", "content_base64": base64.b64encode(b"x").decode()},
    )

    assert response.status_code == 404


def test_experiment_without_gpu_is_recorded_as_unavailable() -> None:
    dataset_id = _dataset()
    _upload(dataset_id, "a.txt", b"alpha")

    response = client.post(
        "/experiments",
        json={"name": "baseline", "dataset_id": dataset_id, "epochs": 1},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["metrics"] is None
    assert body["error"] == "no_cuda"
    assert body["dataset_version"] == 0
    assert client.get(f"/experiments/{body['experiment_id']}").status_code == 200


def test_compare_without_metrics_reports_empty_deltas() -> None:
    dataset_id = _dataset()
    first = client.post(
        "/experiments", json={"name": "a", "dataset_id": dataset_id}
    ).json()
    second = client.post(
        "/experiments", json={"name": "b", "dataset_id": dataset_id}
    ).json()

    response = client.post(
        f"/experiments/{second['experiment_id']}/compare",
        params={"baseline": first["experiment_id"]},
    )

    assert response.status_code == 200
    assert response.json()["deltas"] == {}