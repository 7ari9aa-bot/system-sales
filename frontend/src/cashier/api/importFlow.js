/**
 * Which step of the import screen a session belongs to. The server's status decides, never local
 * state, so a merchant who reloads or comes back mid-import lands where the import actually is.
 */
export const STEPS = [
  { key: "upload", label: "رفع الملف" },
  { key: "mapping", label: "ربط الأعمدة" },
  { key: "review", label: "المراجعة" },
  { key: "run", label: "الاستيراد" },
];

const STEP_OF_STATUS = {
  analyzed: "mapping",
  mapped: "mapping",
  validating: "review",
  validated: "review",
  running: "run",
  completed: "run",
  cancelled: "run",
  failed: "run",
};

export const stepOf = (session) => (session ? (STEP_OF_STATUS[session.status] ?? "mapping") : "upload");

/** The mapping the screen shows: the merchant's unsaved choices over what the server suggested. */
export const mergedMapping = (session, draft) =>
  Object.fromEntries(Object.entries(session?.sheets ?? {}).map(([sheet, s]) => [sheet, draft?.[sheet] ?? s.mapping]));

/** The body of "save mapping": every sheet's full mapping, plus the chosen duplicate policy. */
export const mappingBody = (session, draft, policy) => ({
  mapping: mergedMapping(session, draft),
  options: { duplicate_policy: policy === "update" ? "update" : "skip" },
});
