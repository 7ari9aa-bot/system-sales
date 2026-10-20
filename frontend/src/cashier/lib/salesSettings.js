// إعدادات البيع المشتركة بين شاشة الكاشير وصفحة الإعدادات:
// طرق الدفع المفعّلة، الطريقة الافتراضية، وحد الخصم المسموح للكاشير.

import { useSyncExternalStore } from "react";
import { PAYMENT_METHODS } from "@/cashier/lib/format";

export const ALL_PAYMENT_METHODS = Object.keys(PAYMENT_METHODS);

const listeners = new Set();

let state = {
  enabledMethods: ALL_PAYMENT_METHODS,
  defaultMethod: "cash",
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