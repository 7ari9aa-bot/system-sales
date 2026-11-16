"""E-invoicing provider registry and resolver."""

from __future__ import annotations

from app.modules.einvoice.ports import EInvoiceProvider
from app.modules.einvoice.providers.eta import EtaEInvoiceProvider
from app.modules.einvoice.providers.peppol_ae import PeppolAeEInvoiceProvider
from app.modules.einvoice.providers.sandbox import SandboxEInvoiceProvider
from app.modules.einvoice.providers.zatca import ZatcaEInvoiceProvider

_PROVIDERS: dict[str, type[EInvoiceProvider]] = {
    "sandbox": SandboxEInvoiceProvider,
    "zatca": ZatcaEInvoiceProvider,
    "eta": EtaEInvoiceProvider,
    "peppol_ae": PeppolAeEInvoiceProvider,
}

_COUNTRY_DEFAULT_PROVIDERS: dict[str, str] = {
    "SA": "zatca",
    "EG": "eta",
    "AE": "peppol_ae",
}


def register_provider(provider_type: str, provider_cls: type[EInvoiceProvider]) -> None:
    """Register a concrete e-invoicing provider implementation."""
    _PROVIDERS[provider_type.lower()] = provider_cls


def get_einvoice_provider(
    provider_type: str | None = None,
    *,
    country_code: str | None = None,
) -> EInvoiceProvider:
    """Retrieve an active EInvoiceProvider instance.

    Resolves by explicit provider_type, or infers standard provider from country_code.
    Falls back to SandboxEInvoiceProvider if a provider type is unconfigured or in tests.
    """
    key = provider_type.lower() if provider_type else None

    if not key and country_code:
        key = _COUNTRY_DEFAULT_PROVIDERS.get(country_code.strip().upper())

    provider_cls = _PROVIDERS.get(key or "sandbox", SandboxEInvoiceProvider)
    return provider_cls()
