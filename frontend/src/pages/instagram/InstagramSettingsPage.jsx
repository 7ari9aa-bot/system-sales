import React, { useEffect, useState } from "react";
import { IG } from "@/components/instagram/igTheme";
import { fetchIceBreakers, saveIceBreakers } from "@/lib/socialApi";
import { useInstagramData } from "./useInstagramData";

const MAX = 4;

/** /instagram/settings — the questions a customer can tap to start a chat (Instagram "Ice Breakers"). */
export default function InstagramSettingsPage() {
  const { lang, demoAccount } = useInstagramData();
  const ar = lang === "ar";
  const [saved, setSaved] = useState([]);
  const [items, setItems] = useState([]);
  const [state, setState] = useState({ loading: !demoAccount, error: "", saving: false, done: false });

  useEffect(() => {
    if (demoAccount) return undefined;
    let cancelled = false;
    fetchIceBreakers()
      .then((q) => { if (!cancelled) { setSaved(q); setItems(q); setState((s) => ({ ...s, loading: false })); } })
      .catch((e) => { if (!cancelled) setState((s) => ({ ...s, loading: false, error: e?.message || "error" })); });
    return () => { cancelled = true; };
  }, [demoAccount]);

  const cleaned = items.map((t) => t.trim()).filter(Boolean);
  const repeated = new Set(cleaned).size !== cleaned.length;
  const unchanged = cleaned.join("\n") === saved.join("\n");

  async function save() {
    setState((s) => ({ ...s, saving: true, error: "", done: false }));
    try {
      const now = await saveIceBreakers(cleaned);
      setSaved(now); setItems(now);
      setState((s) => ({ ...s, saving: false, done: true }));
    } catch (e) {
      setState((s) => ({ ...s, saving: false, error: e?.message || "error" }));
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[560px] px-6 py-8">
        <h1 className="text-[24px] font-bold">{ar ? "الإعدادات" : "Settings"}</h1>
        <h2 className="mt-6 text-[16px] font-semibold">{ar ? "أسئلة البداية" : "Ice breakers"}</h2>
        <p className="mt-1 text-[14px] leading-[18px]" style={{ color: IG.secondary }}>
          {ar ? "أسئلة شائعة يضغط عليها العميل ليبدأ المحادثة. حتى 4 أسئلة، وتظهر في تطبيق إنستغرام على الموبايل فقط، وليس على الكمبيوتر."
            : "Common questions a customer can tap to start a chat. Up to 4. They show in Instagram's mobile app, not on desktop."}
        </p>
        {demoAccount ? (
          <p data-testid="ig-ice-demo" className="mt-4 rounded-xl bg-[#f3f5f7] px-4 py-3 text-[14px]">{ar ? "اربط حساب إنستغرام حقيقيًا لتعديل أسئلة البداية." : "Connect a real Instagram account to edit ice breakers."}</p>
        ) : state.loading ? (
          <p role="status" className="mt-4 text-[14px]" style={{ color: IG.secondary }}>{ar ? "جارٍ التحميل..." : "Loading..."}</p>
        ) : (
          <>
            <ul className="mt-4 flex flex-col gap-2">
              {items.map((q, i) => (
                <li key={i} className="flex items-center gap-2">
                  <input value={q} onChange={(e) => setItems(items.map((t, n) => (n === i ? e.target.value : t)))} dir="auto" data-testid="ig-ice-input"
                    aria-label={`${ar ? "سؤال" : "Question"} ${i + 1}`} placeholder={ar ? "اكتب سؤالًا" : "Write a question"}
                    className="h-10 min-w-0 flex-1 rounded-full bg-[#f3f5f7] px-4 text-[14px] outline-none placeholder:text-[#6a717a]" />
                  <button type="button" onClick={() => setItems(items.filter((_, n) => n !== i))} aria-label={ar ? "حذف السؤال" : "Remove question"} className="shrink-0 rounded-full px-2 text-[18px] leading-none text-[#6a717a] hover:bg-[#f3f5f7]">×</button>
                </li>
              ))}
            </ul>
            {items.length < MAX && (
              <button type="button" data-testid="ig-ice-add" onClick={() => setItems([...items, ""])} className="mt-3 text-[14px] font-semibold text-[#0095f6] hover:text-[#00376b]">{ar ? "إضافة سؤال" : "Add a question"}</button>
            )}
            {repeated && <p role="alert" className="mt-2 text-[12px]" style={{ color: IG.error }}>{ar ? "الأسئلة لازم تكون مختلفة عن بعضها." : "Questions must differ from each other."}</p>}
            {state.error && <p role="alert" data-testid="ig-ice-error" className="mt-2 text-[14px]" style={{ color: IG.error }}>{state.error}</p>}
            {state.done && !state.error && <p role="status" data-testid="ig-ice-done" className="mt-2 text-[14px]" style={{ color: IG.secondary }}>{ar ? "تم الحفظ." : "Saved."}</p>}
            <button type="button" data-testid="ig-ice-save" onClick={save} disabled={state.saving || repeated || unchanged}
              className="mt-4 h-9 rounded-lg bg-[#4a5df9] px-5 text-[14px] font-semibold text-white hover:bg-[#3a4de0] disabled:opacity-40">{state.saving ? (ar ? "جارٍ الحفظ..." : "Saving...") : (ar ? "حفظ" : "Save")}</button>
          </>
        )}
      </div>
    </div>
  );
}
