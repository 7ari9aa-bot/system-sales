"""Connection-spec registry — the settings screen reads THIS, nothing else."""

from __future__ import annotations

from app.modules.platform.channel_specs.base import (
    ChannelConnectionSpec,
    ConnectionSpec,
)
from app.modules.platform.channel_specs.facebook import facebook_connection_spec
from app.modules.platform.channel_specs.instagram import instagram_connection_spec
from app.modules.platform.channel_specs.messenger import messenger_connection_spec
from app.modules.platform.channel_specs.telegram import telegram_connection_spec
from app.modules.platform.channel_specs.webchat import webchat_connection_spec
from app.modules.platform.channel_specs.whatsapp import whatsapp_connection_spec

CONNECTION_SPECS: dict[str, ChannelConnectionSpec] = {
    spec.name: spec
    for spec in (
        whatsapp_connection_spec,
        telegram_connection_spec,
        facebook_connection_spec,
        messenger_connection_spec,
        instagram_connection_spec,
        webchat_connection_spec,
    )
}


def get_connection_spec(name: str) -> ChannelConnectionSpec | None:
    return CONNECTION_SPECS.get((name or "").strip().lower())


def list_connection_specs() -> list[ChannelConnectionSpec]:
    """Stable, UI-friendly ordering: the channels the owner listed, in order."""
    ordered = ("whatsapp", "facebook", "messenger", "instagram", "telegram", "webchat")
    return [CONNECTION_SPECS[name] for name in ordered if name in CONNECTION_SPECS]


__all__ = [
    "CONNECTION_SPECS",
    "ChannelConnectionSpec",
    "ConnectionSpec",
    "get_connection_spec",
    "list_connection_specs",
]
