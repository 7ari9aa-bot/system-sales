"""Sector applications.

One package per industry. Each package owns that sector's modules, settings,
permissions, routes and events, and may use ``app.platform`` and ``app.core``.
Nothing under ``app.modules`` may import from here: the platform does not know
which sectors exist, which is the whole point of this layer.
"""
