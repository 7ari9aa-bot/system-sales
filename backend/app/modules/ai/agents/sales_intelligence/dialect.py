"""The wording the owner's assistant uses for each dialect.

Which dialects a shop may choose is the shop's SETTING and is owned by ``identity.dialects`` (and
enforced by the database CHECK). This module is the assistant's side: it holds the fixed directive
for each key, and a read-only mirror of the key list and the currency default, so ``ai`` takes on no
import from ``identity`` for it. ``tests/test_si_dialect.py`` fails if the mirror and the owner ever
disagree, which is what keeps a copy honest.

The stored key selects one of these constants, so nothing a shop types can reach the model's system
prompt, and an unknown key fails closed to the neutral register.

A directive colours the wording only. It never changes which tool a number comes from, how a metric
is named, or any rule in the main prompt, and it travels after those rules so it cannot dilute them.
"""

from __future__ import annotations

_KEEP_EXACT = "الأرقام وأسماء المقاييس زي ما هي من الأدوات بالظبط، والأسلوب بس هو اللي يتأثر."

#: Mirror of ``identity.dialects`` (kept equal by a test): the closed list, the neutral register and
#: the currency default. Read-only here; the setting itself is owned and validated by identity.
CHOICES: tuple[str, ...] = ("egyptian", "gulf", "levantine", "maghrebi", "msa")
NEUTRAL = "msa"
CURRENCY_DEFAULT: dict[str, str] = {
    "EGP": "egyptian",
    "SAR": "gulf",
    "AED": "gulf",
    "QAR": "gulf",
    "KWD": "gulf",
    "JOD": "levantine",
    "MAD": "maghrebi",
}

#: One fixed directive per listed dialect.
DIRECTIVES: dict[str, str] = {
    "egyptian": (
        "رد باللهجة المصرية البسيطة زي ما صاحب محل بيكلم شريكه، بجمل قصيرة وبدون رسمية زيادة. "
        + _KEEP_EXACT
    ),
    "gulf": ("رد باللهجة الخليجية البيضاء المفهومة، بجمل قصيرة وبأسلوب مهذب مباشر. " + _KEEP_EXACT),
    "levantine": (
        "رد باللهجة الشامية البيضاء المفهومة، بجمل قصيرة وبأسلوب ودّي مباشر. " + _KEEP_EXACT
    ),
    "maghrebi": (
        "رد بعربية مبسطة مفهومة لصاحب محل مغربي، مع لمسة من الدارجة بدون مبالغة. " + _KEEP_EXACT
    ),
    "msa": ("رد بعربية فصحى مبسطة وواضحة بدون تعقيد، بجمل قصيرة ونبرة محايدة. " + _KEEP_EXACT),
}


def directive_for(key: str | None) -> str:
    """The fixed style directive for a key; the neutral one for anything unknown."""
    return DIRECTIVES.get(key or "", DIRECTIVES[NEUTRAL])


def resolve(stored: str | None, currency: str | None) -> str:
    """The dialect key a shop gets: its owner's choice, else its currency's, else neutral.

    A stored value that is not on the list is neither: it fails closed to neutral."""
    if stored:
        return stored if stored in CHOICES else NEUTRAL
    return CURRENCY_DEFAULT.get((currency or "").upper(), NEUTRAL)


def directive_for_shop(stored: str | None, currency: str | None) -> str:
    """The directive a shop gets: its owner's choice, else its currency's, else neutral."""
    return directive_for(resolve(stored, currency))
