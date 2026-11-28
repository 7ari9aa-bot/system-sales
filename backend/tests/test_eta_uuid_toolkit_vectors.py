"""The receipt UUID against the authority's OWN library.

``tests/data/eta_uuid_authority_vectors.json`` holds documents together with the UUID that the
authority's published NuGet package ``ETA.Ereceipt.UUID`` 1.0.0 (MIT, author "ETAEgypt") returned
for them when it was executed (on .NET 8, no ETA account involved). Each ``sent_text`` is the
receipt exactly as it is sent, ``header.uuid`` empty. Our implementation must give the same 64
characters. These vectors are what justify ``NORMALIZATION_VERIFIED = True``.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.applications.apparel.modules.einvoice.providers.eta import builder
from app.applications.apparel.modules.einvoice.providers.eta.uuid_ import (
    NORMALIZATION_VERIFIED,
    UnsupportedShape,
    canonical_string,
    compute_receipt_uuid,
)

_VECTORS = json.loads(
    (Path(__file__).parent / "data" / "eta_uuid_authority_vectors.json").read_text(encoding="utf-8")
)["vectors"]


def _hash_of_sent_text(text: str) -> str:
    # Decimal keeps "1.50000" exactly as written, which is what the authority's rule needs.
    doc = json.loads(text, parse_float=Decimal, parse_int=Decimal)
    return hashlib.sha256(canonical_string(doc).encode("utf-8")).hexdigest()


def test_the_rule_is_marked_verified_only_because_these_vectors_exist():
    assert NORMALIZATION_VERIFIED is True
    assert len(_VECTORS) >= 50
    assert {v["kind"] for v in _VECTORS} == {"rule", "receipt"}


@pytest.mark.parametrize(
    "vector", _VECTORS, ids=[f"{v['kind']}-{i}" for i, v in enumerate(_VECTORS)]
)
def test_we_produce_the_authoritys_uuid(vector):
    assert _hash_of_sent_text(vector["sent_text"]) == vector["authority_uuid"]


def test_the_builder_hashes_what_it_sends():
    from tests.test_eta_ereceipt_core import _receipt

    doc = builder.build_receipt(_receipt())
    sent_with_empty_uuid = builder.dumps({**doc, "header": {**doc["header"], "uuid": ""}})
    assert doc["header"]["uuid"] == _hash_of_sent_text(sent_with_empty_uuid)


def test_compute_receipt_uuid_ignores_the_uuid_already_in_the_receipt():
    from tests.test_eta_ereceipt_core import _receipt

    doc = builder.build_receipt(_receipt())
    filled = builder._jsonable(doc)
    assert compute_receipt_uuid(filled) == doc["header"]["uuid"]
    filled["header"]["uuid"] = "f" * 64
    assert compute_receipt_uuid(filled) == doc["header"]["uuid"]


def test_a_shape_the_authoritys_serializer_handles_oddly_is_refused_not_guessed():
    with pytest.raises(UnsupportedShape):
        canonical_string({"a": [1, 2]})
    with pytest.raises(UnsupportedShape):
        canonical_string([{"a": 1}])
