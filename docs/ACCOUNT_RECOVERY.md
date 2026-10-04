# Account recovery email setup

The backend uses a durable PostgreSQL queue and Resend to deliver password
reset links. The raw token is encrypted while queued and is deleted from the
queue after delivery; password verification uses only its SHA-256 digest.
Requests return the same response for existing and unknown accounts.

## Before enabling production mail

1. Create a Resend account and add a sending domain owned by the company.
2. Publish the SPF and DKIM records Resend provides for that domain. Add a
   DMARC policy for the domain and wait until Resend reports the domain as
   verified. Use a sender on that verified domain in `EMAIL_FROM`.
3. Create a Resend API key limited to sending email. Store it as a server-only
   Railway variable named `RESEND_API_KEY`; never use a `VITE_` or `NEXT_PUBLIC_`
   variable.
4. Set the following in both the API and worker services:

   - `EMAIL_DELIVERY_ENABLED=true`
   - `EMAIL_FROM=Security <security@your-verified-domain>`
   - `FRONTEND_PUBLIC_URL=https://your-production-frontend.example`
   - `RESEND_API_KEY=<server-only sending key>`
   - the same `SECRETS_MASTER_KEY` and database URL used by the API

5. Keep staging on a separate verified sender/subdomain and separate Resend
   key. Do not point preview builds at the production API or send test emails
   using production credentials.

Until these settings are complete, the API accepts reset requests without
revealing whether an account exists, but email delivery stays disabled. The
worker will not contact Resend. The scheduler worker must be running for queued
reset messages and expired-offboarding sweeps to execute.

Local/test environments may leave delivery disabled. Staging and production
now refuse to start with `EMAIL_DELIVERY_ENABLED=false` or incomplete sender
settings, so a release cannot silently advertise a recovery flow that cannot
send mail.

## Operational behavior

- Reset links expire after one hour, are single-use, and are placed in the URL
  fragment so they are not sent in HTTP requests or referrer headers.
- A new request invalidates previous reset links. Requests are throttled to one
  per account per minute and `/auth/*` is also rate limited by IP.
- Password reset increments the user's authentication version and revokes all
  refresh tokens. Existing access tokens stop working immediately.
- Resend failures retry with backoff and a stable idempotency key. The queue
  does not log email addresses, reset tokens, or provider response bodies.
- Apply the Alembic migration before rolling out the API/worker code.

## Data export and offboarding

The offboarding export contains tenant-owned database rows, including message,
order, payment, refund, and AI-memory records. Credential-like columns and
operational queues are omitted and listed in the export metadata. Attachments
are exported as metadata; the binary objects remain in object storage. Keep the
export endpoint available during the 30-day retention period. The scheduler
hard-deletes only matured `offboarding` tenants, one tenant-bound transaction
at a time, while preserving the purge audit record.
