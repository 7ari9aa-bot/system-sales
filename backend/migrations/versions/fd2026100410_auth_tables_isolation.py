"""Auth-plane isolation — RLS on the five global auth tables + RBAC freeze.

Finding 1 (external audit): ``users``, ``refresh_tokens``,
``password_reset_tokens``, ``user_mfa_secrets`` and ``tenants`` are the only
tables a session can touch before any GUC is bound, and none of them had RLS:
full DML on every credential in the system for one compromised
``sales_app`` session.

The design constraint is the login chicken-and-egg: login / refresh / reset /
MFA look rows up BEFORE any tenant or user context exists, and several of
those paths never bind a GUC at all (deps.get_current_user reads ``users`` on
every authenticated request before it sets anything; ``refresh`` and
``logout`` look up by token_hash; register probes ``tenants.slug``). An RLS
policy evaluates (row, session state) and can never see the query's WHERE
argument, so a possession lookup by email / token_hash / slug is
indistinguishable, policy-side, from an attacker's enumeration — UNLESS the
flow first establishes session state. Those flows do not, and app/ is out of
scope here, so the policy set below mirrors the exact call patterns in
identity/service.py and identity/deps.py:

- permissive ONLY where a pre-GUC possession lookup makes any row predicate
  impossible (documented per policy below; each is one app change away from
  being narrowed, and ``auth_lookup_user_by_email`` /
  ``auth_user_is_tenant_member`` are provided for that adoption);
- scoped to the bound identity everywhere the app DOES bind one.

Concretely:
  users         SELECT/INSERT stay possession-driven (pre-GUC lookups in
                login/register/reset + the per-request dep read); UPDATE is
                self-row via app.user_id OR while a password reset flow for
                that row is open (a reset token requested within the last
                hour — the flow updates the user with no GUC bound and the
                ORM consumes the token before flushing the user write);
                DELETE only when the user holds no live (unrevoked) refresh
                token.
  refresh_tokens SELECT/INSERT/UPDATE stay possession-driven (rotation,
                logout and family revocation all run pre-GUC by token_hash);
                DELETE only purges DEAD tokens (revoked or expired).
  password_reset_tokens  SELECT/INSERT/UPDATE possession-driven (request,
                reset and the delivery worker all run pre-GUC); DELETE has no
                policy — nothing in the app or the suite purges these rows.
  user_mfa_secrets  permissive DML: enroll/confirm/disable and the
                mfa_verify login step all run on a CurrentUserDep session,
                which binds no user GUC.
  tenants       SELECT/INSERT possession-driven (register's slug probe and
                the refresh-path lifecycle check run pre-GUC); UPDATE and
                DELETE require a bound app.tenant_id — every writer
                (settings, lifecycle, offboarding purge, teardowns) binds it —
                EXCEPT the §147 break-glass route, which is cross-tenant BY
                DESIGN (platform PATCH /admin/tenants/{id}/status transitions
                a tenant the admin is not a member of, with app.tenant_id
                bound to their own). Its admission is the app.is_platform_admin
                GUC, which deps.get_current_user re-verifies against the users
                row on EVERY request; the one-shot break-glass capability
                check stays app-side, like every other GUC-keyed policy here.

Finding 2: the RBAC reference tables ``permissions``, ``roles``,
``role_permissions``, ``plans`` — and the ops table ``alembic_version``,
which the blanket ``GRANT ALL PRIVILEGES ON ALL TABLES`` also covered — were
fully writable by the runtime role. The app only ever SELECTs them
(deps._role_permissions, register's owner-role lookup); seeding happens in
provision.py over the ADMIN connection. Their INSERT/UPDATE/DELETE are
revoked here and re-frozen in provision.py's PRIVILEGE_REFREEZE so both
deploy orders converge. ``dr_policy`` is deliberately NOT frozen: unlike the
others it has a legitimate runtime write — DRService.get_policy lazily
INSERTs the singleton on the first platform health read
(platform/router.py -> check_dr_health), and complete_restore_test stamps
the last test result on the same row — so revoking would 500 that endpoint.
Reported to the audit instead; freezing it needs an app change first (seed
the singleton in provision, move the stamp off the runtime role).

Every sales_app-dependent statement is guarded on the role existing: CI runs
alembic BEFORE provision creates it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fd2026100410"
down_revision: str | None = "fd2026100409"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
_USER_GUARD = "NULLIF(current_setting('app.user_id', true), '')::uuid"
# Set by deps.get_current_user on EVERY request, from the DB-verified
# users.is_platform_admin — never from the JWT claim. Admits the §147
# break-glass route, whose target tenant is deliberately not the bound one.
_ADMIN_GUARD = "coalesce(current_setting('app.is_platform_admin', true), '') = 'true'"

# Possession of an open reset flow is what admits the reset write: the flow
# binds no GUC, reads the token row by hash, updates the user row and consumes
# the token — and the ORM flushes the token's consumption UPDATE BEFORE the
# user UPDATE (dependents first), so any `consumed_at IS NULL` predicate is a
# StaleDataError waiting to happen. `requested_at` is immutable and the token
# TTL is one hour, so "a reset was requested for this user within the hour"
# says the same thing without depending on flush order.
_LIVE_RESET_TOKEN = (
    "EXISTS (SELECT 1 FROM public.password_reset_tokens prt "
    "WHERE prt.user_id = users.id "
    "AND prt.requested_at > now() - interval '1 hour')"
)
# A user holding a live session must not be purgeable through a stray DELETE.
_NO_LIVE_SESSION = (
    "NOT EXISTS (SELECT 1 FROM public.refresh_tokens rt "
    "WHERE rt.user_id = users.id AND rt.revoked_at IS NULL)"
)

_AUTH_TABLES = (
    "users",
    "refresh_tokens",
    "password_reset_tokens",
    "user_mfa_secrets",
    "tenants",
)

# The runtime role reads these; it must never write them. (TRUNCATE,
# REFERENCES, TRIGGER and MAINTAIN were already revoked on ALL tables by
# fd2026100409 — repeated here so this freeze stands alone.) dr_policy is
# excluded ON PURPOSE — see the module docstring: DRService.get_policy writes
# it at runtime from the platform health endpoint.
_REFERENCE_TABLES = (
    "permissions",
    "roles",
    "role_permissions",
    "plans",
    "alembic_version",
)


def _grant_fn(fn_signature: str) -> None:
    op.execute(
        f"""DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            GRANT EXECUTE ON FUNCTION {fn_signature} TO sales_app;
          END IF;
        END $$"""
    )


def upgrade() -> None:
    # --- pre-auth lookup helpers (for the app-side narrowing that follows) --
    # SECURITY DEFINER + pinned search_path, mirroring resolve_channel_tenant.
    # Returns ONLY the columns the login path consumes — never the whole row —
    # so adopting it in identity service/deps lets users_read collapse from
    # "possession-driven" to a self-row policy without widening anything.
    op.execute(
        """CREATE OR REPLACE FUNCTION public.auth_lookup_user_by_email(p_email text)
           RETURNS TABLE (id uuid, password_hash text, is_active boolean,
                          auth_version integer, is_platform_admin boolean)
           LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
           AS $fn$
               SELECT u.id, u.password_hash, u.is_active, u.auth_version,
                      u.is_platform_admin
                 FROM public.users u
                WHERE lower(u.email) = lower(p_email)
                LIMIT 1
           $fn$"""
    )
    op.execute("REVOKE ALL ON FUNCTION public.auth_lookup_user_by_email(text) FROM PUBLIC")
    _grant_fn("public.auth_lookup_user_by_email(text)")

    # Membership probe for the pre-tenant paths (the tenant_users row IS the
    # membership fact; tenant_users keeps its own self-access policy).
    op.execute(
        """CREATE OR REPLACE FUNCTION public.auth_user_is_tenant_member(
               p_user uuid, p_tenant uuid
           ) RETURNS boolean
           LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
           AS $fn$
               SELECT EXISTS (
                   SELECT 1 FROM public.tenant_users tu
                    WHERE tu.user_id = p_user AND tu.tenant_id = p_tenant
               )
           $fn$"""
    )
    op.execute("REVOKE ALL ON FUNCTION public.auth_user_is_tenant_member(uuid, uuid) FROM PUBLIC")
    _grant_fn("public.auth_user_is_tenant_member(uuid, uuid)")

    # --- Finding 1: FORCE RLS on the five global auth tables ---------------
    for table in _AUTH_TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")

    # users -------------------------------------------------------------
    op.execute("DROP POLICY IF EXISTS users_preauth_read ON public.users")
    op.execute(
        # BLOCKED from self-scoping without an app change: deps.get_current_user
        # (every authenticated request), the login/register/reset email lookups
        # and the refresh/mfa id lookups all run before any GUC is bound. The
        # possession credential (email) is a query parameter, invisible to the
        # policy. Narrow to id = self via auth_lookup_user_by_email adoption.
        """CREATE POLICY users_preauth_read ON public.users
            FOR SELECT USING (true)"""
    )
    op.execute("DROP POLICY IF EXISTS users_register_insert ON public.users")
    op.execute(
        # register / accept_invitation / sso_login insert before any GUC; an
        # INSERT reveals nothing about other rows.
        """CREATE POLICY users_register_insert ON public.users
           FOR INSERT WITH CHECK (true)"""
    )
    op.execute("DROP POLICY IF EXISTS users_self_update ON public.users")
    op.execute(
        f"""CREATE POLICY users_self_update ON public.users
            FOR UPDATE USING (id = {_USER_GUARD} OR {_LIVE_RESET_TOKEN})
            WITH CHECK (id = {_USER_GUARD} OR {_LIVE_RESET_TOKEN})"""
    )
    op.execute("DROP POLICY IF EXISTS users_purge_delete ON public.users")
    op.execute(
        f"""CREATE POLICY users_purge_delete ON public.users
            FOR DELETE USING ({_NO_LIVE_SESSION})"""
    )

    # refresh_tokens ------------------------------------------------------
    op.execute("DROP POLICY IF EXISTS refresh_tokens_possession_read ON public.refresh_tokens")
    op.execute(
        # BLOCKED from self-scoping without an app change: refresh()/logout()
        # look up by token_hash pre-GUC and the reuse/family revocations update
        # by user_id pre-GUC (_revoke_family_on_reuse opens its own session).
        # The hash IS the possession credential and is invisible to the policy.
        """CREATE POLICY refresh_tokens_possession_read ON public.refresh_tokens
           FOR SELECT USING (true)"""
    )
    op.execute("DROP POLICY IF EXISTS refresh_tokens_issue_insert ON public.refresh_tokens")
    op.execute(
        # _issue_pair inserts on the refresh/mfa_verify/sso paths, which bind no
        # GUC (login's own insert does — but the policy must admit both).
        """CREATE POLICY refresh_tokens_issue_insert ON public.refresh_tokens
           FOR INSERT WITH CHECK (true)"""
    )
    op.execute("DROP POLICY IF EXISTS refresh_tokens_rotation_update ON public.refresh_tokens")
    op.execute(
        # Rotation (refresh/logout) and the reset/reuse family revocation all
        # update pre-GUC.
        """CREATE POLICY refresh_tokens_rotation_update ON public.refresh_tokens
           FOR UPDATE USING (true)"""
    )
    op.execute("DROP POLICY IF EXISTS refresh_tokens_purge_delete ON public.refresh_tokens")
    op.execute(
        # Only dead sessions may be purged — deleting a LIVE token would be an
        # unauthenticated logout of another user's session.
        """CREATE POLICY refresh_tokens_purge_delete ON public.refresh_tokens
           FOR DELETE USING (revoked_at IS NOT NULL OR expires_at < now())"""
    )

    # password_reset_tokens -------------------------------------------------
    op.execute("DROP POLICY IF EXISTS prt_possession_read ON public.password_reset_tokens")
    op.execute(
        # BLOCKED: request_password_reset queries by user_id pre-GUC, the reset
        # flow by token_hash pre-GUC, and the delivery worker sweeps due rows.
        """CREATE POLICY prt_possession_read ON public.password_reset_tokens
           FOR SELECT USING (true)"""
    )
    op.execute("DROP POLICY IF EXISTS prt_request_insert ON public.password_reset_tokens")
    op.execute(
        """CREATE POLICY prt_request_insert ON public.password_reset_tokens
           FOR INSERT WITH CHECK (true)"""
    )
    op.execute("DROP POLICY IF EXISTS prt_consume_update ON public.password_reset_tokens")
    op.execute(
        # Consumption, throttling and lease management all run pre-GUC.
        """CREATE POLICY prt_consume_update ON public.password_reset_tokens
           FOR UPDATE USING (true)"""
    )
    # No DELETE policy — RLS denies it outright; nothing purges these rows.

    # user_mfa_secrets ------------------------------------------------------
    op.execute("DROP POLICY IF EXISTS user_mfa_secrets_read ON public.user_mfa_secrets")
    op.execute(
        # BLOCKED: the mfa_verify login step and the enroll/confirm/disable
        # routes run on a CurrentUserDep session, which binds no user GUC.
        """CREATE POLICY user_mfa_secrets_read ON public.user_mfa_secrets
           FOR SELECT USING (true)"""
    )
    op.execute("DROP POLICY IF EXISTS user_mfa_secrets_enroll_insert ON public.user_mfa_secrets")
    op.execute(
        """CREATE POLICY user_mfa_secrets_enroll_insert ON public.user_mfa_secrets
           FOR INSERT WITH CHECK (true)"""
    )
    op.execute("DROP POLICY IF EXISTS user_mfa_secrets_update ON public.user_mfa_secrets")
    op.execute(
        """CREATE POLICY user_mfa_secrets_update ON public.user_mfa_secrets
           FOR UPDATE USING (true)"""
    )
    op.execute("DROP POLICY IF EXISTS user_mfa_secrets_delete ON public.user_mfa_secrets")
    op.execute(
        # disable_mfa deletes pre-GUC.
        """CREATE POLICY user_mfa_secrets_delete ON public.user_mfa_secrets
           FOR DELETE USING (true)"""
    )

    # tenants ---------------------------------------------------------------
    op.execute("DROP POLICY IF EXISTS tenants_preauth_read ON public.tenants")
    op.execute(
        # BLOCKED: register's slug-uniqueness probe and the refresh-path
        # lifecycle check (_assert_tenant_allows_login) read tenants pre-GUC —
        # and refresh() binds no GUC at all before that read.
        """CREATE POLICY tenants_preauth_read ON public.tenants
           FOR SELECT USING (true)"""
    )
    op.execute("DROP POLICY IF EXISTS tenants_register_insert ON public.tenants")
    op.execute(
        # register inserts the tenant before bind_tenant (the flush must see
        # the row first to bind it).
        """CREATE POLICY tenants_register_insert ON public.tenants
           FOR INSERT WITH CHECK (true)"""
    )
    op.execute("DROP POLICY IF EXISTS tenants_bound_update ON public.tenants")
    op.execute(
        # Every in-tenant writer (settings, lifecycle, offboarding purge,
        # teardowns) runs under bind_tenant — a session without a bound tenant
        # mutates nothing. The platform-admin OR-branch keeps the §147
        # break-glass route alive: it transitions tenants the admin holds no
        # membership in, and the GUC it reads is re-verified against the users
        # row by deps.get_current_user on every request.
        f"""CREATE POLICY tenants_bound_update ON public.tenants
            FOR UPDATE USING (id = {_TENANT_GUARD} OR {_ADMIN_GUARD})
            WITH CHECK (id = {_TENANT_GUARD} OR {_ADMIN_GUARD})"""
    )
    op.execute("DROP POLICY IF EXISTS tenants_bound_delete ON public.tenants")
    op.execute(
        f"""CREATE POLICY tenants_bound_delete ON public.tenants
            FOR DELETE USING (id = {_TENANT_GUARD})"""
    )

    # --- Finding 2: the RBAC reference plane is SELECT-only ----------------
    for table in _REFERENCE_TABLES:
        op.execute(
            f"""DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
                REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN
                  ON public.{table} FROM sales_app;
              END IF;
            END $$"""
        )


def downgrade() -> None:
    # Restore the pre-hardening state verbatim: no RLS on the five tables, the
    # reference tables writable again, the helpers gone. Only the tables the
    # upgrade actually froze are re-granted — dr_policy was never touched.
    op.execute(
        """DO $$
        DECLARE
          tbl text;
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            FOREACH tbl IN ARRAY ARRAY['permissions', 'roles', 'role_permissions',
                                       'plans', 'alembic_version']
            LOOP
              EXECUTE format('GRANT INSERT, UPDATE, DELETE ON public.%I TO sales_app', tbl);
            END LOOP;
          END IF;
        END $$"""
    )
    for table in _AUTH_TABLES:
        for policy in (
            "users_preauth_read",
            "users_register_insert",
            "users_self_update",
            "users_purge_delete",
            "refresh_tokens_possession_read",
            "refresh_tokens_issue_insert",
            "refresh_tokens_rotation_update",
            "refresh_tokens_purge_delete",
            "prt_possession_read",
            "prt_request_insert",
            "prt_consume_update",
            "user_mfa_secrets_read",
            "user_mfa_secrets_enroll_insert",
            "user_mfa_secrets_update",
            "user_mfa_secrets_delete",
            "tenants_preauth_read",
            "tenants_register_insert",
            "tenants_bound_update",
            "tenants_bound_delete",
        ):
            op.execute(f"DROP POLICY IF EXISTS {policy} ON public.{table}")
        op.execute(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION IF EXISTS public.auth_lookup_user_by_email(text)")
    op.execute("DROP FUNCTION IF EXISTS public.auth_user_is_tenant_member(uuid, uuid)")
