"""Settings module — the FIHRIST Configuration Engine.

A centralised, hierarchical settings system with scoped inheritance,
audit trails, and preset-based onboarding. Each setting is defined once
in the registry, stored per-scope in the database, and resolved at read
time through the inheritance chain: tenant → branch → warehouse →
pos_profile → register (and tenant → channel, tenant → user as leaves).
"""

# Import the event module so its @register_event decorator runs and
# "settings.changed" is known to the outbox event registry at startup.
from app.modules.settings import events as _events  # noqa: F401
