"""External commerce connectors (§161) — Shopify, WooCommerce, CSV import.

The canonical workflow is source-of-truth-policy-driven: every entity
(products, inventory, orders, customers, payments) has an explicit
SourceOfTruthPolicy that defines whether the internal DB or the external
store is authoritative, and how conflicts are resolved.
"""
