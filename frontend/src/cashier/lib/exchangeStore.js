// حالة شاشة الاستبدال: عمليات معلقة (محفوظة محليًا لاستكمالها لاحقًا) + العمليات المعتمدة في الجلسة.
import { useSyncExternalStore } from "react";
import { exchangeRecords } from "@/cashier/lib/opsData";

const STORAGE_KEY = "boutique-held-exchanges";

function readHeld() {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveHeld(list) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
  } catch {
    /* تجاهل: تظل العملية معلقة في الذاكرة */
  }
}

let state = {
  held: readHeld(),
  completed: [], // عمليات أُتمّت في هذه الجلسة (الأحدث أولاً)
  lastOperation: null, // آخر عملية معتمدة لطباعة الإيصال
  seq: exchangeRecords.length + 1,
};

const listeners = new Set();

function emit() {
  listeners.forEach((l) => l());
}

function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot() {
  return state;
}

export function useExchangeState() {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

// رقم العملية التالي (EXC-2026-00xx).
export function nextExchangeNumber() {
  return `EXC-2026-${String(state.seq).padStart(4, "0")}`;
}

// سجل الاستبدال الكامل: عمليات الجلسة أولاً ثم السجل التجريبي.
export function allExchangeRecords() {
  return [...state.completed, ...exchangeRecords];
}

// الكميات التي سبق استبدالها لنفس الفاتورة في عمليات استبدال معتمدة
// (مفتاح: اسم المنتج|اللون|المقاس) — لخصمها من المتاح للاستبدال.
export function priorExchangedQuantities(invoiceId) {
  const map = {};
  if (!invoiceId) return map;
  allExchangeRecords().forEach((record) => {
    if (record.invoiceId !== invoiceId || record.status !== "completed" || !Array.isArray(record.returns)) return;
    record.returns.forEach((line) => {
      const key = `${line.name}|${line.color}|${line.size}`;
      map[key] = (map[key] || 0) + line.qty;
    });
  });
  return map;
}

export function holdExchange(record) {
  const held = [record, ...state.held];
  state = { ...state, held };
  saveHeld(held);
  emit();
}

// سحب عملية معلقة لاستكمالها (تُزال من قائمة المعلقات).
export function takeHeld(id) {
  const found = state.held.find((h) => h.id === id) ?? null;
  const held = state.held.filter((h) => h.id !== id);
  state = { ...state, held };
  saveHeld(held);
  emit();
  return found;
}

export function removeHeld(id) {
  const held = state.held.filter((h) => h.id !== id);
  state = { ...state, held };
  saveHeld(held);
  emit();
}

export function completeExchange(record) {
  state = { ...state, completed: [record, ...state.completed], lastOperation: record, seq: state.seq + 1 };
  emit();
}

// حركة المخزون (مشتركة بين المرتجعات والاستبدال).
export { applyStockMovement } from "@/cashier/lib/stockMovement";