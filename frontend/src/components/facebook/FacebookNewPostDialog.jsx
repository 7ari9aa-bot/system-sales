import React, { useEffect, useMemo, useRef, useState } from "react";
import { FB } from "@/components/facebook/fbTheme";
import { FbClock, FbGlobe, FbPhoto } from "@/components/facebook/fbIcons";
import { FB_LIMITS, FB_PICTURE_TYPES, addPictures, facebookPostProblem } from "@/lib/facebookApi";

const pad = (n) => String(n).padStart(2, "0");
const local = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;

/** Facebook's "Create post" box: text, optional pictures (an album) or a link (not both), and an optional schedule. Nothing is sent until Meta accepts it. */
export default function FacebookNewPostDialog({ lang = "ar", onPublish, onClose }) {
  const ar = lang === "ar";
  const [message, setMessage] = useState("");
  const [link, setLink] = useState("");
  const [showLink, setShowLink] = useState(false);
  const [pictures, setPictures] = useState([]);
  const picker = useRef(null);
  const previews = useMemo(() => pictures.map((f) => URL.createObjectURL(f)), [pictures]);
  useEffect(() => () => { previews.forEach((u) => URL.revokeObjectURL(u)); }, [previews]);
  const [schedule, setSchedule] = useState(false);
  const [scheduleAt, setScheduleAt] = useState(local(new Date(Date.now() + 60 * 60000)));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  const input = { message, link: showLink && !pictures.length ? link : "", pictures, scheduleAt: schedule ? scheduleAt : "" };
  const problem = facebookPostProblem(input, lang);

  const submit = async (event) => {
    event.preventDefault();
    if (problem || busy) return;
    setBusy(true);
    setError("");
    try {
      const out = await onPublish(input);
      setDone(out?.scheduled ? (ar ? "تمت جدولة المنشور" : "Post scheduled") : (ar ? "تم نشر المنشور" : "Post published"));
      window.setTimeout(onClose, 900);
    } catch (e) {
      setError(e?.message || (ar ? "تعذّر النشر" : "Could not publish"));
      setBusy(false);
    }
  };

  return (
    <div role="dialog" aria-modal="true" aria-label={ar ? "إنشاء منشور" : "Create post"} dir={ar ? "rtl" : "ltr"} className="fixed inset-0 z-50 grid place-items-center bg-white/80 p-3 backdrop-blur-[2px]" onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onClose(); }}>
      <form onSubmit={submit} className="w-full max-w-[500px] rounded-xl bg-white shadow-[0_12px_28px_rgba(0,0,0,0.2),0_2px_4px_rgba(0,0,0,0.1)]" style={{ fontFamily: FB.font, color: FB.text }}>
        <div className="relative border-b px-4 py-4 text-center" style={{ borderColor: FB.divider }}>
          <h2 className="text-[20px] font-bold">{ar ? "إنشاء منشور" : "Create post"}</h2>
          <button type="button" onClick={onClose} disabled={busy} aria-label={ar ? "إغلاق" : "Close"} className="absolute end-4 top-3 grid h-9 w-9 place-items-center rounded-full bg-[#e4e6eb] text-[20px] leading-none text-[#65676b] hover:bg-[#d8dadf] disabled:opacity-50">×</button>
        </div>
        <div className="px-4 pt-3">
          <p className="mb-2 flex items-center gap-1 text-[13px]" style={{ color: FB.text2 }}><FbGlobe size={13} />{ar ? "عام" : "Public"}</p>
          <textarea autoFocus value={message} onChange={(e) => setMessage(e.target.value)} maxLength={FB_LIMITS.maxPostChars} rows={5} dir="auto" placeholder={ar ? "بماذا تفكر؟" : "What's on your mind?"} className="w-full resize-none border-0 bg-transparent text-[18px] leading-snug outline-none placeholder:text-[#65676b]" />
          {pictures.length > 0 && (
            <div data-testid="fb-album" className={`mb-2 grid gap-1 overflow-hidden rounded-lg border ${pictures.length === 1 ? "grid-cols-1" : "grid-cols-2"}`} style={{ borderColor: FB.border }}>
              {pictures.map((file, i) => (
                <div key={`${file.name}-${file.size}-${i}`} className="relative" style={{ background: FB.bg }}>
                  <img src={previews[i]} alt={ar ? `الصورة ${i + 1}` : `Picture ${i + 1}`} className={`w-full object-cover ${pictures.length === 1 ? "max-h-[260px] object-contain" : "h-[130px]"}`} />
                  <button type="button" onClick={() => setPictures((list) => list.filter((_, k) => k !== i))} disabled={busy} aria-label={ar ? `إزالة الصورة ${i + 1}` : `Remove picture ${i + 1}`} className="absolute end-2 top-2 grid h-8 w-8 place-items-center rounded-full bg-white text-[18px] leading-none shadow-[0_1px_3px_rgba(0,0,0,0.3)] hover:bg-[#f2f2f2]">×</button>
                </div>
              ))}
            </div>
          )}
          {showLink && !pictures.length && (
            <input value={link} onChange={(e) => setLink(e.target.value)} dir="ltr" inputMode="url" placeholder="https://" aria-label={ar ? "الرابط" : "Link"} className="mb-2 w-full rounded-lg border px-3 py-2 text-[15px] outline-none focus:border-[#0866ff]" style={{ borderColor: FB.border, background: FB.bg }} />
          )}
          {schedule && (
            <label className="mb-2 flex items-center gap-2 text-[14px]" style={{ color: FB.text2 }}>
              <FbClock size={18} />
              <input type="datetime-local" value={scheduleAt} min={local(new Date(Date.now() + FB_LIMITS.scheduleMinMinutes * 60000))} max={local(new Date(Date.now() + FB_LIMITS.scheduleMaxDays * 86400000))} onChange={(e) => setScheduleAt(e.target.value)} aria-label={ar ? "موعد النشر" : "Publish time"} className="rounded-lg border px-2 py-1.5 text-[14px] outline-none focus:border-[#0866ff]" style={{ borderColor: FB.border, color: FB.text }} />
            </label>
          )}
        </div>
        <div className="mx-4 mb-3 flex items-center justify-between rounded-lg border px-3 py-2" style={{ borderColor: FB.border }}>
          <span className="text-[15px] font-semibold">{ar ? "إضافة إلى منشورك" : "Add to your post"}</span>
          <span className="flex gap-1">
            <button type="button" onClick={() => picker.current?.click()} disabled={busy} aria-label={ar ? "صورة" : "Photo"} title={ar ? "صورة" : "Photo"} className={`grid h-8 w-8 place-items-center rounded-full ${pictures.length ? "bg-[#e7f3ff] text-[#0866ff]" : "text-[#45bd62] hover:bg-[#f2f2f2]"} disabled:opacity-50`}><FbPhoto size={20} /></button>
            <input ref={picker} data-testid="fb-picture-input" type="file" multiple accept={FB_PICTURE_TYPES.join(",")} hidden onChange={(e) => { const next = addPictures(pictures, e.target.files); if (e.target.files?.length) { setPictures([...next]); setShowLink(false); setError(next.left ? (ar ? `أُضيفت ${FB_LIMITS.maxPictures} صور فقط، وهذا الحد الأقصى` : `Only ${FB_LIMITS.maxPictures} pictures fit in one post`) : ""); } e.target.value = ""; }} />
            <button type="button" aria-pressed={showLink} onClick={() => { setShowLink((v) => !v); setPictures([]); }} className={`rounded-full px-3 py-1.5 text-[13px] font-semibold ${showLink ? "bg-[#e7f3ff] text-[#0866ff]" : "text-[#65676b] hover:bg-[#f2f2f2]"}`}>{ar ? "رابط" : "Link"}</button>
            <button type="button" aria-pressed={schedule} onClick={() => setSchedule((v) => !v)} className={`rounded-full px-3 py-1.5 text-[13px] font-semibold ${schedule ? "bg-[#e7f3ff] text-[#0866ff]" : "text-[#65676b] hover:bg-[#f2f2f2]"}`}>{ar ? "جدولة" : "Schedule"}</button>
          </span>
        </div>
        <div className="px-4 pb-4">
          {(error || (problem && (message || link || pictures.length))) && <p role="alert" className="mb-2 text-[13px]" style={{ color: FB.red }}>{error || problem}</p>}
          {done && <p role="status" className="mb-2 text-[13px]" style={{ color: FB.green }}>{done}</p>}
          <button type="submit" disabled={!!problem || busy || !!done} className="h-9 w-full rounded-md text-[15px] font-semibold text-white transition-colors disabled:cursor-not-allowed disabled:bg-[#e4e6eb] disabled:text-[#bcc0c4]" style={{ background: FB.blue }}>
            {busy ? (ar ? "جارٍ النشر..." : "Posting...") : schedule ? (ar ? "جدولة" : "Schedule") : (ar ? "نشر" : "Post")}
          </button>
        </div>
      </form>
    </div>
  );
}
