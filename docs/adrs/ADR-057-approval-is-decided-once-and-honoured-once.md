# ADR-057 — An approval is decided once, honoured once, and a partial queue says so

Date: 2026-09-24. Wave 5 / §135 approvals surface.
Evidence: `backend/app/modules/ai/approvals.py` (`decide` 102-145, `find_granted` 148-201,
`list_for_tenant` 212-236), `backend/tests/gate/test_gate_approval_double_grant.py` (3, needs a
database), `backend/tests/test_approvals_queue_read.py` (5; 2 run anywhere),
`frontend/src/components/approvals/` + `frontend/e2e/approvals.spec.ts`.

## Context

Spec §135 parks a HIGH-risk tool call — `create_order`, `refund`, a purge — in `PENDING` and does not
run it until a human decides. The column that closes a grant states the promise in the model itself:
*"an approval authorizes exactly ONE execution of the action"* (`ai/models.py:335`). Nothing enforced
that, because both reads on the path were a plain `SELECT` followed by a separate write — the same
check-then-act shape this project keeps finding and fixing:

* **Two reviewers, one decision.** `ApprovalService.decide` read the row, checked `status == PENDING`
  and wrote the decision. Two concurrent decides — two tabs, a double-click across two dialogs, or
  two staff who both saw the same queue — both read `PENDING`, both returned 200, and the route
  enqueues a `message.received` resume **for every successful APPROVE** (`ai/router.py:345-356`). One
  human decision released the parked run twice.
* **One grant, two executions.** The resume path is `find_granted` then `consume` then the handler
  (`ai/runtime.py:687-711`). Both racers read the same row while `consumed_at` was still `NULL`, both
  consumed it, and both called `spec.handler`. The second one is the double refund.

Neither window had a backstop. `/api/v1/ai/approvals` is deliberately absent from the idempotency
allow-list (`core/idempotency.py:115-123`), so no client key deduplicated either step — and a key
would not have closed the second window anyway, because the two racers are a worker and a resume, not
a client and its retry.

A second, quieter dishonesty sat on the read side. `list_for_tenant` has always defaulted to a
bounded page, and the route never passed or reported anything about it: a reviewer shown exactly 100
pending rows could not distinguish 100 from 1000, while §135's premise is that this queue is the set
of decisions owed.

## Decisions

### 1. The row is the lock, on both sides

`decide`'s and `find_granted`'s SELECTs carry `.with_for_update()` (`approvals.py:126`, `198`). Under
READ COMMITTED the loser blocks on the winner's lock, and when the winner commits Postgres
re-evaluates the query's predicate against the **new** row version:

* `decide` gets the updated row, so `status != "PENDING"` and it raises the sentence the client
  already treats as terminal (`"approval already APPROVED"`) — no new response shape, no new code.
* `find_granted` gets a row that no longer matches `consumed_at IS NULL`, so it returns `None` and the
  runtime takes its existing park branch. The loser does not execute; it asks a human again.

One line each, no control-flow change at the call sites, and the guarantee now lives where the state
transition lives rather than in a caller's good intentions.

### 2. The queue reports its own bound

`APPROVALS_PAGE_SIZE = 100` is declared next to the TTL it sits beside, `list_for_tenant` fetches
`limit + 1` and returns `(page, truncated)`, and the route answers
`{items, truncated}` (`router.py:317`). The screen renders a notice and a `100+` badge when the flag
is set (`approvals/page.tsx`, `labels.queueTruncated`).

The probe row is fetched to *count* and never returned as *content* — that boundary is its own test,
because it is the off-by-one a reader cannot see in the code. A `COUNT(*)` was rejected for the same
reason the outbox does not pre-count: the page boundary is the cheap, always-consistent answer, and
"there is more" is all the reviewer needs to act on.

### 3. What stays exactly as it was

`consume` still writes `consumed_at` in Python rather than claiming itself with a conditional
`UPDATE … WHERE consumed_at IS NULL RETURNING`. The lock above makes that safe; the atomic-claim form
would be safe without it, and is the shape to reach for first if this read ever stops taking the lock.
The frontend still mints one Idempotency-Key per dialog open even though this route ignores it: it
costs nothing, it is the discipline every other write screen uses, and it becomes load-bearing the day
this path is allow-listed. That it is *inert here* is stated in `approvals/decision.ts`, so no reader
mistakes it for the guard.

## Consequences

- A double-clicked approve is now a 400 with the server's own sentence, and the dialog that receives
  it is already written to freeze on that sentence rather than re-mint a key. The client's stated
  reasoning and the server's behaviour now agree.
- The loser of a grant race creates a **second** `PENDING` approval for an action that just ran. That
  is a human seeing one redundant request, deliberately chosen over a silent double execution. It is
  possible because `request()`'s own de-duplication is a non-unique lookup — see Rejected §3.
- `find_granted`'s lock is held across `spec.handler`, so a slow HIGH-risk tool serialises concurrent
  resumes of the *same* conversation. Different conversations take different approval rows and do not
  contend.
- The gate test skips without an application database; CI is the venue that publishes its verdict,
  and the mutation that proves it can fail is stated in its own docstring rather than claimed here.
- `GET /ai/approvals` gained a response key. Both callers were updated in the same commit; the shape
  is asserted by a test, not by a comment.

## Rejected

1. **`SELECT … FOR UPDATE SKIP LOCKED` in `find_granted`.** With one candidate row the loser would
   skip to *no grant* — the same outcome — but on a queue with several matching grants it would
   silently pass over the row a legitimate racer holds and could pick a different one. Blocking is the
   semantics the promise needs: wait, then re-read the truth.
2. **Adding `/api/v1/ai/approvals` to the idempotency allow-list.** Extending that list is documented
   as "a deliberate decision that a duplicate execution would be harmful", and this path's duplicate
   is already refused by the status transition once it is locked. Worse, a key does not cover the
   second window at all: there the racers are two resumes, not a request and its replay.
3. **A unique index for pending duplicates.** `approval_requests` carries a non-unique
   `(tenant_id, status, expires_at)` index, and `request()` de-duplicates by lookup. Two concurrent
   parks can therefore both insert a `PENDING` row for the same action+arguments. Left open on
   purpose: a partial unique index would also have to express `payload_hash` matching and the stale
   path, and the failure it prevents is one redundant human request — not an unauthorized execution.
   Recorded here so the next reader does not mistake the missing index for the missing lock.
4. **Deriving "already honoured" from the run instead of the row.** A resumed run knows what it
   executed; the gate does not read runs. That would put the guard one layer away from the state it
   guards, and the state column is already the thing being protected.
