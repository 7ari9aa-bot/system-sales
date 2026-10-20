import { lazy, Suspense } from "react";
import { Navigate, Outlet, Route, Routes } from "react-router-dom";
import { Toaster } from "@/cashier/components/ui/sonner";
import "./cashier.css";

// كل صفحات الكاشير تُحمَّل عند الطلب حتى لا تثقل باقي النظام.
const Page0 = lazy(() => import("./routes/_authed/activity-log.jsx"));
const Page1 = lazy(() => import("./routes/_authed/exchanges.index.jsx"));
const Page2 = lazy(() => import("./routes/_authed/exchanges.log.jsx"));
const Page3 = lazy(() => import("./routes/_authed/expenses.jsx"));
const Page4 = lazy(() => import("./routes/_authed/inventory.index.jsx"));
const Page5 = lazy(() => import("./routes/_authed/inventory.movements.jsx"));
const Page6 = lazy(() => import("./routes/_authed/inventory.stocktake.jsx"));
const Page7 = lazy(() => import("./routes/_authed/labels.jsx"));
const Page8 = lazy(() => import("./routes/_authed/pos.jsx"));
const Page9 = lazy(() => import("./routes/_authed/products.$productId.edit.jsx"));
const Page10 = lazy(() => import("./routes/_authed/products.index.jsx"));
const Page11 = lazy(() => import("./routes/_authed/products.new.jsx"));
const Page12 = lazy(() => import("./routes/_authed/purchases.jsx"));
const Page13 = lazy(() => import("./routes/_authed/reports.jsx"));
const Page14 = lazy(() => import("./routes/_authed/returns.index.jsx"));
const Page15 = lazy(() => import("./routes/_authed/returns.log.jsx"));
const Page16 = lazy(() => import("./routes/_authed/sales.$invoiceId.jsx"));
const Page17 = lazy(() => import("./routes/_authed/sales.index.jsx"));
const Page18 = lazy(() => import("./routes/_authed/settings.jsx"));
const Page19 = lazy(() => import("./routes/_authed/shifts.jsx"));
const Page20 = lazy(() => import("./routes/_authed/supplier-returns.jsx"));
const Page21 = lazy(() => import("./routes/_authed/suppliers.jsx"));

function CashierLayout() {
  // الهيكل (السايدبار والتنقل) جاي من DashboardLayout في النظام الرئيسي؛ هنا بس الثيم المعزول.
  return (
    <div className="cashier-root" dir="rtl">
      <Suspense fallback={<div className="p-8 text-center text-sm text-muted-foreground">جارٍ التحميل…</div>}>
        <Outlet />
      </Suspense>
      {/* Every toast() in the cashier (sale done, stock warnings, errors) needs this host; the main app mounts a different toaster. */}
      <Toaster position="top-center" dir="rtl" />
    </div>
  );
}

// يُركَّب تحت /cashier/* في App.jsx (الدخول والصلاحيات من النظام الرئيسي).
export default function CashierApp() {
  return (
    <Routes>
      <Route element={<CashierLayout />}>
        <Route index element={<Navigate to="pos" replace />} />
        <Route path="activity-log" element={<Page0 />} />
        <Route path="exchanges" element={<Page1 />} />
        <Route path="exchanges/log" element={<Page2 />} />
        <Route path="expenses" element={<Page3 />} />
        <Route path="inventory" element={<Page4 />} />
        <Route path="inventory/movements" element={<Page5 />} />
        <Route path="inventory/stocktake" element={<Page6 />} />
        <Route path="labels" element={<Page7 />} />
        <Route path="pos" element={<Page8 />} />
        <Route path="products/:productId/edit" element={<Page9 />} />
        <Route path="products" element={<Page10 />} />
        <Route path="products/new" element={<Page11 />} />
        <Route path="purchases" element={<Page12 />} />
        <Route path="reports" element={<Page13 />} />
        <Route path="returns" element={<Page14 />} />
        <Route path="returns/log" element={<Page15 />} />
        <Route path="sales/:invoiceId" element={<Page16 />} />
        <Route path="sales" element={<Page17 />} />
        <Route path="settings" element={<Page18 />} />
        <Route path="shifts" element={<Page19 />} />
        <Route path="supplier-returns" element={<Page20 />} />
        <Route path="suppliers" element={<Page21 />} />
        <Route path="*" element={<Navigate to="/cashier/pos" replace />} />
      </Route>
    </Routes>
  );
}
