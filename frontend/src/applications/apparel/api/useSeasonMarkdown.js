import { useMutation, useQueryClient } from "@tanstack/react-query";
import { posApi } from "./posApi";
import { applyBody, previewBody, shapePreview } from "./seasonMarkdown";

/**
 * Preview, then apply. Preview writes nothing. Apply sends the token the preview returned, so what
 * the owner approved is exactly what is written. After a successful apply every price on screen is
 * stale (stock rows, the catalogue, the profit and sell-through reports), so the cached lists are
 * dropped and refetched rather than patched by hand.
 */
export function useSeasonMarkdown() {
  const qc = useQueryClient();
  const preview = useMutation({
    mutationFn: async (input) => shapePreview(await posApi.seasonMarkdownPreview(previewBody(input))),
  });
  const apply = useMutation({
    mutationFn: ({ preview: p, brandId = "" }) => posApi.seasonMarkdownApply(applyBody(p, brandId)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cashier"] }),
  });
  return { preview, apply };
}
