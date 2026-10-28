from uuid import uuid4

from fastapi import FastAPI, HTTPException

from .schemas import CreateDatasetRequest, DatasetResponse

app = FastAPI(title="Multimodal and LoRA Demo", version="0.1.0")
datasets: dict[str, DatasetResponse] = {}


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
    return item


@app.get("/datasets/{dataset_id}", response_model=DatasetResponse)
def get_dataset(dataset_id: str) -> DatasetResponse:
    if dataset_id not in datasets:
        raise HTTPException(status_code=404, detail="dataset not found")
    return datasets[dataset_id]


def run() -> None:
    import uvicorn

    from packages.shared_config import get_settings

    settings = get_settings()
    uvicorn.run(app, host=settings.multimodal_host, port=settings.multimodal_port)
