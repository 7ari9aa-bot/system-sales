"""Period maturity (spec §6.6) — fair comparison means same age.

A period's numbers are not final the day they are written: COD orders settle
over days, returns arrive late. The maturity job compares the OBSERVED
resolved fraction against the EXPECTED fraction at that age (from the
platform's resolution curves); this module turns that ratio into the
three-state status every fact and finding carries.

Thresholds are config DEFAULTS to be calibrated by eval — never silent
constants someone guessed once.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.analytics.contracts import MaturityStatus

#: MATURE when the expected-unresolved share has fallen below ε (the period
#: is ~final). IMMATURE when more than τ of the expected resolution is still
#: outstanding. In between: PARTIALLY_MATURE.
DEFAULT_EPSILON = 0.05
DEFAULT_TAU = 0.50
#: A ratio the maturity job could not compute (no curve yet) yields None —
#: the honest call is PARTIALLY_MATURE with a warning, never MATURE.
DEFAULT_UNKNOWN_STATUS = MaturityStatus.PARTIALLY_MATURE


@dataclass(frozen=True, slots=True)
class MaturityThresholds:
    epsilon: float = DEFAULT_EPSILON
    tau: float = DEFAULT_TAU
    unknown_status: MaturityStatus = DEFAULT_UNKNOWN_STATUS

    DEFAULT: MaturityThresholds | None = None  # set below


MaturityThresholds.DEFAULT = MaturityThresholds()


def maturity_status(
    maturity_ratio: float | None,
    thresholds: MaturityThresholds | None = None,
) -> MaturityStatus:
    """Classify one period's maturity from observed/expected resolution.

    ``maturity_ratio`` is None when no resolution curve exists for this
    (carrier, governorate) fallback level — the unknown case degrades
    DOWN, never up: an unmeasured period must not read as final.
    """
    t = thresholds or MaturityThresholds.DEFAULT
    if maturity_ratio is None:
        return t.unknown_status
    if maturity_ratio < 0 or maturity_ratio > 1:
        raise ValueError(f"maturity_ratio outside [0, 1]: {maturity_ratio}")
    if 1 - maturity_ratio < t.epsilon:
        return MaturityStatus.MATURE
    if maturity_ratio < t.tau:
        return MaturityStatus.IMMATURE
    return MaturityStatus.PARTIALLY_MATURE
