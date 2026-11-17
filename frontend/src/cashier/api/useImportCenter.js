import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ACTIVE_STATUSES,
  cancelImport,
  getImportPreview,
  getImportSession,
  listImportSessions,
  saveImportMapping,
  startImport,
  uploadImageArchive,
  uploadImportFile,
  validateImport,
} from "./importCenter";
import { STOCK_KEY } from "./useStock";

export const IMPORT_KEY = ["cashier", "imports"];

/** While an import runs the server is the only one who knows how far it got, so ask again. */
export const POLL_MS = 2000;

/** How long to wait before asking again: only a running import keeps moving by itself. */
export const pollInterval = (session) => (ACTIVE_STATUSES.includes(session?.status) ? POLL_MS : false);

/**
 * Reads one session and, when it is seen to have just stopped running, tells the stock screens and
 * the recent-imports list to re-read: that is when the new products and balances actually exist.
 */
export async function readSession(qc, id, signal) {
  const previous = qc.getQueryData([...IMPORT_KEY, "session", id])?.status;
  const next = await getImportSession(id, { signal });
  if (previous === "running" && next.status !== "running") {
    qc.invalidateQueries({ queryKey: STOCK_KEY });
    qc.invalidateQueries({ queryKey: [...IMPORT_KEY, "recent"] });
  }
  return next;
}

/** One session. It refreshes by itself only while the import is running, and stops on its own. */
export function useImportSession(id) {
  const qc = useQueryClient();
  return useQuery({
    queryKey: [...IMPORT_KEY, "session", id],
    queryFn: ({ signal }) => readSession(qc, id, signal),
    enabled: Boolean(id),
    refetchInterval: (query) => pollInterval(query.state.data),
    refetchIntervalInBackground: false,
  });
}

/** The rows that would not import, plus the counters, for the review step. */
export function useImportPreview(id, enabled) {
  return useQuery({
    queryKey: [...IMPORT_KEY, "preview", id],
    queryFn: ({ signal }) => getImportPreview(id, { sample: 20, signal }),
    enabled: Boolean(id) && enabled,
  });
}

/** Recent imports, so a merchant who left the page can find the one that was running. */
export function useRecentImports() {
  return useQuery({
    queryKey: [...IMPORT_KEY, "recent"],
    queryFn: async () => (await listImportSessions()).items ?? [],
  });
}

/** What a finished step writes into the cache: the session's new fields over what is already known. */
export function applySession(qc, session, { refreshStock = false } = {}) {
  if (!session?.id) return;
  qc.setQueryData([...IMPORT_KEY, "session", session.id], (old) => ({ ...old, ...session }));
  qc.invalidateQueries({ queryKey: [...IMPORT_KEY, "recent"] });
  qc.invalidateQueries({ queryKey: [...IMPORT_KEY, "preview", session.id] });
  if (refreshStock) qc.invalidateQueries({ queryKey: STOCK_KEY });
}

/** Every step writes the session's new state straight into the cache, so the screen never lags. */
function useSessionMutation(fn, opts) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: (session) => applySession(qc, session, opts) });
}

export const useUploadImport = () => useSessionMutation(uploadImportFile);
export const useUploadImageArchive = (id) => useSessionMutation((file) => uploadImageArchive(id, file));
export const useSaveMapping = (id) => useSessionMutation((body) => saveImportMapping(id, body));
export const useValidateImport = (id) => useSessionMutation(() => validateImport(id));
export const useStartImport = (id) => useSessionMutation(() => startImport(id));
export const useCancelImport = (id) => useSessionMutation(() => cancelImport(id), { refreshStock: true });
