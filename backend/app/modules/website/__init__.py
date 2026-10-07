"""Sales OS ↔ Website Platform integration (§206-§208, receive side).

The Website Platform (external presentation plane) owns websites; Sales OS
owns business truth (products, orders). This module is the bridge the
«My Website» section uses: provision a website for the tenant, SSO the
merchant into the Studio, publish, and read status.
"""
