"""Carrying out a memory command the owner typed, and saying what happened.

The chat recognises the sentence (``owner_memory_command``) and calls this BEFORE the model, so the
model neither saves a note nor sees the command. Every reply is plain Arabic text, built here and
never from a model, because it is stored in the chat history and shown back.

Three rules about what a reply may contain:
  * a refused note is never repeated back. A password the owner typed by mistake must not be copied
    into the history it was refused for;
  * a saved note is shown as the owner's own words, but with markup characters flattened, so a note
    that looks like a tag or a header cannot become one in the reply;
  * nothing claims more than happened: "nothing saved" is said when nothing was.
"""

from __future__ import annotations

from app.modules.ai.owner_memory import (
    MAX_ACTIVE_MEMORIES,
    MAX_MEMORY_CHARS,
    MemoryRefused,
    OwnerMemoryService,
    _key,
)
from app.modules.ai.owner_memory_command import MemoryCommand

_WHY_NOT = {
    "sensitive": "ده شكله سر (باسورد أو كارت أو رقم قومي أو مفتاح)، فمبحفظش الحاجات دي.",
    "instruction": (
        "ده شكله تعليمات ليا مش معلومة عنك، فمبحفظش كده. "
        "قولي معلومة (زي «المورد الرئيسي اسمه حسين») وأنا أحفظها."
    ),
    "too_long": f"الملاحظة طويلة (الحد {MAX_MEMORY_CHARS} حرف). اختصرها وابعتها تاني.",
    "empty": "مفيش حاجة أحفظها.",
    "full": (
        f"الذاكرة ممتلئة ({MAX_ACTIVE_MEMORIES} ملاحظة). "
        "امسح ملاحظات قديمة من شاشة الذاكرة وبعدين قولي تاني."
    ),
    "disabled": "الذاكرة مقفولة عندك. قولي «شغل الذاكرة» الأول.",
}


def _plain(text: str) -> str:
    """A note as it may appear in a reply: one line, and nothing that reads as markup."""
    flat = " ".join(text.split())
    return flat.replace("<", "‹").replace(">", "›").replace("[", "(").replace("]", ")")


async def run_memory_command(service: OwnerMemoryService, command: MemoryCommand) -> str:
    """Do what the owner asked to their OWN notes and return the reply to show them."""
    if command.kind == "remember":
        return await _remember(service, command.note or "")
    if command.kind == "list":
        return await _list(service)
    if command.kind == "forget_all":
        removed = await service.forget_all()
        if not removed:
            return "مفيش حاجة محفوظة عندي عنك أمسحها."
        return f"مسحت كل اللي كنت فاكره عنك ({removed} ملاحظة)."
    if command.kind == "off":
        await service.set_enabled(False)
        return "وقفت الذاكرة. مش هحفظ حاجة جديدة ومش هستخدم اللي محفوظ، وهو لسه موجود لحد ما تمسحه."
    if command.kind == "on":
        await service.set_enabled(True)
        return "شغلت الذاكرة."
    raise ValueError(f"unknown memory command: {command.kind!r}")


async def _remember(service: OwnerMemoryService, note: str) -> str:
    key = _key(note)
    already = any(m.content_key == key for m in await service.list_active())
    try:
        saved = await service.remember(note, source="explicit")
    except MemoryRefused as refused:
        # The reason only. The note is NOT repeated: it may be the very secret that was refused.
        return "ما حفظتش. " + _WHY_NOT.get(refused.reason, "مقدرتش أحفظها.")
    shown = _plain(saved.content)
    if already:
        return f"كنت حافظ ده بالفعل: «{shown}»."
    return f"حفظت: «{shown}»."


async def _list(service: OwnerMemoryService) -> str:
    notes = await service.list_active()
    off = not await service.is_enabled()
    if not notes:
        return "مفيش حاجة محفوظة عندي عنك." + (" (الذاكرة مقفولة.)" if off else "")
    lines = []
    for i, n in enumerate(notes, start=1):
        mark = " (استنتجتها أنا)" if n.source == "inferred" else ""
        lines.append(f"{i}. {_plain(n.content)}{mark}")
    head = "اللي فاكره عنك:"
    if off:
        head = "الذاكرة مقفولة دلوقتي، ومش بستخدم اللي تحت. هو محفوظ لحد ما تمسحه:"
    return head + "\n" + "\n".join(lines)
