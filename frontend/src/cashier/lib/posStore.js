// حالة الكاشير التي تعيش عبر التنقل بين الشاشات (فواتير معلقة + آخر فاتورة للمعاينة).
// لا يوجد اتصال ببيانات حقيقية: الحالة في الذاكرة فقط خلال جلسة العرض.

import { useSyncExternalStore } from "react";
import { initialSuspended } from "@/cashier/lib/mockData";

let state = {
  suspended: initialSuspended,
  lastReceipt: null,
  exchangeSeed: null,
  returnSeed: null,
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

export function usePosState() {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

export function suspendInvoice(invoice) {
  state = { ...state, suspended: [invoice, ...state.suspended] };
  emit();
}

export function resumeSuspended(id) {
  const found = state.suspended.find((s) => s.id === id);
  if (!found) return null;
  state = { ...state, suspended: state.suspended.filter((s) => s.id !== id) };
  emit();
  return found;
}

export function removeSuspended(id) {
  state = { ...state, suspended: state.suspended.filter((s) => s.id !== id) };
  emit();
}

export function setLastReceipt(receipt) {
  state = { ...state, lastReceipt: receipt };
  emit();
}

// تمرير فاتورة أو صنف مختار إلى شاشة المرتجعات / الاستبدال.
export function setReturnSeed(seed) {
  state = { ...state, returnSeed: seed };
  emit();
}

export function peekReturnSeed() {
  const seed = state.returnSeed;
  state = { ...state, returnSeed: null };
  return seed;
}