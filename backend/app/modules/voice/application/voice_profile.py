"""Which voice the merchant assistant speaks with, and which dialect it must hold.

The voice and the dialect are two different decisions and are kept apart here:

* the **voice** is a property of the model (GPT-Live ships a fixed set, none of them Arabic), so it
  is chosen from a catalog and cannot be changed after a session starts;
* the **dialect** is a property of the shop (its country, its language, and any explicit override),
  so it becomes an instruction the model must follow, never a different model or a different voice.

The honesty flag matters: no voice in the published catalog is Arabic-native, so a profile says so
out loud instead of letting a product screen imply an Egyptian voice exists when it does not.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class Presentation(enum.StrEnum):
    FEMININE = "feminine"
    MASCULINE = "masculine"


@dataclass(frozen=True, slots=True)
class VoiceOption:
    """One voice the model ships with, as published."""

    voice_id: str
    language: str
    regional_influence: str
    presentation: Presentation
    label: str


# The published GPT-Live voices. ``marin`` is the documented default and is listed first so a shop
# with no preference gets the voice OpenAI itself falls back to.
VOICE_CATALOG: tuple[VoiceOption, ...] = (
    VoiceOption("marin", "English", "Neutral", Presentation.FEMININE, "Marin"),
    VoiceOption("gleam", "English", "North American", Presentation.FEMININE, "Gleam"),
    VoiceOption("meridian", "English", "North American", Presentation.MASCULINE, "Meridian"),
    VoiceOption("halo", "English", "British", Presentation.FEMININE, "Halo"),
    VoiceOption("vesper", "English", "British", Presentation.MASCULINE, "Vesper"),
    VoiceOption("pearl", "English", "Australian", Presentation.FEMININE, "Pearl"),
    VoiceOption("quartz", "English", "Australian", Presentation.FEMININE, "Quartz"),
    VoiceOption("ripple", "English", "Australian", Presentation.MASCULINE, "Ripple"),
    VoiceOption("willow", "English", "Irish", Presentation.FEMININE, "Willow"),
    VoiceOption("stone", "English", "Irish", Presentation.MASCULINE, "Stone"),
    VoiceOption("beacon", "English", "Filipino", Presentation.MASCULINE, "Beacon"),
    VoiceOption("delta", "English", "Southern U.S.", Presentation.FEMININE, "Delta"),
    VoiceOption("cinder", "English", "Southern U.S.", Presentation.MASCULINE, "Cinder"),
    VoiceOption("bossa", "Portuguese", "Brazilian", Presentation.FEMININE, "Bossa"),
    VoiceOption("tempo", "Portuguese", "Brazilian", Presentation.MASCULINE, "Tempo"),
    VoiceOption("calandria", "Spanish", "Argentine", Presentation.FEMININE, "Calandria"),
    VoiceOption("compas", "Spanish", "Argentine", Presentation.MASCULINE, "Compás"),
    VoiceOption("hornero", "Spanish", "Argentine", Presentation.MASCULINE, "Hornero"),
    VoiceOption("luciernaga", "Spanish", "Mexican", Presentation.FEMININE, "Luciérnaga"),
    VoiceOption("destello", "Spanish", "Mexican", Presentation.MASCULINE, "Destello"),
    VoiceOption("nuri", "German", "Neutral", Presentation.FEMININE, "Nuri"),
    VoiceOption("juni", "German", "Neutral", Presentation.FEMININE, "Juni"),
    VoiceOption("flitz", "German", "Neutral", Presentation.MASCULINE, "Flitz"),
    VoiceOption("brise", "French", "Neutral", Presentation.FEMININE, "Brise"),
    VoiceOption("sillage", "French", "Neutral", Presentation.MASCULINE, "Sillage"),
    VoiceOption("nira", "Hindi", "Neutral", Presentation.FEMININE, "Nira"),
    VoiceOption("harema", "Japanese", "Neutral", Presentation.FEMININE, "Harema"),
    VoiceOption("shida", "Japanese", "Neutral", Presentation.MASCULINE, "Shida"),
    VoiceOption("noeul", "Korean", "Neutral", Presentation.FEMININE, "Noeul"),
)

VOICES_BY_ID: dict[str, VoiceOption] = {voice.voice_id: voice for voice in VOICE_CATALOG}
DEFAULT_VOICE_ID = "marin"


class ArabicDialect(enum.StrEnum):
    """The dialects a shop can ask for, and the words the model must actually use."""

    EGYPTIAN = "egyptian"
    GULF = "gulf"
    LEVANTINE = "levantine"
    MOROCCAN = "moroccan"
    MODERN_STANDARD = "modern_standard"


# Country to dialect. A shop's country is a setting it already has, so it is the default source;
# an explicit override always wins because owners move and brands differ from their address.
COUNTRY_DIALECTS: dict[str, ArabicDialect] = {
    "EG": ArabicDialect.EGYPTIAN,
    "SD": ArabicDialect.EGYPTIAN,
    "SA": ArabicDialect.GULF,
    "AE": ArabicDialect.GULF,
    "KW": ArabicDialect.GULF,
    "QA": ArabicDialect.GULF,
    "BH": ArabicDialect.GULF,
    "OM": ArabicDialect.GULF,
    "JO": ArabicDialect.LEVANTINE,
    "LB": ArabicDialect.LEVANTINE,
    "SY": ArabicDialect.LEVANTINE,
    "PS": ArabicDialect.LEVANTINE,
    "MA": ArabicDialect.MOROCCAN,
    "DZ": ArabicDialect.MOROCCAN,
    "TN": ArabicDialect.MOROCCAN,
}

DIALECT_INSTRUCTIONS: dict[ArabicDialect, str] = {
    ArabicDialect.EGYPTIAN: (
        "اتكلم بالمصري العامي اللي الناس بتتكلمه في الشارع، مش الفصحى. "
        "استخدم كلمات زي: إيه، ازاي، دلوقتي، خلاص، ماشي، تمام، تحت أمرك. "
        "متقولش: ماذا، كيف، الآن، حسناً."
    ),
    ArabicDialect.GULF: (
        "اتكلم باللهجة الخليجية العامية، مش الفصحى. "
        "استخدم كلمات زي: وش، شلون، الحين، خلاص، زين، أبشر. "
        "متقولش: ماذا، كيف، الآن، حسناً."
    ),
    ArabicDialect.LEVANTINE: (
        "اتكلم باللهجة الشامية العامية، مش الفصحى. "
        "استخدم كلمات زي: شو، كيف، هلق، خلص، منيح، تكرم. "
        "متقولش: ماذا، كيف، الآن، حسناً."
    ),
    ArabicDialect.MOROCCAN: (
        "اتكلم بالدارجة المغربية، مش الفصحى. "
        "استخدم كلمات زي: شنو، كيفاش، دابا، صافي، واخا. "
        "متقولش: ماذا، كيف، الآن، حسناً."
    ),
    ArabicDialect.MODERN_STANDARD: ("اتكلم بعربية فصحى مبسطة وواضحة، من غير عامية."),
}

LANGUAGE_BY_COUNTRY_ARABIC = frozenset(COUNTRY_DIALECTS)


@dataclass(frozen=True, slots=True)
class ShopVoiceSettings:
    """What a shop already knows about itself, and what its owner chose about the voice."""

    country_code: str = "EG"
    language: str = "ar"
    dialect: ArabicDialect | None = None
    voice_id: str | None = None
    presentation: Presentation | None = None
    shop_name: str = ""

    def normalised_country(self) -> str:
        return self.country_code.strip().upper()


@dataclass(frozen=True, slots=True)
class VoiceProfile:
    """The resolved answer: one voice, one dialect, and one instruction block."""

    voice_id: str
    language: str
    dialect: ArabicDialect | None
    voice_is_native_for_language: bool
    instructions: str

    @property
    def needs_dialect_instruction(self) -> bool:
        """True when the voice is not native for the language, so the prompt has to carry it."""
        return not self.voice_is_native_for_language


def _pick_voice(settings: ShopVoiceSettings) -> VoiceOption:
    if settings.voice_id:
        chosen = VOICES_BY_ID.get(settings.voice_id.strip())
        if chosen is None:
            raise ValueError(f"unknown voice {settings.voice_id!r}")
        return chosen
    if settings.presentation is not None:
        for voice in VOICE_CATALOG:
            if voice.presentation is settings.presentation:
                return voice
    return VOICES_BY_ID[DEFAULT_VOICE_ID]


def resolve_voice_profile(settings: ShopVoiceSettings) -> VoiceProfile:
    """Resolve the voice and the dialect from the shop's own settings.

    An explicit dialect override wins over the country, because the shop's address is not always
    the dialect its customers speak. A language that is not Arabic gets no Arabic instruction at
    all rather than a translated one.
    """
    country = settings.normalised_country()
    language = (settings.language or "ar").strip().lower().split("-")[0]
    dialect: ArabicDialect | None = None
    if language == "ar":
        dialect = settings.dialect or COUNTRY_DIALECTS.get(country, ArabicDialect.MODERN_STANDARD)
    voice = _pick_voice(settings)
    native = voice.language.strip().lower() == _language_name(language)

    parts: list[str] = []
    if language == "ar" and dialect is not None:
        parts.append(DIALECT_INSTRUCTIONS[dialect])
        parts.append(
            "أرقام الطلبات والأسعار انطقها زي ما العميل بيقولها في بلده، "
            "ولو رجعت مبلغ قول العملة بالاسم."
        )
        if not native:
            parts.append(
                "صوتك مش صوت عربي أصلي، فخلي النطق واضح وبطيء شوية على الكلمات الصعبة "
                "ومن غير أي كلمة إنجليزي إلا لو اسم منتج."
            )
    if settings.shop_name.strip():
        parts.append(f"اسم المحل: {settings.shop_name.strip()}.")
    return VoiceProfile(
        voice_id=voice.voice_id,
        language=language,
        dialect=dialect,
        voice_is_native_for_language=native,
        instructions=" ".join(parts).strip(),
    )


def _language_name(code: str) -> str:
    return {
        "ar": "arabic",
        "en": "english",
        "pt": "portuguese",
        "es": "spanish",
        "de": "german",
        "fr": "french",
        "hi": "hindi",
        "ja": "japanese",
        "ko": "korean",
    }.get(code, code)
