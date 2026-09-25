# components

Shared presentational pieces only — the error panel, an empty state, a section
header. No component here may import from `@tauri-apps/*`, read a store, or format
money itself; it takes props and renders them.

Phase 0 has one real component family, and it is the failure surface
(`../app/error-boundary.tsx`), because every later screen inherits it rather than
writing its own.
