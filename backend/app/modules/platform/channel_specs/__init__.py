"""Per-channel connection specs — one file per channel (see base.py)."""

from app.modules.platform.channel_specs.registry import (
    CONNECTION_SPECS,
    get_connection_spec,
    list_connection_specs,
)

__all__ = ["CONNECTION_SPECS", "get_connection_spec", "list_connection_specs"]
