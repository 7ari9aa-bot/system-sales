"""البرومبت اللي المكالمة بتبدأ بيه، مقروء من المحل اللي المكالمة بتاعته.

`voice_profile` بيقرر اللهجة والصوت من إعدادات، بس هو ما بيعرفش قاعدة البيانات بقصد.
الملف ده هو الحد بين الاتنين: بيقرا الـtenant مرة واحدة وقت فتح السوكت ويحوّله لإعدادات،
والـadapter بياخد `voice` و`instructions` جاهزين.

لو الـtenant مش موجود أو قراءته فشلت، الجلسة بتفتح بالعقد الأساسي واللهجة الافتراضية بدل ما
تسقط: مكالمة من غير اسم محل أحسن من مكالمة مش موجودة، والاسم ما بيتخمّنش.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from app.platform.identity.models import Tenant
from app.platform.voice.application.voice_profile import (
    ArabicDialect,
    ShopVoiceSettings,
    resolve_voice_profile,
    session_start_config,
)

logger = logging.getLogger(__name__)


def _dialect(value: str | None) -> ArabicDialect | None:
    """اللهجة المخزّنة نص حر؛ أي قيمة مش معروفة بترجع None فيشتغل البلد بدالها."""
    if not value:
        return None
    try:
        return ArabicDialect(str(value).strip().lower())
    except ValueError:
        return None


async def load_shop_voice_config(session, tenant_id: uuid.UUID) -> dict[str, str]:
    """إعدادات جلسة صوت واحدة: صوت واحد وكتلة تعليمات واحدة، مقروءين من المحل."""
    row = (
        await session.execute(
            select(Tenant.name, Tenant.country_code, Tenant.dialect).where(Tenant.id == tenant_id)
        )
    ).first()
    if row is None:
        logger.warning(
            "voice session for a missing tenant %s: starting on the base contract", tenant_id
        )
        return session_start_config(resolve_voice_profile(ShopVoiceSettings()))

    name, country, dialect = row
    return session_start_config(
        resolve_voice_profile(
            ShopVoiceSettings(
                country_code=country or "EG",
                language="ar",
                dialect=_dialect(dialect),
                shop_name=name or "",
            )
        )
    )
