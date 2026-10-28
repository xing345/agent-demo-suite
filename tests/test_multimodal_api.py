from apps.multimodal_lora.main import create_dataset, get_dataset, health
from apps.multimodal_lora.schemas import CreateDatasetRequest


def test_health() -> None:
    assert health() == {"status": "ok"}


def test_create_and_get_dataset() -> None:
    response = create_dataset(
        CreateDatasetRequest(name="agent-notes", source_types=["text", "audio"])
    )
    result = get_dataset(response.dataset_id)

    assert result.status == "created"
    assert result.source_types == ["text", "audio"]
