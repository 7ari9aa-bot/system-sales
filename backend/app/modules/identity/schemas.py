"""Identity module — pydantic request/response schemas."""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

# Same shape the telemetry ingest accepts (platform/services/telemetry.py). Always
# used with fullmatch: a "$" anchor would let a trailing newline through.
_VISITOR_ID_RE = re.compile(r"[A-Za-z0-9_-]{8,64}")


class RegisterRequest(BaseModel):
    """email + password only is the minimal signup contract; the tenant
    name/slug and display name are derived server-side when omitted."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    tenant_name: str | None = Field(default=None, max_length=255)
    tenant_slug: str | None = Field(default=None, max_length=63, pattern=r"^[a-z0-9-]+$")
    full_name: str | None = Field(default=None, max_length=255)
    # The anonymous id the website tracker keeps in localStorage. Optional, and
    # a malformed value is DROPPED, never a reason to refuse a signup: attribution
    # must not be able to break registration.
    visitor_id: str | None = Field(default=None, max_length=64)

    @field_validator("visitor_id", mode="before")
    @classmethod
    def _drop_bad_visitor_id(cls, value):
        if value is None:
            return None
        return value if isinstance(value, str) and _VISITOR_ID_RE.fullmatch(value) else None

    captcha_token: str | None = Field(default=None, max_length=2048)

    # The shop's own name, the market it trades in, and whether the owner accepted the terms. All
    # optional: an email and a password alone still make an account, exactly as before.
    shop_name: str | None = Field(default=None, max_length=255)
    country_code: str | None = Field(default=None, max_length=2)
    terms_accepted: bool | None = None

    @field_validator("shop_name", mode="before")
    @classmethod
    def _blank_shop_name_is_none(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("country_code", mode="after")
    @classmethod
    def _country_must_be_a_market_we_serve(cls, value):
        # A wrong country is refused (422), never silently replaced by a default: the owner would
        # otherwise be set up for a market they did not choose.
        if value is None:
            return None
        from app.core.country import get_country

        spec = get_country(value)
        if spec is None or spec.launch_status != "live":
            raise ValueError("country is not a market we serve yet")
        return spec.code


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    captcha_token: str | None = Field(default=None, max_length=2048)


class PasswordResetRequest(BaseModel):
    email: EmailStr
    captcha_token: str | None = Field(default=None, max_length=2048)


class VerifyEmailRequest(BaseModel):
    """Body for POST /auth/verify-email — the token from the confirmation link."""

    token: str = Field(min_length=16, max_length=128)


class ChangePasswordRequest(BaseModel):
    """Body for POST /auth/password/change — a signed-in account, proven twice.

    `current_password` is what makes this safe to expose without a token: an
    unlocked laptop is not enough to change the credential. `new_password` is
    checked against the tenant's strength policy in the service, not here, so the
    rule has exactly one home.
    """

    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class SignedInDeviceOut(BaseModel):
    """One live refresh-token chain, as the account's own screen shows it."""

    id: uuid.UUID
    device: str
    user_agent: str | None = None
    ip: str | None = None
    signed_in_at: datetime
    last_used_at: datetime
    expires_at: datetime
    current: bool


class RevokedSessionsOut(BaseModel):
    """How many chains a revoke call closed — never who they were."""

    revoked: int


class ResendVerificationRequest(BaseModel):
    """Body for POST /auth/resend-verification — an address, nothing else.

    Shape-identical to PasswordResetRequest on purpose: both endpoints answer
    with the same neutral response regardless of account state. It stays its
    own type so the two contracts can evolve independently.
    """

    email: EmailStr
    captcha_token: str | None = Field(default=None, max_length=2048)


class PasswordResetConfirmRequest(BaseModel):
    token: str = Field(min_length=32, max_length=128)
    password: str = Field(min_length=8, max_length=128)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    # Optional since the cookie wave: the refresh cookie (path=/api/v1/auth)
    # supplies the token when the body omits it — the browser flow's shape.
    refresh_token: str | None = None


class SwitchTenantRequest(RefreshRequest):
    """§125: tenancy is the request context's, never a URL parameter.

    The target tenant rides the typed body — a query string is logged, cached
    and echoed by every hop between here and the user's finger — and the
    service still verifies membership server-side before minting anything.
    """

    tenant_id: uuid.UUID


class CurrentTenant(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    role_code: str | None = None
    # The one currency this shop trades in (ISO 4217), so a screen writes amounts in it.
    currency: str | None = None


class CurrentUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    is_platform_admin: bool
    # A short-lived read URL for the account's own picture, or None.
    avatar_url: str | None = None
    # Whether two-step verification is CONFIRMED and therefore challenges logins.
    # The security screen used to apologise that it could not read this; it is one
    # flag on the row the account already loads, so it is answered with the account.
    mfa_enabled: bool = False
    # Proven-inbox flag. The profile screen shows it beside the address instead of
    # implying an unverified account is verified.
    email_verified: bool = False
    # Optional contact/display facts the person fills in themselves.
    phone: str | None = None
    job_title: str | None = None
    tenants: list[CurrentTenant] = []


class UserPreferences(BaseModel):
    """What the person's own screen reads: their choices, and what applies now.

    A NULL field means "follow the default", which is why the response also carries
    the resolved values. Without them the screen would have to guess what a NULL
    timezone means, and a guess in a clock is a wrong time, not a blank one.
    """

    locale: str | None = None
    theme: str | None = None
    timezone: str | None = None
    date_format: str | None = None
    default_page: str | None = None
    #: The zone the account actually counts in: the person's own, or the shop's.
    effective_timezone: str
    #: The shop's zone, so the screen can say "following the shop" honestly.
    tenant_timezone: str | None = None


class PreferencesUpdate(BaseModel):
    """A partial rewrite of the caller's preferences.

    ``None`` leaves a field alone; an empty string clears it back to the default.
    That is the same contract ``PATCH /users/me`` uses for the phone and the job
    title, so one screen can save one control at a time without resending the rest.
    """

    locale: str | None = Field(default=None, max_length=8)
    theme: str | None = Field(default=None, max_length=16)
    timezone: str | None = Field(default=None, max_length=64)
    date_format: str | None = Field(default=None, max_length=8)
    default_page: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _something_to_change(self) -> PreferencesUpdate:
        if all(
            value is None
            for value in (
                self.locale,
                self.theme,
                self.timezone,
                self.date_format,
                self.default_page,
            )
        ):
            raise ValueError("nothing to update")
        return self


class ProfileUpdate(BaseModel):
    """The parts of an account its owner may rewrite about themselves.

    Deliberately narrow: the display name, the phone and the job title are the
    personal facts the API owns. Email is not here — changing it is a
    verified-identity operation (prove the inbox, then move the login), not a
    field edit, and the address is the key invitations bind to. The workspace
    name is not here either: it belongs to the shop (``PUT /tenants/{id}/name``),
    not to the person.

    Every field is optional so the screen can save one row at a time; an empty
    body is refused rather than answered with a no-op 200.
    """

    # Trimmed and collapsed by the service; the bound only stops an absurd payload.
    full_name: str | None = Field(default=None, max_length=255)
    # Free-form as people write numbers ("+20 100 123 4567"). The service keeps
    # the digits and the leading + and refuses anything that is not a phone.
    phone: str | None = Field(default=None, max_length=32)
    job_title: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def _something_to_change(self) -> ProfileUpdate:
        if self.full_name is None and self.phone is None and self.job_title is None:
            raise ValueError("nothing to update")
        return self


class InviteRequest(BaseModel):
    email: EmailStr
    #: When omitted, the tenant's ``team.default_role`` setting decides
    #: (falling back to the registry default "cashier").
    role_code: str | None = None


class InvitationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role_code: str | None
    status: str
    expires_at: datetime
    token: str  # shown once to the inviting admin


class MemberRoleUpdate(BaseModel):
    """A role change on an existing membership.

    One field, because that is the whole operation: the person, the workspace and
    the caller's rank are all server-side facts.
    """

    role_code: str = Field(min_length=1, max_length=63)


class RolePermissionOut(BaseModel):
    code: str
    resource: str
    action: str


class RoleOut(BaseModel):
    """A role and the permission codes it carries, read from role_permissions."""

    code: str
    name: str
    description: str | None = None
    permissions: list[str]


class PermissionMatrixOut(BaseModel):
    """The whole matrix: the roles, every permission, and who holds what.

    Sent as one payload because a matrix split across requests is a matrix that
    renders half-decided: a column arriving late looks like "no permissions".
    """

    roles: list[RoleOut]
    permissions: list[RolePermissionOut]


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=512)


class TeamUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=512)


class TeamOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    member_count: int = 0


class TeamListOut(BaseModel):
    items: list[TeamOut]


class TeamMemberOut(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str


class TeamMemberListOut(BaseModel):
    items: list[TeamMemberOut]


class AcceptInvitationRequest(BaseModel):
    token: str = Field(min_length=16, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)


# --- §151 hierarchy (workspaces / locations / location access) -------------


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=63, pattern=r"^[a-z0-9-]+$")


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    slug: str
    is_active: bool


class WorkspaceListOut(BaseModel):
    items: list[WorkspaceOut]


class LocationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    code: str | None = Field(default=None, min_length=1, max_length=31)


DAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class BranchDayHours(BaseModel):
    """One day of a branch's week. `closed` wins over any open/close it carries."""

    model_config = ConfigDict(extra="forbid")

    closed: bool = False
    open: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    close: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")

    @model_validator(mode="after")
    def _open_needs_close(self):
        if not self.closed and bool(self.open) != bool(self.close):
            raise ValueError("a trading day needs both open and close")
        return self


class LocationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    code: str | None = Field(default=None, min_length=1, max_length=31)
    is_active: bool | None = None
    # None leaves the hours untouched; an empty object clears them back to
    # "follows the store", which is a real choice and must stay reachable.
    hours: dict[str, BranchDayHours] | None = None


class LocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    code: str | None
    is_active: bool
    hours: dict | None = None


class LocationListOut(BaseModel):
    items: list[LocationOut]


class LocationAccessGrant(BaseModel):
    """PUT body — role_override is the only mutable grant attribute."""

    role_override: str | None = Field(default=None, max_length=63)


class LocationAccessOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    location_id: uuid.UUID
    role_override: str | None
    granted_by: uuid.UUID | None


class LocationAccessListOut(BaseModel):
    items: list[LocationAccessOut]


class AccountClosureRequestIn(BaseModel):
    """Ask to close the account, or to erase the personal data as well."""

    # close: stop using the account, keep the rows the shops still need.
    # delete: erase the personal data too.
    mode: str = Field(pattern="^(close|delete)$")
    reason: str | None = Field(default=None, max_length=1000)


class AccountClosureBlocker(BaseModel):
    """One membership that stops the request: the person owns this shop alone."""

    tenant_id: uuid.UUID
    tenant_name: str
    role_code: str | None = None


class AccountClosureRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    mode: str
    reason: str | None = None
    status: str
    created_at: datetime
    decided_at: datetime | None = None


class AccountClosureState(BaseModel):
    """What the profile screen needs to draw the "close my account" card.

    ``blockers`` is not decoration: a sole owner cannot walk away from a shop
    that would be left without one, so the screen disables the request and names
    the shop instead of letting the person submit something that must fail.
    """

    request: AccountClosureRequestOut | None = None
    blockers: list[AccountClosureBlocker] = []
    memberships: int = 0


class WorkspaceMembershipOut(BaseModel):
    """One workspace the person belongs to, as the switcher lists it."""

    id: uuid.UUID
    name: str
    slug: str
    role_code: str | None = None
    lifecycle_state: str
    is_active: bool


class WorkspaceOverviewOut(BaseModel):
    """The account workspace: the container, its region, its size, and your role.

    ``role_code`` is the caller's own role, not the workspace's: the same container
    looks different to its owner and to its cashier.
    """

    id: uuid.UUID
    name: str
    slug: str
    role_code: str | None = None
    lifecycle_state: str
    is_active: bool
    status_reason: str | None = None
    currency: str
    timezone: str | None = None
    country_code: str
    dialect: str | None = None
    member_count: int
    created_at: datetime


class WorkspaceAdminsOut(BaseModel):
    """Who runs the workspace. Empty for a caller without ``settings:read``."""

    owner_user_id: uuid.UUID | None = None
    admin_user_ids: list[uuid.UUID] = Field(default_factory=list)
