import React, { useEffect, useMemo, useState } from "react";
import { IgClose } from "@/components/instagram/igIcons";
import { IG } from "@/components/instagram/igTheme";

const sizeLabel = (bytes) => (bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / (1024 * 1024)).toFixed(1)} MB`);

/**
 * What the agent is about to send, shown before anything reaches the customer. Nothing is uploaded
 * until Send is pressed, so cancelling costs nothing. Instagram's own preview carries a caption
 * field; the Send API has no caption on an attachment, so the caption travels as its own message
 * right after the file, which is exactly how Instagram draws it (a second bubble under the photo).
 */
export default function IgAttachPreview({ file, kind, busy = false, error = "", lang = "ar", onSend, onCancel }) {
  const ar = lang === "ar";
  const [caption, setCaption] = useState("");
  const url = useMemo(() => (file && (kind === "image" || kind === "video") ? URL.createObjectURL(file) : null), [file, kind]);
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);

  return (
    <div role="dialog" aria-modal="true" aria-label={ar ? "معاينة" : "Preview"} data-testid="ig-attach-preview" dir={ar ? "rtl" : "ltr"}
      className="absolute inset-0 z-40 flex flex-col bg-white" onKeyDown={(e) => { if (e.key === "Escape" && !busy) onCancel?.(); }}>
      <div className="flex h-[64px] shrink-0 items-center gap-3 border-b px-4" style={{ borderColor: IG.border }}>
        <button type="button" onClick={onCancel} disabled={busy} aria-label={ar ? "إلغاء" : "Cancel"} data-testid="ig-attach-cancel"
          className="grid h-9 w-9 place-items-center rounded-full text-[#0c1014] hover:opacity-60 disabled:opacity-40"><IgClose /></button>
        <div className="min-w-0 flex-1 truncate text-[16px] font-semibold" dir="auto">{file?.name}</div>
      </div>
      <div className="grid min-h-0 flex-1 place-items-center overflow-auto p-4">
        {kind === "image" && url && <img src={url} alt={file?.name || ""} data-testid="ig-preview-image" className="max-h-full max-w-full rounded-[18px] object-contain" />}
        {kind === "video" && url && <video src={url} controls data-testid="ig-preview-video" className="max-h-full max-w-full rounded-[18px]" />}
        {(kind === "audio" || kind === "document") && (
          <div data-testid="ig-preview-file" className="flex w-72 flex-col items-center gap-2 rounded-[18px] bg-[#f3f5f7] p-8 text-center">
            <div className="text-[15px]" dir="auto">{file?.name}</div>
            <div className="text-[13px]" style={{ color: IG.secondary }}>{sizeLabel(file?.size || 0)}</div>
          </div>
        )}
      </div>
      <div className="shrink-0 border-t px-4 py-2" style={{ borderColor: IG.border }}>
        <input
          value={caption}
          onChange={(event) => setCaption(event.target.value)}
          disabled={busy}
          dir={ar ? "rtl" : "ltr"}
          data-testid="ig-attach-caption"
          placeholder={ar ? "اكتب تعليقًا..." : "Write a caption..."}
          aria-label={ar ? "تعليق على الملف" : "Caption"}
          onKeyDown={(event) => { if (event.key === "Enter" && !busy) { event.preventDefault(); onSend?.(caption); } }}
          className="h-10 w-full bg-transparent text-[14px] text-[#0c1014] outline-none placeholder:text-[#8e8e8e]"
        />
      </div>
      {error && <p role="alert" data-testid="ig-attach-error" className="mx-4 mb-2 text-[14px]" style={{ color: IG.error }}>{error}</p>}
      <div className="flex shrink-0 items-center justify-end gap-3 border-t px-4 py-3" style={{ borderColor: IG.border }}>
        <button type="button" data-testid="ig-attach-send" disabled={busy} onClick={() => onSend?.(caption)}
          className="h-9 rounded-lg bg-[#4a5df9] px-5 text-[14px] font-semibold text-white hover:bg-[#3a4de0] disabled:opacity-40">
          {busy ? (ar ? "جارٍ الرفع..." : "Uploading...") : error ? (ar ? "إعادة المحاولة" : "Try again") : (ar ? "إرسال" : "Send")}
        </button>
      </div>
    </div>
  );
}
