"""The agent LAYER (spec §22) — pluggable agents behind one runtime.

Two canonical agents ship today, with completely different mandates:

``customer``
    The conversational storefront. Answers a customer's question like a full
    service agent — text, a voice transcript, or a photo — and looks everything
    up in the store's own data. It holds NO sales power: no orders, no cart, no
    promises, and its prompt forbids selling outright. It is driven by INBOUND
    customer messages: ``hooks.py`` is its gateway and ``handover.py`` is how it
    hands a customer to a human.

``sales_intelligence``
    The owner's analyst. Reads metrics, trends, fulfilment and drivers for the
    merchant. Every route that reaches it is gated by ``analytics:read``, so a
    customer can never reach it, and its tool set is read-only.

ADDING A THIRD AGENT IS ONE FILE
--------------------------------

1. Create ``agents/<kind>/definition.py`` that builds an :class:`AgentDefinition`
   and registers itself with :class:`AgentRegistry`.
2. Set ``provisioning_policy={"is_canonical": True, "auto_provision": True}`` if
   every new tenant should receive one automatically.
3. List the tools it may use in ``allowed_tools`` — the runtime refuses anything
   else (:meth:`AgentRegistry.is_tool_authorized`), and an empty list authorises
   nothing: tool authorization is default-deny per kind.
4. Pick a ``guardrail_profile``: ``analytics`` for a read-only analyst,
   ``default`` otherwise. A kind that is NOT registered fails CLOSED at the
   guardrail (``decision="block"``, reason ``unknown_agent_kind``) rather than
   running unsupervised.

Everything else picks the new kind up WITHOUT further edits: discovery walks this
directory (``discover_agents`` imports every ``agents/<kind>/definition.py`` and
fails startup on a broken one), provisioning is kind-agnostic, tool authorization
is per-kind, and the prompt-reconcile tooling iterates every canonical kind.

What is deliberately NOT automatic: ``hooks.py`` is the CUSTOMER-messaging
gateway, so a kind that is not customer-facing (an internal analyst) is not wired
to inbound messages — it is reached through its own routes instead. And the
prompt-reconcile's stale markers are declared per kind, so a prompt fix on a NEW
kind needs that kind's marker (or ``--force``) before the tool will touch its
rows: a prompt that does not match a known canonical revision is a store's own
edit, and overwriting it silently would be a worse bug than the drift.
"""
