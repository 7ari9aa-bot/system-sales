import React, { useEffect, useMemo, useState } from "react";

const sizeLabel = (bytes) => (bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / (1024 * 1024)).toFixed(1)} MB`);

// A caption rides with a file on Telegram only up to 1024 characters; beyond that the text is sent
// as its own message right after, so nothing is lost, and nothing here needs to cut it.
const THEME = {
  messenger: { accent: "#0084ff", hover: "#0073e6", soft: "#f0f2f5" },
  telegram: { accent: "#3390ec", hover: "#2a7fd4", soft: "#eff8fd" },
};

/**
 * What the agent is about to send on Messenger or Telegram, shown before anything reaches the
 * customer. Nothing is uploaded until Send is pressed, so cancelling costs nothing. Both channels
 * carry a caption with the file, so there is a text box here.
 */
export default function ChannelAttachPreview({ channel, file, kind, busy = false, error = "", lang = "ar", onSend, onCancel }) {
  const ar = lang === "ar";
  const theme = THEME[channel] || THEME.messenger;
  const [caption, setCaption] = useState("");
  const url = useMemo(() => (file && (kind === "image" || kind === "video") ? URL.createObjectURL(file) : null), [file, kind]);
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);

  return (
    <div role="dialog" aria-modal="true" aria-label={ar ? "معاينة" : "Preview"} data-testid="channel-attach-preview" dir={ar ? "rtl" : "ltr"}
      className="absolute inset-0 z-40 flex flex-col bg-white" onKeyDown={(e) => { if (e.key === "Escape" && !busy) onCancel?.(); }}>
      <div className="flex h-14 shrink-0 items-center gap-3 border-b border-[#e4e6eb] px-4">
        <button type="button" onClick={onCancel} disabled={busy} aria-label={ar ? "إلغاء" : "Cancel"} data-testid="channel-attach-cancel"
          className="grid h-9 w-9 place-items-center rounded-full text-[20px] leading-none text-[#65676b] hover:bg-[#f0f2f5] disabled:opacity-40">×</button>
        <div className="min-w-0 flex-1 truncate text-[15px] font-semibold" dir="auto">{file?.name}</div>
      </div>
      <div className="grid min-h-0 flex-1 place-items-center overflow-auto p-4">
        {kind === "image" && url && <img src={url} alt={file?.name || ""} data-testid="channel-preview-image" className="max-h-full max-w-full rounded-xl object-contain" />}
        {kind === "video" && url && <video src={url} controls data-testid="channel-preview-video" className="max-h-full max-w-full rounded-xl" />}
        {(kind === "audio" || kind === "document") && (
          <div data-testid="channel-preview-file" className="flex w-72 flex-col items-center gap-2 rounded-xl p-8 text-center" style={{ background: theme.soft }}>
            <div className="text-[15px]" dir="auto">{file?.name}</div>
            <div className="text-[13px] text-[#65676b]">{sizeLabel(file?.size || 0)}</div>
          </div>
        )}
      </div>
      {error && <p role="alert" data-testid="channel-attach-error" className="mx-4 mb-2 text-[14px] text-[#d93025]">{error}</p>}
      <div className="flex shrink-0 items-center gap-3 border-t border-[#e4e6eb] px-4 py-3">
        <input value={caption} onChange={(e) => setCaption(e.target.value)} disabled={busy} dir="auto" data-testid="channel-attach-caption"
          placeholder={ar ? "أضف نصًا (اختياري)" : "Add a caption (optional)"}
          onKeyDown={(e) => { if (e.key === "Enter" && !busy) { e.preventDefault(); onSend?.(caption.trim()); } }}
          className="h-10 min-w-0 flex-1 rounded-full border border-[#e4e6eb] bg-white px-4 text-[14px] outline-none focus:border-[#0084ff] disabled:opacity-60" />
        <button type="button" data-testid="channel-attach-send" disabled={busy} onClick={() => onSend?.(caption.trim())}
          style={{ background: theme.accent }} className="h-10 shrink-0 rounded-full px-5 text-[14px] font-semibold text-white hover:opacity-90 disabled:opacity-40">
          {busy ? (ar ? "جارٍ الرفع..." : "Uploading...") : error ? (ar ? "إعادة المحاولة" : "Try again") : (ar ? "إرسال" : "Send")}
        </button>
      </div>
    </div>
  );
}
