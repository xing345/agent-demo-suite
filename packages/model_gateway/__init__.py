"""Model provider abstraction."""

from .base import ModelGateway
from .openai_compatible import ModelGatewayError, OpenAICompatibleGateway

__all__ = ["ModelGateway", "ModelGatewayError", "OpenAICompatibleGateway"]
