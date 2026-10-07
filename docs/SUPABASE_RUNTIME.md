# Supabase runtime responsibilities

Use Supabase for the services this application already fits well:

| Supabase service | Application responsibility | Free-plan fit |
| --- | --- | --- |
| PostgreSQL | Primary relational data store. The API and workers connect with the restricted `sales_app` role through Supavisor; migrations use a separate owner connection. | Good for development and staging while under the 500 MB database quota. |
| Storage | Durable channel attachments (images, audio, and other media) fetched from provider URLs before those URLs expire. Keep the bucket private; the API returns short-lived signed read URLs after its tenant-scoped query. | Useful for virtual data and early testing. Watch the 1 GB object-storage and 5 GB egress quotas. |
| pgvector | Existing AI embedding/search storage in PostgreSQL. The Python AI services own embedding generation, retrieval policy, and budget accounting. | Keep with the primary data while monitoring database size. |
| Auth | The app currently owns password verification, session/refresh rotation, MFA, tenant selection, and custom access claims in FastAPI. Supabase Auth is a valid full replacement candidate, but a password-only switch is unsafe: auth users, API sessions, MFA, tenant switching, invitations, and claim validation must move as one design. | Keep one identity authority for now. Reconsider a complete Auth migration before launch only if the team wants Supabase Auth to own login, sessions, recovery, and MFA together. Supabase Auth would still need a custom SMTP provider for real user mail. |
| Queues / Redis | The Postgres outbox is the durable source; Redis Streams transport events to independently scaled consumers. Redis also handles rate limits, fairness, and short-lived coordination. | Keep the existing split. PGMQ is a possible future bus adapter, but moving the bus into the same size-limited database adds queue writes/retention pressure and does not remove the other Redis uses. |
| Realtime | The API emits tenant-checked SSE with replay cursors, short-lived stream tokens, and lifecycle checks; Redis Streams is its transport. | Keep for now. Supabase Realtime would require new event publication and channel authorization, plus tokens that its service can verify; it is not a drop-in replacement for the current replay contract. |
| Scheduler / Edge Functions | Railway workers execute tenant-bound jobs, long workflows, provider calls, and retention sweeps. | Keep worker execution outside Edge Functions. Free Edge Functions have a 2-second CPU budget per request and 150-second wall-clock limit, which do not fit the system's worker pools. A future tiny scheduled maintenance trigger could use Supabase Cron without moving business job execution. |
| FastAPI | HTTP contract, tenant and permission checks, domain transactions, channel webhook verification, and orchestration across providers. | Keep on Railway. These are application/domain responsibilities, not Supabase hosting primitives. |

## Storage setup

The `sales` project (`iixxqitfopsgvaheedlg`, `eu-west-1`) already has the S3 protocol enabled and a private `sales-media` bucket. The bucket limit is 27 MiB; the app enforces 25 MiB for fetched channel media and 10 MiB for direct product-image uploads. Keep the larger bucket limit so channel attachments continue to work.

The preferred connection is a dedicated S3 access key pair generated in Supabase Storage settings. S3 keys provide full access to Storage, so keep them server-side and never put them in frontend build variables or browser code. A Supabase Management API PAT (`sbp_…`) is a different credential and cannot replace either S3 key.

When dedicated S3 keys are unavailable, the server can use the Supabase Storage REST fallback with the project URL and the already-provisioned service-role key. This key is also server-only and has broader project privileges than a dedicated Storage key; never expose it to browser code. Both paths use the same private bucket and signed-download behavior.

Configure either the complete S3 pair or the REST fallback for both the Railway API and workers. Use the matching project values for each environment.

S3 variables:

   - `S3_ENDPOINT=https://iixxqitfopsgvaheedlg.storage.supabase.co/storage/v1/s3`
   - `S3_REGION=eu-west-1`
   - `S3_BUCKET=sales-media`
   - `S3_ACCESS_KEY_ID=<Storage S3 access key ID>`
   - `S3_SECRET_ACCESS_KEY=<Storage S3 secret access key>`
   - `S3_SIGNED_URL_TTL_SECONDS=900`

REST fallback variables:

   - `SUPABASE_URL=https://iixxqitfopsgvaheedlg.supabase.co`
   - `SUPABASE_SERVICE_ROLE_KEY=<server-only project key>`
   - `S3_BUCKET=sales-media`
   - `S3_SIGNED_URL_TTL_SECONDS=900`

Staging and production fail closed if neither complete Storage connection is present, if a connection is partial, or if its URL is insecure. Local and test environments may leave Storage unconfigured.

## Identity and email

The current identity model stores password hashes in the application `users` table and issues its own JWT/refresh-token families. Password reset must therefore continue to update that table and revoke the application's sessions in one backend transaction. The durable email queue remains in PostgreSQL and the worker sends through Resend. Supabase's built-in Auth mail server is limited to project-team recipients, currently two messages per hour, and best-effort delivery; it is not a general production email service. If the product later adopts Supabase Auth, migrate registration, login, invitations, MFA, session handling, tenant claims, and authorization together, then configure a custom SMTP provider.

## Free-plan boundary

The Free plan is appropriate for development and staging, not a production availability guarantee: current quotas include 500 MB database size, 1 GB Storage, 5 GB egress, and free projects may pause after low database activity. A project over its database quota can enter read-only mode. Free-plan projects also do not include downloadable database backups. Measure actual use and set a paid-plan/backup and restore decision before launch; do not treat a free project as the only copy of production data.

## References

- [Supabase Auth and JWT access-token hooks](https://supabase.com/docs/guides/auth/auth-hooks/custom-access-token-hook)
- [Supabase password recovery and custom SMTP](https://supabase.com/docs/guides/auth/passwords)
- [Supabase Realtime authorization](https://supabase.com/docs/guides/realtime/authorization)
- [Supabase Queues / pgmq](https://supabase.com/docs/guides/queues)
- [Supabase Edge Function limits](https://supabase.com/docs/guides/functions/limits)
- [Supabase Free plan quotas](https://supabase.com/docs/guides/platform/billing-on-supabase)
- [Supabase Free project pausing](https://supabase.com/docs/guides/platform/free-project-pausing)
- [Supabase production availability and backup checklist](https://supabase.com/docs/guides/deployment/going-into-prod)
