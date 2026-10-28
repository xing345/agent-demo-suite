from abc import ABC, abstractmethod
from typing import Any


class ModelGateway(ABC):
    @abstractmethod
    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        response_model: Any | None = None,
        tools: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        raise NotImplementedError("configure a concrete model provider before generation")

    @abstractmethod
    async def embed(
        self,
        texts: list[str],
        *,
        metadata: dict[str, Any] | None = None,
    ) -> list[list[float]]:
        raise NotImplementedError("configure an embedding provider before embedding")
