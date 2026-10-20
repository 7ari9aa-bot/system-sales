// منتجات يضيفها المستخدم من شاشة «إضافة منتج»: محفوظة محليًا وتظهر في خانة منتجات النظام بصفحة المخزون.
import { useSyncExternalStore } from "react";
import { products as seedProducts, shop } from "@/cashier/lib/mockData";

const STORAGE_KEY = "boutique-added-products";

function readAdded() {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveAdded(list) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
  } catch {
    /* تجاهل: تبقى المنتجات في الذاكرة */
  }
}

let state = { added: readAdded() };
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

// المنتجات المُضافة من شاشة الإضافة (الأحدث أولاً).
export function useAddedProducts() {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot).added;
}

// كل منتجات النظام: المُضافة أولاً ثم كتالوج النموذج.
export function systemProducts(added) {
  return [...added, ...seedProducts];
}

// تحويل بيانات نموذج الإضافة إلى منتج كامل بتركيبات اللون والمقاس.
export function buildProductRecord(values) {
  const id = `add-${Date.now()}`;
  const variants = (values.variants ?? []).map((v, i) => ({
    id: `${id}-${i + 1}`,
    productId: id,
    productName: String(values.name).trim(),
    color: v.color,
    size: v.size,
    sku: v.sku,
    barcode: v.barcode,
    stock: Number(v.stock) || 0,
    buyPrice: Number(v.buyPrice) || 0,
    sellPrice: Number(v.sellPrice) || 0,
  }));

  return {
    id,
    sku: variants[0]?.sku || `ADD-${String(Date.now()).slice(-6)}`,
    barcode: variants[0]?.barcode || "",
    name: String(values.name).trim(),
    category: values.category,
    brand: values.brand,
    description: values.description ?? "",
    buyPrice: Number(values.buyPrice) || 0,
    sellPrice: Number(values.sellPrice) || 0,
    threshold: Number(values.threshold) || shop.lowStockThreshold,
    status: "active",
    variants,
    variantsCount: variants.length,
    totalStock: variants.reduce((s, v) => s + v.stock, 0),
    colors: [...new Set(variants.map((v) => v.color))],
    sizes: [...new Set(variants.map((v) => v.size))],
    addedAt: new Date().toISOString(),
  };
}

export function addProduct(record) {
  state = { added: [record, ...state.added] };
  saveAdded(state.added);
  emit();
}