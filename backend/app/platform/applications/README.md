# applications

Which product a workspace may use, and whether it has switched it on.

A plan says what a business **may** use. An installation says what it **did** switch on, and how
far its setup got. Keeping those two questions apart is what lets one shop buy purchasing without
buying a warehouse, while `catalog` and `inventory` keep serving both.

## Where things are

| File | What it is |
|---|---|
| `manifests.py` | The manifest registry: what each application IS, in code. A database row may decide whether an application is for sale, at what price, and whether this workspace bought it. It may never decide what the application can do — so capabilities live here, in the release |
| `access.py` | The one decision that says whether a workspace may use an application: `tenant operational AND user has workspace access` |
| `install.py` | Turning a licensed product into an installed one, and recording how far its setup got |
| `repository.py` | Reads of entitlements and installation state (no writes, no policy) |
| `dependencies.py` | `workspace_gate`: the dependency a route declares to say which application it serves |
| `routing.py` | Which application a route group belongs to (`GROUP_APPLICATIONS`). Nothing gates on it yet; it exists so that when enforcement lands there is no route whose owner was never decided |
| `models.py` | `plan_application_inclusions`, `workspace_app_installations` |
| `router.py` | `GET /applications` — what this workspace has, and what each product is waiting on |

## Rules

- **The database carries commerce and installation state, never capability.** A row cannot
  invent a route or run code.
- **A refusal says which one it is.** "You did not buy this" and "you have not finished setting
  this up" are different answers, and the interface shows them differently.
- **Routes ask, they do not decide.** A route declares `workspace_gate`; the verdict comes from
  `access.py`.

## HTTP

Route prefix `/applications`, registered in `app/main.py`.

## Tables

- `plan_application_inclusions`
- `workspace_app_installations`

## Depends on

`billing`, `identity`. Seven other modules import `applications.dependencies` to gate their own
routes (`catalog`, `conversations`, `customers`, `inventory`, `pos`, `purchasing`, `segments`);
those edges are counted by `tests/test_module_boundaries.py`.
