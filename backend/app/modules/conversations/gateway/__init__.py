"""Channel Gateway: platform adapters + ingest orchestration."""

from app.modules.conversations.gateway.base import (
    ChannelAdapter,
    InboundMessage,
    OutboundMessage,
    ProviderCredentials,
)
from app.modules.conversations.gateway.ingest import IngestService
from app.modules.conversations.gateway.webchat import webchat_adapter

__all__ = [
    "ChannelAdapter",
    "InboundMessage",
    "IngestService",
    "OutboundMessage",
    "ProviderCredentials",
    "webchat_adapter",
]
