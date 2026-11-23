import React, { useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, ImagePlus, Loader2, X } from "lucide-react";
import { PUBLISH_LIMITS, publishProblem, reelProblem, storyProblem } from "@/lib/socialApi";

/** Instagram's own three compose choices, in its own order. */
const KINDS = [
  { id: "post", ar: "منشور", en: "Post" },
  { id: "reel", ar: "ريل", en: "Reel" },
  { id: "story", ar: "ستوري", en: "Story" },
];

/**
 * Compose a post: 1 picture, or 2-10 as a carousel, plus a caption.
 * Nothing is uploaded until "Share". A failure keeps the pictures and the caption,
 * says why, and lets the person try again.
 */
export default function InstagramNewPostDialog({ lang = "ar", onPublish, onClose }) {
  const ar = lang === "ar";
  const [kind, setKind] = useState("post");
  const [files, setFiles] = useState([]);
  const [caption, setCaption] = useState("");
  const [shareToFeed, setShareToFeed] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const input = useRef(null);
  const previews = useMemo(() => files.map((f) => URL.createObjectURL(f)), [files]);
  useEffect(() => () => previews.forEach((u) => URL.revokeObjectURL(u)), [previews]);
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape" && !busy) onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  // Each kind has its own rules, and Instagram's own limits decide what can be sent.
  const problem = kind === "post"
    ? publishProblem(files, caption, lang)
    : kind === "reel"
      ? reelProblem(files[0], caption, lang)
      : storyProblem(files[0], lang);
  const oneOnly = kind !== "post";
  const accept = kind === "post" ? "image/jpeg" : kind === "reel" ? "video/mp4,video/quicktime" : "image/jpeg,video/mp4,video/quicktime";
  const pick = (next) => { setError(""); setKind(next); setFiles((prev) => (next === "post" ? prev : prev.slice(0, 1))); };
  const add = (list) => { setError(""); setFiles((prev) => [...prev, ...Array.from(list)].slice(0, oneOnly ? 1 : PUBLISH_LIMITS.maxPictures + 1)); };
  const move = (i, d) => setFiles((prev) => { const n = [...prev]; const j = i + d; if (j < 0 || j >= n.length) return prev; [n[i], n[j]] = [n[j], n[i]]; return n; });
  const drop = (i) => { setError(""); setFiles((prev) => prev.filter((_, k) => k !== i)); };

  const share = async () => {
    if (problem || busy) return;
    setBusy(true); setError("");
    try {
      await onPublish(files, caption, kind, { shareToFeed });
      onClose();
    } catch (e) {
      setError(e?.message || (ar ? "تعذّر النشر على إنستغرام. حاول مرة أخرى" : "Instagram could not publish this. Try again"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-3" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onClose(); }}>
      <div role="dialog" aria-modal="true" aria-label={ar ? "محتوى جديد" : "New content"} data-testid="ig-new-post" dir={ar ? "rtl" : "ltr"} className="flex max-h-[min(92vh,640px)] w-full max-w-[520px] flex-col overflow-hidden rounded-xl bg-white text-[#262626] shadow-2xl">
        <div className="flex h-12 shrink-0 items-center justify-between border-b border-[#dbdbdb] px-4">
          <button type="button" disabled={busy} onClick={onClose} aria-label={ar ? "إغلاق" : "Close"} className="grid h-8 w-8 place-items-center rounded-full hover:bg-[#efefef] disabled:opacity-40"><X className="h-5 w-5" /></button>
          <h2 className="text-[15px] font-semibold">{ar ? `جديد: ${KINDS.find((k) => k.id === kind)[ar ? "ar" : "en"]}` : `New ${KINDS.find((k) => k.id === kind).en.toLowerCase()}`}</h2>
          <button type="button" data-testid="ig-share" disabled={Boolean(problem) || busy} onClick={share} className="min-w-[56px] text-[14px] font-semibold text-[#0095f6] hover:text-[#00376b] disabled:cursor-not-allowed disabled:text-[#b2dffc]">
            {busy ? <Loader2 className="mx-auto h-4 w-4 animate-spin" /> : ar ? "مشاركة" : "Share"}
          </button>
        </div>

        <div role="tablist" aria-label={ar ? "نوع المحتوى" : "Content type"} className="flex shrink-0 justify-center gap-1 border-b border-[#dbdbdb] px-2 py-2">
          {KINDS.map((k) => (
            <button key={k.id} type="button" role="tab" aria-selected={kind === k.id} data-testid={`ig-kind-${k.id}`} disabled={busy} onClick={() => pick(k.id)} className={`rounded-full px-3 py-1 text-[13px] font-semibold ${kind === k.id ? "bg-[#efefef] text-[#262626]" : "text-[#737373] hover:bg-[#fafafa]"}`}>
              {ar ? k.ar : k.en}
            </button>
          ))}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {files.length > 0 && (
            <ul data-testid="ig-picture-list" className="mb-3 grid grid-cols-3 gap-2">
              {files.map((f, i) => (
                <li key={`${f.name}-${i}`} className="relative aspect-square overflow-hidden rounded-lg bg-[#efefef]">
                  <img src={previews[i]} alt={ar ? `الصورة ${i + 1}` : `Picture ${i + 1}`} className="h-full w-full object-cover" />
                  <span className="absolute start-1 top-1 rounded-full bg-black/60 px-1.5 text-[11px] text-white">{i + 1}</span>
                  <button type="button" disabled={busy} onClick={() => drop(i)} aria-label={ar ? `حذف الصورة ${i + 1}` : `Remove picture ${i + 1}`} className="absolute end-1 top-1 grid h-6 w-6 place-items-center rounded-full bg-black/60 text-white"><X className="h-3.5 w-3.5" /></button>
                  <div className="absolute inset-x-0 bottom-0 flex justify-between bg-gradient-to-t from-black/50 to-transparent p-1 text-white">
                    <button type="button" disabled={busy || i === 0} onClick={() => move(i, -1)} aria-label={ar ? "تقديم" : "Move earlier"} className="grid h-6 w-6 place-items-center disabled:opacity-30">{ar ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}</button>
                    <button type="button" disabled={busy || i === files.length - 1} onClick={() => move(i, 1)} aria-label={ar ? "تأخير" : "Move later"} className="grid h-6 w-6 place-items-center disabled:opacity-30">{ar ? <ChevronLeft className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}</button>
                  </div>
                </li>
              ))}
            </ul>
          )}

          <button type="button" disabled={busy || files.length >= (oneOnly ? 1 : PUBLISH_LIMITS.maxPictures)} onClick={() => input.current?.click()} className="flex h-24 w-full flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-[#dbdbdb] text-[13px] text-[#737373] hover:bg-[#fafafa] disabled:opacity-40">
            <ImagePlus className="h-6 w-6" />
            <span>{files.length ? (ar ? "تغيير الملف" : "Change the file") : kind === "reel" ? (ar ? "اختر فيديو MP4 أو MOV" : "Choose an MP4 or MOV video") : kind === "story" ? (ar ? "اختر صورة JPEG أو فيديو MP4" : "Choose a JPEG or an MP4 video") : (ar ? "اختر صورة JPEG أو أكثر (حتى 10)" : "Choose a JPEG, or up to 10")}</span>
          </button>
          <input ref={input} data-testid="ig-file-input" type="file" accept={accept} multiple={!oneOnly} hidden onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
          {files.length > 1 && <p className="mt-2 text-[12px] text-[#737373]">{ar ? "ستُنشر كألبوم بنفس الترتيب أعلاه" : "Shared as a carousel in the order above"}</p>}

          {kind === "reel" && (
            <label className="mt-3 flex items-center gap-2 text-[13px] text-[#262626]">
              <input type="checkbox" data-testid="ig-share-to-feed" checked={shareToFeed} disabled={busy} onChange={(e) => setShareToFeed(e.target.checked)} />
              <span>{ar ? "إظهار الريل في الملف الشخصي أيضًا" : "Also share the Reel to your profile"}</span>
            </label>
          )}

          {kind === "story" ? (
            <p className="mt-4 text-[12px] text-[#737373]">{ar ? "الستوري بدون نص: إنستغرام ملهاش حقل نص للستوري" : "A story has no caption: Instagram has no field for one"}</p>
          ) : (
          <label className="mt-4 block">
            <span className="sr-only">{ar ? "النص" : "Caption"}</span>
            <textarea data-testid="ig-caption" value={caption} disabled={busy} onChange={(e) => setCaption(e.target.value)} rows={4} placeholder={ar ? "اكتب نصًا للمنشور..." : "Write a caption..."} className="w-full resize-none rounded-lg bg-[#efefef] px-3 py-2 text-[14px] outline-none focus:ring-2 focus:ring-[#0095f6]/30" />
            <span className={`block text-[11px] ${caption.length > PUBLISH_LIMITS.maxCaption ? "text-[#ed4956]" : "text-[#8e8e8e]"}`} dir="ltr">{caption.length} / {PUBLISH_LIMITS.maxCaption}</span>
          </label>
          )}

          {(error || (files.length > 0 && problem)) && <p role="alert" data-testid="ig-publish-error" className="mt-3 rounded-lg bg-[#fde8ec] px-3 py-2 text-[12.5px] text-[#7a1226]">{error || problem}</p>}
        </div>
      </div>
    </div>
  );
}
