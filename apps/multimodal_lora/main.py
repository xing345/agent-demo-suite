"""Multimodal dataset and LoRA experiment API.

Files are uploaded as base64 so the demo needs no multipart dependency. The
default LoRA runner is ``UnavailableRunner``: experiments are recorded as
``unavailable`` with ``metrics = None`` rather than inventing numbers.
"""

from __future__ import annotations

from base64 import b64decode
from binascii import Error as Base64Error
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException

from packages.multimodal import (
    ContentAddressedStore,
    DatasetState,
    ExperimentRegistry,
    LoRAConfig,
    QLoRAConfig,
    UnavailableRunner,
    split_ids,
)
from packages.shared_config import get_settings

from .schemas import (
    CreateDatasetRequest,
    CreateExperimentRequest,
    DatasetResponse,
    UploadFileRequest,
)

app = FastAPI(title="Multimodal and LoRA Demo", version="0.1.0")
settings = get_settings()

datasets: dict[str, DatasetResponse] = {}
dataset_states: dict[str, DatasetState] = {}
storage = ContentAddressedStore(Path(settings.upload_dir))
experiments = ExperimentRegistry(runner=UnavailableRunner())


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/datasets", response_model=DatasetResponse, status_code=201)
def create_dataset(request: CreateDatasetRequest) -> DatasetResponse:
    item = DatasetResponse(
        dataset_id=str(uuid4()),
        name=request.name,
        source_types=list(request.source_types),
        status="created",
    )
    datasets[item.dataset_id] = item
    dataset_states[item.dataset_id] = DatasetState(dataset_id=item.dataset_id)
    return item


@app.get("/datasets/{dataset_id}", response_model=DatasetResponse)
def get_dataset(dataset_id: str) -> DatasetResponse:
    if dataset_id not in datasets:
        raise HTTPException(status_code=404, detail="dataset not found")
    return datasets[dataset_id]


def _state(dataset_id: str) -> DatasetState:
    if dataset_id not in datasets:
        raise HTTPException(status_code=404, detail="dataset not found")
    return dataset_states[dataset_id]


@app.post("/datasets/{dataset_id}/files", status_code=201)
def upload_file(dataset_id: str, request: UploadFileRequest) -> dict[str, object]:
    state = _state(dataset_id)
    try:
        data = b64decode(request.content_base64, validate=True)
    except (Base64Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail="content_base64 is not valid base64") from exc
    if not data:
        raise HTTPException(status_code=422, detail="file is empty")
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="file exceeds MAX_UPLOAD_BYTES")

    asset = storage.put(data, filename=request.filename, media_type=request.media_type)
    added = state.add(asset)
    return {
        "dataset_id": dataset_id,
        "asset_id": asset.sha256,
        "sha256": asset.sha256,
        "size": asset.size,
        "media_type": asset.media_type,
        "duplicate": not added,
        "version": state.version,
    }


@app.post("/datasets/{dataset_id}/versions")
def freeze_version(dataset_id: str) -> dict[str, object]:
    return _state(dataset_id).freeze()


@app.post("/datasets/{dataset_id}/split")
def split_dataset(
    dataset_id: str,
    train_ratio: float = 0.8,
    seed: int = 42,
) -> dict[str, object]:
    state = _state(dataset_id)
    try:
        parts = split_ids(
            [asset.sha256 for asset in state.assets],
            train_ratio=train_ratio,
            seed=seed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"dataset_id": dataset_id, "version": state.version, **parts}


@app.post("/experiments", status_code=201)
def create_experiment(request: CreateExperimentRequest) -> dict[str, object]:
    state = _state(request.dataset_id)
    try:
        if request.quant_bits is not None:
            config: LoRAConfig = QLoRAConfig(
                rank=request.rank,
                alpha=request.alpha,
                learning_rate=request.learning_rate,
                epochs=request.epochs,
                quant_bits=request.quant_bits,
            )
        else:
            config = LoRAConfig(
                rank=request.rank,
                alpha=request.alpha,
                learning_rate=request.learning_rate,
                epochs=request.epochs,
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    record = experiments.create(
        name=request.name,
        dataset_id=request.dataset_id,
        dataset_version=state.version,
        config=config,
    )
    return record.to_dict()


@app.get("/experiments")
def list_experiments() -> list[dict[str, object]]:
    return [record.to_dict() for record in experiments.list()]


@app.get("/experiments/{experiment_id}")
def get_experiment(experiment_id: str) -> dict[str, object]:
    try:
        return experiments.get(experiment_id).to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/experiments/{experiment_id}/compare")
def compare_experiments(experiment_id: str, baseline: str) -> dict[str, object]:
    try:
        deltas = experiments.compare(experiment_id, baseline)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"candidate": experiment_id, "baseline": baseline, "deltas": deltas}


def run() -> None:
    import uvicorn

    uvicorn.run(app, host=settings.multimodal_host, port=settings.multimodal_port)