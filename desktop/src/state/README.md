# state

Zustand stores for **UI and application state only**: which panel is open, the
connection indicator's last transition, draft form scaffolding.

Server values — messages, customers, orders, balances — never live here. They come
from TanStack Query, which owns their freshness, and a store that copies one of
them is a second cache with no invalidation path and no tenant boundary. When a
workspace switches, `queryClient.clear()` and the local read model are what have to
go, and this directory must not be the reason something survives.
