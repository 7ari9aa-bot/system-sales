import { useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { posApi } from "./posApi";
import { createIntentStore } from "./intentStore";
import { CATALOG_KEY } from "./usePosSale";
import { SHIFTS_KEY, SHIFT_STATE_KEY } from "./useShifts";
import { orderFromApi, returnFromApi, supplierFromApi } from "./purchasingAdapter";

export const SUPPLIERS_KEY = ["cashier", "suppliers"];
export const ORDERS_KEY = ["cashier", "purchase-orders"];
export const RETURNS_KEY = ["cashier", "supplier-returns"];
export const PAYMENTS_KEY = ["cashier", "supplier-payments"];

export function useSuppliers() {
  return useQuery({
    queryKey: SUPPLIERS_KEY,
    queryFn: async () => ((await posApi.listSuppliers()) ?? []).map(supplierFromApi),
  });
}

/** `variants` maps variant id -> catalog entry (names/colour/size); `suppliers` maps supplier id -> name. */
export function usePurchaseOrders({ suppliers = {}, variants = {} } = {}) {
  return useQuery({
    queryKey: [...ORDERS_KEY, Object.keys(suppliers).length, Object.keys(variants).length],
    queryFn: async () => ((await posApi.listPurchaseOrders()) ?? []).map((o) => orderFromApi(o, { suppliers, variants })),
  });
}

export function useSupplierReturns({ suppliers = {}, variants = {}, orders = {} } = {}) {
  return useQuery({
    queryKey: [...RETURNS_KEY, Object.keys(suppliers).length, Object.keys(variants).length, Object.keys(orders).length],
    queryFn: async () => ((await posApi.listSupplierReturns()) ?? []).map((r) => returnFromApi(r, { suppliers, variants, orders })),
  });
}

export function useSupplierPayments() {
  return useQuery({ queryKey: PAYMENTS_KEY, queryFn: async () => (await posApi.listSupplierPayments()) ?? [] });
}

function useRefresh() {
  const qc = useQueryClient();
  // Receiving changes stock and a payment/refund changes the drawer, so everything derived from them is re-read.
  return () =>
    Promise.all(
      [SUPPLIERS_KEY, ORDERS_KEY, RETURNS_KEY, PAYMENTS_KEY, CATALOG_KEY, SHIFTS_KEY, SHIFT_STATE_KEY].map((queryKey) =>
        qc.invalidateQueries({ queryKey }),
      ),
    );
}

/**
 * One Idempotency-Key per user intention (see intentStore.js): the same content re-sent reuses the key so the
 * server replays; changed content, after the user fixed a refusal, gets a new one. The store lives in a ref: a
 * plain Map built in the hook body would be new on every render.
 */
function useIntentMutation(call) {
  const refresh = useRefresh();
  const store = useRef(null);
  if (!store.current) store.current = createIntentStore();
  return useMutation({
    mutationFn: async ({ slot, ...args }) => {
      const key = slot ?? "new";
      const intent = store.current.take(key, args);
      const result = await call(args, intent);
      store.current.done(key);
      return result;
    },
    onSuccess: refresh,
  });
}

export function useCreateSupplier() {
  const refresh = useRefresh();
  return useMutation({ mutationFn: (body) => posApi.createSupplier(body), onSuccess: refresh });
}

export function useUpdateSupplier() {
  const refresh = useRefresh();
  return useMutation({ mutationFn: ({ id, body }) => posApi.updateSupplier(id, body), onSuccess: refresh });
}

export const useCreatePurchaseOrder = () => useIntentMutation(({ payload }, intent) => posApi.createPurchaseOrder(payload, intent));
export const useCancelPurchaseOrder = () => useIntentMutation(({ id }, intent) => posApi.cancelPurchaseOrder(id, intent));
export const useReceivePurchaseOrder = () => useIntentMutation(({ id }, intent) => posApi.receivePurchaseOrder(id, intent));
export const usePaySupplier = () => useIntentMutation(({ payload }, intent) => posApi.createSupplierPayment(payload, intent));
export const useCreateSupplierReturn = () => useIntentMutation(({ payload }, intent) => posApi.createSupplierReturn(payload, intent));
export const useAcceptSupplierReturn = () =>
  useIntentMutation(({ id }, intent) => posApi.acceptSupplierReturn(id, {}, intent));
export const useRejectSupplierReturn = () => useIntentMutation(({ id }, intent) => posApi.rejectSupplierReturn(id, intent));
