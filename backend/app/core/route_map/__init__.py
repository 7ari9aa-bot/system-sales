"""Route map: one small registry says which capability and scope each route group belongs to.

``registry.py`` is the only file a person edits. ``scan.py`` reads the real app, and
``tests/test_route_map.py`` fails when the two disagree, so the map cannot rot.
"""
