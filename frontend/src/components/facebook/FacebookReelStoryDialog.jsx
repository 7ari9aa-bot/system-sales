import React, { useEffect, useMemo, useRef, useState } from "react";
import { FB } from "@/components/facebook/fbTheme";
import { FbClock, FbPhoto } from "@/components/facebook/fbIcons";
import {
  FB_STORY_PHOTO_TYPES,
  FB_VIDEO,
  facebookPublishFailure,
  facebookReelStoryProblem,
  readVideoInfo,
} from "@/lib/facebookApi";

const pad = (n) => String(n).padStart(2, "0");
const local = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;

/**
 * "Create reel" (kind "reel") and "Create story" (kind "story"). The file is checked here against
 * Meta's rules before anything is uploaded; the server checks it again from the file's own bytes.
 * Nothing is reported as posted until Facebook accepted it.
 */
export default function FacebookReelStoryDialog({ kind = "reel", lang = "ar", onPublishReel, onPublishStory, onClose }) {
  const ar = lang === "ar";
  const isReel = kind === "reel";
  const title = isReel ? (ar ? "إنشاء ريل" : "Create reel") : (ar ? "إنشاء ستوري" : "Create story");
  const [file, setFile] = useState(null);
  const [info, setInfo] = useState(null);
  const [reading, setReading] = useState(false);
  const [readError, setReadError] = useState("");
  const [description, setDescription] = useState("");
  const [schedule, setSchedule] = useState(false);
  const [scheduleAt, setScheduleAt] = useState(local(new Date(Date.now() + 60 * 60000)));
  const [ai, setAi] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  const picker = useRef(null);
  const abort = useRef(null);
  const sending = useRef(false);

  const isPhoto = !!file && file.type.startsWith("image/");
  const preview = useMemo(() => (file ? URL.createObjectURL(file) : ""), [file]);
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);
  useEffect(() => () => abort.current?.abort(), []);

  const pick = async (picked) => {
    setFile(picked);
    setInfo(null);
    setReadError("");
    setError("");
    if (!picked || picked.type.startsWith("image/")) return;
    setReading(true);
    try {
      const read = await readVideoInfo(picked);
      setInfo(read);
    } catch {
      setReadError(ar ? "تعذّرت قراءة الفيديو. جرّب ملف mp4 آخر." : "The video could not be read. Try another mp4.");
    } finally {
      setReading(false);
    }
  };

  const problem = facebookReelStoryProblem({ kind, file, info, reading, readError, scheduleOn: schedule, scheduleAt }, lang);
  const ready = !!file && !reading && !problem;

  const submit = async (event) => {
    event.preventDefault();
    if (!ready || busy || sending.current) return;
    sending.current = true; // a second tap must not post it twice
    setBusy(true);
    setError("");
    abort.current = new AbortController();
    try {
      if (isReel) {
        const out = await onPublishReel({ file, description, scheduleAt: schedule ? scheduleAt : "", aiGenerated: ai, signal: abort.current.signal });
        setDone(out?.scheduled ? (ar ? "تمت جدولة الريل" : "Reel scheduled") : (ar ? "تم نشر الريل" : "Reel published"));
      } else {
        await onPublishStory({ file, signal: abort.current.signal });
        setDone(ar ? "تم نشر الستوري" : "Story published");
      }
      window.setTimeout(onClose, 1200);
    } catch (e) {
      if (e?.name === "AbortError") return;
      setError(facebookPublishFailure(e, lang));
      sending.current = false;
      setBusy(false);
    }
  };

  const accept = isReel ? "video/mp4" : ["video/mp4", ...FB_STORY_PHOTO_TYPES].join(",");
  const rules = isReel
    ? (ar ? "mp4 طولي 9:16، لا يقل عن 540×960، من 3 إلى 90 ثانية" : "Tall 9:16 mp4, at least 540x960, 3 to 90 seconds")
    : (ar ? `فيديو mp4 طولي حتى ${FB_VIDEO.storyMaxSeconds} ثانية، أو صورة حتى 10 ميغابايت` : `Tall mp4 up to ${FB_VIDEO.storyMaxSeconds} seconds, or a picture up to 10 MB`);

  return (
    <div role="dialog" aria-modal="true" aria-label={title} dir={ar ? "rtl" : "ltr"} className="fixed inset-0 z-50 grid place-items-center bg-white/80 p-3 backdrop-blur-[2px]" onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onClose(); }}>
      <form onSubmit={submit} className="max-h-[94vh] w-full max-w-[500px] overflow-y-auto rounded-xl bg-white shadow-[0_12px_28px_rgba(0,0,0,0.2),0_2px_4px_rgba(0,0,0,0.1)]" style={{ fontFamily: FB.font, color: FB.text }}>
        <div className="relative border-b px-4 py-4 text-center" style={{ borderColor: FB.divider }}>
          <h2 className="text-[20px] font-bold">{title}</h2>
          <button type="button" onClick={onClose} disabled={busy} aria-label={ar ? "إغلاق" : "Close"} className="absolute end-4 top-3 grid h-9 w-9 place-items-center rounded-full bg-[#e4e6eb] text-[20px] leading-none text-[#65676b] hover:bg-[#d8dadf] disabled:opacity-50">×</button>
        </div>
        <div className="px-4 pt-3">
          {file ? (
            <div className="relative mb-3 overflow-hidden rounded-lg border" style={{ borderColor: FB.border, background: "#000" }}>
              {isPhoto
                ? <img src={preview} alt={ar ? "الصورة المرفقة" : "Attached picture"} className="mx-auto max-h-[320px] object-contain" />
                : <video src={preview} controls muted playsInline data-testid="fb-video-preview" className="mx-auto max-h-[320px]" />}
              <button type="button" onClick={() => pick(null)} disabled={busy} aria-label={ar ? "إزالة الملف" : "Remove file"} className="absolute end-2 top-2 grid h-8 w-8 place-items-center rounded-full bg-white text-[18px] leading-none text-[#65676b] shadow hover:bg-[#f2f2f2] disabled:opacity-50">×</button>
            </div>
          ) : (
            <button type="button" onClick={() => picker.current?.click()} className="mb-3 flex h-[160px] w-full flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed text-[15px] font-semibold hover:bg-[#f2f2f2]" style={{ borderColor: FB.border, color: FB.text2 }}>
              <FbPhoto size={32} />
              {isReel ? (ar ? "اختر فيديو" : "Choose a video") : (ar ? "اختر فيديو أو صورة" : "Choose a video or picture")}
              <span className="px-4 text-center text-[12px] font-normal">{rules}</span>
            </button>
          )}
          <input ref={picker} data-testid="fb-reel-input" type="file" accept={accept} hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) pick(f); e.target.value = ""; }} />
          {reading && <p role="status" className="mb-2 text-[13px]" style={{ color: FB.text2 }}>{ar ? "جارٍ قراءة الفيديو..." : "Reading the video..."}</p>}
          {info && !problem && <p className="mb-2 text-[12px]" style={{ color: FB.text2 }}>{info.width} × {info.height} · {Math.round(info.seconds)} {ar ? "ث" : "s"}</p>}
          {isReel && (
            <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3} dir="auto" disabled={busy} aria-label={ar ? "وصف الريل" : "Reel description"} placeholder={ar ? "اكتب وصفًا (يدعم الوسوم)" : "Write a description (hashtags work)"} className="mb-2 w-full resize-none rounded-lg border px-3 py-2 text-[15px] outline-none focus:border-[#0866ff]" style={{ borderColor: FB.border, background: FB.bg }} />
          )}
          {isReel && schedule && (
            <label className="mb-2 flex items-center gap-2 text-[14px]" style={{ color: FB.text2 }}>
              <FbClock size={18} />
              <input type="datetime-local" value={scheduleAt} min={local(new Date(Date.now() + FB_VIDEO.scheduleMinMinutes * 60000))} max={local(new Date(Date.now() + FB_VIDEO.scheduleMaxDays * 86400000))} onChange={(e) => setScheduleAt(e.target.value)} aria-label={ar ? "موعد النشر" : "Publish time"} className="rounded-lg border px-2 py-1.5 text-[14px] outline-none focus:border-[#0866ff]" style={{ borderColor: FB.border, color: FB.text }} />
            </label>
          )}
          {isReel && (
            <div className="mb-3 flex flex-wrap items-center gap-1">
              <button type="button" aria-pressed={schedule} onClick={() => setSchedule((v) => !v)} disabled={busy} className={`rounded-full px-3 py-1.5 text-[13px] font-semibold ${schedule ? "bg-[#e7f3ff] text-[#0866ff]" : "text-[#65676b] hover:bg-[#f2f2f2]"}`}>{ar ? "جدولة" : "Schedule"}</button>
              <button type="button" aria-pressed={ai} onClick={() => setAi((v) => !v)} disabled={busy} title={ar ? "أخبر فيسبوك أن الفيديو أُنشئ أو عُدّل بالذكاء الاصطناعي" : "Tell Facebook the video was made or edited with AI"} className={`rounded-full px-3 py-1.5 text-[13px] font-semibold ${ai ? "bg-[#e7f3ff] text-[#0866ff]" : "text-[#65676b] hover:bg-[#f2f2f2]"}`}>{ar ? "مُنشأ بالذكاء الاصطناعي" : "Made with AI"}</button>
            </div>
          )}
        </div>
        <div className="px-4 pb-4">
          {(error || (file && !reading && problem)) && <p role="alert" className="mb-2 text-[13px]" style={{ color: FB.red }}>{error || problem}</p>}
          {busy && !error && <p role="status" className="mb-2 text-[13px]" style={{ color: FB.text2 }}>{ar ? "جارٍ الرفع. قد يستغرق بضع دقائق، لا تغلق النافذة." : "Uploading. This can take a few minutes; keep this window open."}</p>}
          {done && <p role="status" className="mb-2 text-[13px]" style={{ color: FB.green }}>{done}</p>}
          <button type="submit" disabled={!ready || busy || !!done} className="h-9 w-full rounded-md text-[15px] font-semibold text-white transition-colors disabled:cursor-not-allowed disabled:bg-[#e4e6eb] disabled:text-[#bcc0c4]" style={{ background: FB.blue }}>
            {busy ? (ar ? "جارٍ النشر..." : "Posting...") : isReel && schedule ? (ar ? "جدولة" : "Schedule") : (ar ? "نشر" : "Post")}
          </button>
        </div>
      </form>
    </div>
  );
}
