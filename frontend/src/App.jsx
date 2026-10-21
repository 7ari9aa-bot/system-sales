import { Suspense, lazy } from 'react';
import { Toaster } from "@/components/ui/toaster"
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClientInstance } from '@/lib/query-client'
import { BrowserRouter as Router, Route, Routes, Navigate, useLocation } from 'react-router-dom';
import PageNotFound from './lib/PageNotFound';
import { AuthProvider, useAuth } from '@/lib/AuthContext';
import { LanguageProvider } from '@/lib/marketing-i18n';
import ScrollToTop from './components/ScrollToTop';
import DashboardLayout from '@/components/dashboard/DashboardLayout';
import { ThemeProvider } from '@/lib/themeContext';
import { I18nProvider } from '@/lib/i18n';
import { RegionalProvider } from '@/lib/regional';
import ProtectedRoute from '@/components/ProtectedRoute';
import { PUBLIC_SEO_ROUTES } from '@/lib/public-seo-routes.mjs';
const Fihrist = lazy(() => import('@/pages/Fihrist'));
const Login = lazy(() => import('@/pages/Login'));
const Register = lazy(() => import('@/pages/Register'));
const ForgotPassword = lazy(() => import('@/pages/ForgotPassword'));
const ResetPassword = lazy(() => import('@/pages/ResetPassword'));
const VerifyEmail = lazy(() => import('@/pages/VerifyEmail'));
const AcceptInvitation = lazy(() => import('@/pages/AcceptInvitation'));
const Home = lazy(() => import('@/pages/Home'));
const Inbox = lazy(() => import('@/pages/Inbox'));
const Customers = lazy(() => import('@/pages/Customers'));
const Products = lazy(() => import('@/pages/Products'));
const AddProduct = lazy(() => import('@/pages/AddProduct'));
const Inventory = lazy(() => import('@/pages/Inventory'));
const CashierApp = lazy(() => import('@/cashier/CashierApp'));

// وضع معاينة الكاشير: يفتح مسار /cashier/* فقط بدون تسجيل دخول، لمعاينة الواجهة (بيانات تجريبية) على Vercel Preview.
// vite.config.js يمنع البناء تماماً لو اتفعّل مع بيئة الإنتاج، فلا يمكن أن يصل لمستخدمين حقيقيين.
const CASHIER_PREVIEW = import.meta.env.VITE_CASHIER_PREVIEW === '1';
const AI = lazy(() => import('@/pages/AI'));
const SalesAssistant = lazy(() => import('@/pages/SalesAssistant'));
const Analytics = lazy(() => import('@/pages/Analytics'));
const Usage = lazy(() => import('@/pages/Usage'));
const WebsiteComingSoon = lazy(() => import('@/pages/WebsiteComingSoon'));
import SettingsLayout from '@/components/settings/SettingsLayout';
const ProfileSettings = lazy(() => import('@/pages/settings/ProfileSettings'));
const MembersSettings = lazy(() => import('@/pages/settings/MembersSettings'));
const ChannelsSettings = lazy(() => import('@/pages/settings/ChannelsSettings'));
const PosSettings = lazy(() => import('@/pages/settings/PosSettings'));
const SecuritySettings = lazy(() => import('@/pages/settings/SecuritySettings'));
const BillingSettings = lazy(() => import('@/pages/settings/BillingSettings'));
const DangerZoneSettings = lazy(() => import('@/pages/settings/DangerZoneSettings'));

/** الموقع العام (الماركتنج) — عام للزوار، بدون مصادقة.
 *  Fihrist بيقرأ المسار بنفسه ويرسم الصفحة المناسبة داخل Layout الموحد. */
const MarketingRoutes = () => (
  <LanguageProvider>
    <Routes>
      {PUBLIC_SEO_ROUTES.map(({ path }) => (
        <Route key={path} path={path} element={<Fihrist />} />
      ))}
      <Route path="*" element={<PageNotFound />} />
    </Routes>
  </LanguageProvider>
);

const AuthRoutes = () => (
  <LanguageProvider>
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/reset-password" element={<ResetPassword />} />
      <Route path="/verify-email" element={<VerifyEmail />} />
      <Route path="/accept-invitation" element={<AcceptInvitation />} />
      <Route path="*" element={<PageNotFound />} />
    </Routes>
  </LanguageProvider>
);

const DashboardRoutes = () => (
  <Routes>
    {CASHIER_PREVIEW && (
      <Route element={<DashboardLayout />}>
        <Route path="/cashier/*" element={<CashierApp />} />
      </Route>
    )}
    <Route element={<ProtectedRoute />}>
      <Route element={<DashboardLayout />}>
        {/* الكاشير داخل نفس الداشبورد والسايدبار الرئيسي. */}
        {!CASHIER_PREVIEW && <Route path="/cashier/*" element={<CashierApp />} />}
        <Route path="/dashboard" element={<Home />} />
        <Route path="/inbox" element={<Inbox />} />
        <Route path="/customers" element={<Customers />} />
        <Route path="/products" element={<Products />} />
        <Route path="/products/new" element={<AddProduct />} />
        <Route path="/inventory" element={<Inventory />} />
        <Route path="/pos" element={<Navigate to="/cashier/pos" replace />} />
        {/* The manual sales workspace is gone; the cashier took its place. Old
            links (bookmarks, cached ?s=new|returns|exchanges) redirect there
            instead of landing on the 404 screen. */}
        <Route path="/orders" element={<Navigate to="/cashier/pos" replace />} />
        <Route path="/orders/:rest" element={<Navigate to="/cashier/pos" replace />} />
        {/* Marketing is not part of the first release: the old links land on the dashboard, not on a 404. */}
        <Route path="/marketing/*" element={<Navigate to="/dashboard" replace />} />
        <Route path="/ai" element={<AI />} />
        <Route path="/sales-assistant" element={<SalesAssistant />} />
        <Route path="/analytics" element={<Analytics />} />
        <Route path="/usage" element={<Usage />} />
        <Route path="/website" element={<WebsiteComingSoon />} />
      </Route>
      <Route element={<ProtectedRoute />}>
        <Route element={<SettingsLayout />}>
          <Route path="/settings" element={<ProfileSettings />} />
          <Route path="/settings/channels" element={<ChannelsSettings />} />
          <Route path="/settings/pos" element={<PosSettings />} />
          <Route path="/settings/billing" element={<BillingSettings />} />
          <Route path="/settings/members" element={<MembersSettings />} />
          <Route path="/settings/security" element={<SecuritySettings />} />
          <Route path="/settings/danger" element={<DangerZoneSettings />} />
        </Route>
      </Route>
    </Route>
    <Route path="*" element={<PageNotFound />} />
  </Routes>
);

function App() {
  // الـRouter لازم يكون بره AuthProvider — لأن المصادقة بتستخدم
  // useNavigate جواها، وuseNavigate بتشتغل بس جوه سياق Router.
  return (
    <Router>
      <AuthProvider>
        <ThemeProvider>
          <I18nProvider>
            <RegionalProvider>
              <QueryClientProvider client={queryClientInstance}>
                <ScrollToTop />
                <Suspense fallback={<div role="status" className="grid min-h-[50vh] place-items-center text-sm text-muted-foreground">Loading…</div>}>
                  <PathRouter />
                </Suspense>
                <Toaster />
              </QueryClientProvider>
            </RegionalProvider>
          </I18nProvider>
        </ThemeProvider>
      </AuthProvider>
    </Router>
  )
}

/** التوجيه حسب المسار: مسارات الداشبورد محمية، الباقي عام.
 *  بنستخدم useLocation عشان نصروف المسار مرة واحدة هنا بدل ما
 *  كل جزء يقرر لوحده. */
function PathRouter() {
  const location = useLocation();
  const path = location.pathname;
  const under = (base) => path === base || path.startsWith(`${base}/`);
  if (['/dashboard', '/inbox', '/customers', '/products', '/inventory', '/pos', '/cashier', '/sales',
    '/sales-assistant', '/marketing', '/ai', '/analytics', '/usage', '/website', '/settings'].some(under)) {
    return <DashboardRoutes />;
  }
  // retired paths fall through to DashboardRoutes on purpose, so the
  // <Navigate to="/pos"> redirect inside it still runs instead of the 404.
  if (path === '/orders' || path.startsWith('/orders/')) {
    return <DashboardRoutes />;
  }
  if (['/login', '/register', '/forgot-password', '/reset-password', '/verify-email', '/accept-invitation'].some(under)) {
    return <AuthRoutes />;
  }
  return <MarketingRoutes />;
}

export default App
