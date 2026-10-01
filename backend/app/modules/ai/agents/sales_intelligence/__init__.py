"""Sales Intelligence Agent (spec §0-§22) — the merchant's business analyst.

Lives INSIDE the ai module per the repo's convention (ai/agents/<name>),
builds on the platform AgentRunner (never a fork), and imports the analytics
layer as its public interface (§1.2) — the one deliberate cross-module edge
of this feature, recorded in the boundary ratchet.

Core principle (§0.3): the agent is free in its path; the system is strict
in its guarantees. The tools compute and prove; the model investigates and
explains.
"""
