"""IngestService keeps every method the rest of the code calls.

A helper once got pasted at column 0 in the middle of the class body. Python read that as the end of
the class, so `process_webhook_event`, `apply_status_updates` and three more silently became
module-level functions: nothing failed at import, only at the first webhook. The unit tests that
imported the helper still passed. This pins the surface so the same slip fails here.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from app.modules.conversations.gateway import ingest
from app.modules.conversations.gateway.ingest import IngestService

REQUIRED = (
    "resolve_tenant",
    "process_webhook_event",
    "mark_webhook_event_failed",
    "_record_channel_failure",
    "apply_status_updates",
    "fill_customer_names",
    "apply_read_watermarks",
)


@pytest.mark.parametrize("name", REQUIRED)
def test_ingest_service_has_the_method(name):
    assert hasattr(IngestService, name), f"IngestService lost {name}"


def test_no_module_level_function_is_an_orphaned_staticmethod():
    """A `@staticmethod` outside a class is a method that fell out of its class."""
    tree = ast.parse(inspect.getsource(ingest))
    orphans = [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and any(getattr(d, "id", None) == "staticmethod" for d in node.decorator_list)
    ]
    assert orphans == []


def test_the_class_is_the_only_thing_between_its_first_and_last_method():
    """No module-level statement may sit between two of the class's own methods."""
    tree = ast.parse(inspect.getsource(ingest))
    names = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
    assert names.count("IngestService") == 1
