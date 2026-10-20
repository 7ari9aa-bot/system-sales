// إعدادات البيع المشتركة بين شاشة الكاشير وصفحة الإعدادات:
// حد الخصم المسموح للكاشير.

import { useSyncExternalStore } from "react";
const listeners = new Set();

let state = {
  maxDiscountPct: 20,
};

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

export function useSalesSettings() {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

export function updateSalesSettings(patch) {
  state = { ...state, ...patch };
  emit();
}