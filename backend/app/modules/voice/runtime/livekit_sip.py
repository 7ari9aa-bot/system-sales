"""ما ينقص عشان مكالمة تليفون تدخل نفس الجلسة: إعداد LiveKit SIP، جاهز قبل الترنك.

LiveKit SIP محتاج حاجتين من عندنا: inbound trunk بالأرقام بتاعتنا، وdispatch rule بيحوّل
كل مكالمة داخلة لغرفة. والغرفة في تصميمنا هي ``voice_session.id``، فالقاعدة بتتولد لكل
مكالمة والـtenant بيتحدد من **الرقم اللي اتصل عليه** (DID) مش من رقم المتصل.

الحاجة الوحيدة اللي مش في إيدينا هي مزود الترنك: الشركة اللي بتملك الأرقام وبتوصل
المكالمة لـSIP endpoint بتاع LiveKit. من غيرها الإعداد ده بيتبني ويتست بس مش بيشتغل.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class SipNotConfigured(Exception):
    """إعداد SIP ناقص، فمفيش مكالمة تليفون تدخل."""


@dataclass(frozen=True, slots=True)
class SipInboundPlan:
    """اللي بنبعته لـLiveKit عشان يستقبل مكالمات على أرقامنا."""

    numbers: tuple[str, ...]
    allowed_addresses: tuple[str, ...]
    dispatch_rule: dict[str, object]
    requires_pstn_trunk: bool = True

    def as_inbound_trunk(self, name: str = "sales-os") -> dict[str, object]:
        return {
            "trunk": {
                "name": name,
                "numbers": list(self.numbers),
                "allowed_addresses": list(self.allowed_addresses),
            }
        }

    def as_dispatch_rule(self, name: str = "sales-os-inbound") -> dict[str, object]:
        return {"dispatch_rule": {"name": name, **self.dispatch_rule}}


@dataclass(frozen=True, slots=True)
class SipRoutingSettings:
    """أرقامنا اللي العملاء بيتصلوا عليها، ومين مسموح له يوصل لـSIP endpoint."""

    dids: tuple[str, ...] = ()
    allowed_addresses: tuple[str, ...] = ()
    room_prefix: str = "voice-"
    agent_name: str = "sales-os-voice"
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if any(not did.startswith("+") for did in self.dids):
            raise SipNotConfigured("كل رقم لازم يبدأ بـ+ والدولة، زي +201234567890")


def plan_inbound_sip(settings: SipRoutingSettings) -> SipInboundPlan:
    """يبني خطة الاستقبال، ويرفض لو مفيش أرقام أو مفيش مصدر مسموح.

    ``allowed_addresses`` مش تفصيلة: من غيرها أي حد يعرف الـSIP URI يقدر يبعت مكالمات
    ويحرق رصيد. فبنرفض الإعداد بدل ما نفتحه للعالم.
    """
    if not settings.dids:
        raise SipNotConfigured("مفيش أرقام DID، فمفيش مكالمات تدخل")
    if not settings.allowed_addresses:
        raise SipNotConfigured("لازم عناوين مزود الترنك المسموح لها، مش SIP مفتوح للعالم")
    return SipInboundPlan(
        numbers=tuple(dict.fromkeys(settings.dids)),
        allowed_addresses=tuple(dict.fromkeys(settings.allowed_addresses)),
        dispatch_rule={
            "rule": {
                "dispatch_rule_individual": {
                    "room_prefix": settings.room_prefix,
                    "room_config": {
                        "agents": [{"agent_name": settings.agent_name}],
                    },
                }
            },
            "room_config": {"agents": [{"agent_name": settings.agent_name}]},
            "metadata": dict(settings.metadata),
        },
    )


def tenant_did_from_call_attributes(attributes: dict[str, str]) -> str:
    """الـDID اللي العميل اتصل عليه — منه بيتحدد المتجر، مش من رقمه هو."""
    for key in ("sip.trunkPhoneNumber", "sip.phoneNumber"):
        value = (attributes.get(key) or "").strip()
        if value:
            return value
    raise SipNotConfigured("المكالمة وصلت من غير DID، فمش عارفين أي متجر")
