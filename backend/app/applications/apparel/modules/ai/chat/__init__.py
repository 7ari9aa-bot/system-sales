"""Merchant-facing sales-intelligence chat — threads, turns, render blocks.

Deliberately separate from the customer-messaging conversation pipeline: a
chat turn is a `run_sales_analysis` execution with bounded history, not a
customer reply.
"""
