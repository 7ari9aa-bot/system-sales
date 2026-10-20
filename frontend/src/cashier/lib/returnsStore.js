// حالة سجل المرتجعات: العمليات المعتمدة في هذه الجلسة تظهر فوق السجل التجريبي.
import { useSyncExternalStore } from "react";
import { returnRecords } from "@/cashier/lib/opsData";

function nextSeq(records) {
  const max = records.reduce((m, r) => Math.max(m, Number(String(r.number).split("-").pop()) || 0), 0);
  return max + 1;
}

let state = {
  records: [], // عمليات أُعتمدت في هذه الجلسة (الأحدث أولاً)
  seq: nextSeq(returnRecords),
};

const listeners = new Set();

function emit() {
  listeners.forEach((listener) => listener());
}

function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot() {
  return state;
}

export function useReturnState() {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

// رقم المرتجع التالي (RET-2026-00xx).
export function nextReturnNumber() {
  return `RET-2026-${String(state.seq).padStart(4, "0")}`;
}

// السجل الكامل: عمليات الجلسة أولاً ثم السجل التجريبي.
export function allReturnRecords() {
  return [...state.records, ...returnRecords];
}

export function completeReturn(record) {
  state = { ...state, records: [record, ...state.records], seq: state.seq + 1 };
  emit();
}