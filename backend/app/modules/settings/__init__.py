"""Settings module — the FIHRIST Configuration Engine.

A centralised, hierarchical settings system with scoped inheritance,
audit trails, and preset-based onboarding. Each setting is defined once
in the registry, stored per-scope in the database, and resolved at read
time through the inheritance chain: tenant → branch → warehouse →
pos_profile → register (and tenant → channel, tenant → user as leaves).
"""
