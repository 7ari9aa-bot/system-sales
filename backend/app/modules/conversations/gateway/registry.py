"""Adapter registry — channels plug in here."""

from __future__ import annotations

from app.modules.conversations.gateway.base import ChannelAdapter
from app.modules.conversations.gateway.instagram import instagram_adapter
from app.modules.conversations.gateway.messenger import messenger_adapter
from app.modules.conversations.gateway.telegram import telegram_adapter
from app.modules.conversations.gateway.webchat import webchat_adapter
from app.modules.conversations.gateway.whatsapp import whatsapp_adapter

ADAPTERS: dict[str, ChannelAdapter] = {
    webchat_adapter.name: webchat_adapter,
    whatsapp_adapter.name: whatsapp_adapter,
    telegram_adapter.name: telegram_adapter,
    messenger_adapter.name: messenger_adapter,
    instagram_adapter.name: instagram_adapter,
}


def register_adapter(adapter: ChannelAdapter) -> None:
    ADAPTERS[adapter.name] = adapter


def get_adapter(name: str) -> ChannelAdapter | None:
    return ADAPTERS.get(name)
