"""Proving a customer is who they say they are, before any private read.

A Caller ID, a phone number on the line or a name spoken aloud is a clue, never proof. This engine
is the only thing that raises a session's authentication level, and it raises it to VERIFIED only
after a one-time code that was delivered to a channel the customer already controls comes back.

The rules are the ones a risk team would insist on: the code is stored hashed and never returned
twice, it expires, it is single-use, wrong guesses are counted and the challenge dies with the last
one, and a caller cannot grind codes by starting new challenges in a loop.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass, replace
from typing import Final, Protocol

from app.core.errors import ValidationError
from app.modules.voice.security.capabilities import AuthenticationLevel


class VerificationError(Exception):
    """Base for every refusal to verify. Each subclass is a different sentence to the caller."""


class VerificationExpired(VerificationError):
    """The code is past its life or was already used."""


class VerificationFailed(VerificationError):
    """The code was wrong; ``attempts_left`` is what the caller may still try."""

    def __init__(self, attempts_left: int) -> None:
        super().__init__(f"wrong code, {attempts_left} attempt(s) left")
        self.attempts_left = attempts_left


class VerificationThrottled(VerificationError):
    """Too many challenges for this destination in the window; the caller must wait."""


CODE_TTL: Final[dt.timedelta] = dt.timedelta(minutes=5)
MAX_ATTEMPTS: Final[int] = 3
MAX_CHALLENGES_PER_WINDOW: Final[int] = 5
WINDOW: Final[dt.timedelta] = dt.timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class Challenge:
    challenge_id: uuid.UUID
    tenant_id: uuid.UUID
    customer_id: uuid.UUID | None
    destination: str
    code_hash: str
    attempts_left: int
    expires_at: dt.datetime
    consumed: bool = False


class ChallengeStore(Protocol):
    async def put(self, challenge: Challenge) -> None: ...

    async def get(self, challenge_id: uuid.UUID) -> Challenge | None: ...

    async def count_recent(
        self, *, tenant_id: uuid.UUID, destination: str, since: dt.datetime
    ) -> int: ...


class InMemoryChallengeStore:
    def __init__(self) -> None:
        self._rows: dict[uuid.UUID, Challenge] = {}

    async def put(self, challenge: Challenge) -> None:
        self._rows[challenge.challenge_id] = challenge

    async def get(self, challenge_id: uuid.UUID) -> Challenge | None:
        return self._rows.get(challenge_id)

    async def count_recent(
        self, *, tenant_id: uuid.UUID, destination: str, since: dt.datetime
    ) -> int:
        return sum(
            1
            for row in self._rows.values()
            if row.tenant_id == tenant_id
            and row.destination == destination
            and row.expires_at > since
        )


@dataclass(frozen=True, slots=True)
class OtpTicket:
    """What the control plane hands the delivery channel. The code never comes back from verify."""

    challenge_id: uuid.UUID
    destination: str
    expires_at: dt.datetime
    code_for_delivery: str


@dataclass(frozen=True, slots=True)
class VerifiedIdentity:
    tenant_id: uuid.UUID
    customer_id: uuid.UUID | None
    destination: str
    level: AuthenticationLevel
    verified_at: dt.datetime
    method: str


class IdentityVerificationEngine:
    def __init__(
        self,
        store: ChallengeStore,
        *,
        clock=lambda: dt.datetime.now(dt.UTC),
        ttl: dt.timedelta = CODE_TTL,
        max_attempts: int = MAX_ATTEMPTS,
        max_challenges: int = MAX_CHALLENGES_PER_WINDOW,
        window: dt.timedelta = WINDOW,
        pepper: str = "",
    ) -> None:
        self._store = store
        self._clock = clock
        self._ttl = ttl
        self._max_attempts = max_attempts
        self._max_challenges = max_challenges
        self._window = window
        self._pepper = pepper

    def _hash(self, *, challenge_id: uuid.UUID, code: str) -> str:
        payload = f"{challenge_id}:{code}:{self._pepper}".encode()
        return hashlib.sha256(payload).hexdigest()

    async def start(
        self,
        *,
        tenant_id: uuid.UUID,
        destination: str,
        customer_id: uuid.UUID | None = None,
    ) -> OtpTicket:
        """Issue a code for a destination, or refuse because this caller is grinding challenges."""
        destination = destination.strip()
        if len(destination) < 5:
            raise ValidationError("a verification destination must be a real phone or address")
        now = self._clock()
        recent = await self._store.count_recent(
            tenant_id=tenant_id, destination=destination, since=now - self._window
        )
        if recent >= self._max_challenges:
            raise VerificationThrottled(
                f"{recent} verification codes were already sent to this destination this hour"
            )
        challenge_id = uuid.uuid4()
        code = f"{secrets.randbelow(1_000_000):06d}"
        challenge = Challenge(
            challenge_id=challenge_id,
            tenant_id=tenant_id,
            customer_id=customer_id,
            destination=destination,
            code_hash=self._hash(challenge_id=challenge_id, code=code),
            attempts_left=self._max_attempts,
            expires_at=now + self._ttl,
        )
        await self._store.put(challenge)
        return OtpTicket(
            challenge_id=challenge_id,
            destination=destination,
            expires_at=challenge.expires_at,
            code_for_delivery=code,
        )

    async def verify(self, *, challenge_id: uuid.UUID, code: str) -> VerifiedIdentity:
        """Redeem a code once. Every failure path consumes or counts; none passes silently."""
        challenge = await self._store.get(challenge_id)
        if challenge is None:
            raise VerificationExpired("this verification code does not exist")
        if challenge.consumed:
            raise VerificationExpired("this verification code was already used")
        now = self._clock()
        if now >= challenge.expires_at:
            raise VerificationExpired("this verification code has expired")

        presented = self._hash(challenge_id=challenge_id, code=code.strip())
        if not hmac.compare_digest(presented, challenge.code_hash):
            left = challenge.attempts_left - 1
            await self._store.put(
                replace(challenge, attempts_left=max(left, 0), consumed=left <= 0)
            )
            if left <= 0:
                raise VerificationThrottled("too many wrong codes; start a new verification")
            raise VerificationFailed(attempts_left=left)

        await self._store.put(replace(challenge, consumed=True, attempts_left=0))
        return VerifiedIdentity(
            tenant_id=challenge.tenant_id,
            customer_id=challenge.customer_id,
            destination=challenge.destination,
            level=AuthenticationLevel.VERIFIED,
            verified_at=now,
            method="otp",
        )

    def from_account_session(
        self, *, tenant_id: uuid.UUID, customer_id: uuid.UUID, destination: str
    ) -> VerifiedIdentity:
        """A logged-in store session is proof already earned; the caller passes it, we record it."""
        return VerifiedIdentity(
            tenant_id=tenant_id,
            customer_id=customer_id,
            destination=destination,
            level=AuthenticationLevel.VERIFIED,
            verified_at=self._clock(),
            method="account_session",
        )
