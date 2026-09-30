import React, { useEffect, useState } from "react";
import { ShieldCheck, ShieldAlert, ChevronDown, Trash2, X } from "lucide-react";
import { guardianEvents, guardianSubscribe, guardianClear } from "@/lib/guardian";
import { apiCached, peekCache, getTokens } from "@/lib/api";

/** شارة الحارس العائمة — موجودة دايمًا كنقطة خضراء (كل حاجة سليمة)،
 *  وبتحمرّ وتفتح تفاصيل أول ما يتصطاد فشل صامت. صحة الـbackend
 *  بتنقرأ من /platform/health (كاش 60 ثانية). الشارة مش بتقطع
 *  ولا تحجب أي محتوى — مراقب بس. */

const HEALTH_PATH = "/platform/health";

export default function Guardian() {
  const [events, setEvents] = useState(() => guardianEvents());
  const [open, setOpen] = useState(false);
  const [health, setHealth] = useState(() => peekCache(HEALTH_PATH) ?? null);

  useEffect(() => guardianSubscribe(setEvents), []);

  useEffect(() => {
    // فحص الصحة بس مع جلسة قائمة — الزوار على الصفحات العامة مش هدفه
    if (!getTokens()) {
      setHealth(null);
      return;
    }
    let alive = true;
    apiCached(HEALTH_PATH, { ttlMs: 60_000 })
      .then((d) => alive && setHealth(d))
      .catch(() => alive && setHealth({ status: "unreachable" }));
    return () => {
      alive = false;
    };
  }, [events.length]);

  const failures = events.length;
  const backendHealthy = health?.status === "healthy";
  const backendKnown = health != null;
  const allClear = failures === 0 && (!backendKnown || backendHealthy);

  const bg = allClear ? "rgba(16,185,129,.12)" : "rgba(239,68,68,.14)";
  const fg = allClear ? "#10B981" : "#EF4444";

  return (
    <div
      style={{
        position: "fixed",
        bottom: 16,
        insetInlineEnd: 16,
        zIndex: 90,
        direction: "rtl",
        fontFamily: "inherit",
      }}
    >
      {open && (
        <div
          style={{
            position: "absolute",
            bottom: 46,
            insetInlineEnd: 0,
            width: 340,
            maxHeight: 380,
            overflowY: "auto",
            background: "#0E1012",
            border: "1px solid #232629",
            borderRadius: 14,
            boxShadow: "0 18px 50px rgba(0,0,0,.45)",
            padding: 12,
            color: "#EDEDED",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
            <strong style={{ fontSize: 13 }}>الحارس — سجل الأخطاء</strong>
            <span style={{ display: "flex", gap: 6 }}>
              <button
                onClick={guardianClear}
                title="تفريغ السجل"
                style={iconBtn}
              >
                <Trash2 size={14} />
              </button>
              <button onClick={() => setOpen(false)} title="إغلاق" style={iconBtn}>
                <X size={14} />
              </button>
            </span>
          </div>

          <div style={{ fontSize: 12, color: "#9CA3AF", marginBottom: 10, display: "flex", gap: 14 }}>
            <span>
              الباك إند:{" "}
              <b style={{ color: backendHealthy ? "#10B981" : backendKnown ? "#EF4444" : "#9CA3AF" }}>
                {backendHealthy ? "سليم" : backendKnown ? "لا يستجيب" : "…"}
              </b>
            </span>
            <span>
              إجمالي الوقعات: <b style={{ color: failures ? "#F59E0B" : "#10B981" }}>{failures}</b>
            </span>
          </div>

          {failures === 0 ? (
            <p style={{ fontSize: 12.5, color: "#6B7280", margin: "6px 0" }}>
              مفيش أي فشل صامت متصطاد — كل النداءات رجعت ووصلت.
            </p>
          ) : (
            <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 8 }}>
              {[...events].reverse().map((e) => (
                <li
                  key={e.id}
                  style={{
                    background: "rgba(239,68,68,.06)",
                    border: "1px solid rgba(239,68,68,.18)",
                    borderRadius: 10,
                    padding: "8px 10px",
                  }}
                >
                  <div style={{ fontSize: 11.5, color: "#9CA3AF", display: "flex", justifyContent: "space-between" }}>
                    <span style={{ direction: "ltr", textAlign: "left" }}>
                      {e.kind} · {e.source}
                    </span>
                    <span title={e.at.toLocaleString()}>
                      {e.count > 1 ? `×${e.count} ` : ""}
                      {e.at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                    </span>
                  </div>
                  <div style={{ fontSize: 12, marginTop: 4, wordBreak: "break-word", direction: "ltr", textAlign: "left" }}>
                    {e.message}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <button
        onClick={() => setOpen((v) => !v)}
        title="نظام الحارس — مراقبة الأخطاء الصامتة"
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 7,
          height: 34,
          padding: "0 12px",
          borderRadius: 999,
          border: "1px solid rgba(255,255,255,.08)",
          background: bg,
          color: fg,
          fontSize: 12,
          fontWeight: 700,
          cursor: "pointer",
          backdropFilter: "blur(8px)",
          boxShadow: "0 6px 18px rgba(0,0,0,.25)",
        }}
      >
        {allClear ? <ShieldCheck size={15} /> : <ShieldAlert size={15} />}
        <span>{allClear ? "الحارس" : `الحارس · ${failures}`}</span>
        <ChevronDown
          size={13}
          style={{ transform: open ? "rotate(180deg)" : "none", transition: "transform .2s" }}
        />
      </button>
    </div>
  );
}

const iconBtn = {
  width: 26,
  height: 26,
  display: "grid",
  placeItems: "center",
  borderRadius: 8,
  border: "1px solid #232629",
  background: "transparent",
  color: "#9CA3AF",
  cursor: "pointer",
};
