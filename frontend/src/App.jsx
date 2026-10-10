import { Suspense, lazy } from 'react';
import { Toaster } from "@/components/ui/toaster"
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClientInstance } from '@/lib/query-client'
import { BrowserRouter as Router, Route, Routes, useLocation } from 'react-router-dom';
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
const Orders = lazy(() => import('@/pages/Orders'));
const Products = lazy(() => import('@/pages/Products'));
const AddProduct = lazy(() => import('@/pages/AddProduct'));
const Inventory = lazy(() => import('@/pages/Inventory'));
const Marketing = lazy(() => import('@/pages/Marketing'));
const MarketingCampaigns = lazy(() => import('@/pages/marketing/Campaigns'));
const MarketingAudience = lazy(() => import('@/pages/marketing/Audience'));
const MarketingAutomation = lazy(() => import('@/pages/marketing/Automation'));
const AI = lazy(() => import('@/pages/AI'));
const Analytics = lazy(() => import('@/pages/Analytics'));
const Usage = lazy(() => import('@/pages/Usage'));
const Website = lazy(() => import('@/pages/Website'));
import SettingsLayout from '@/components/settings/SettingsLayout';
const ProfileSettings = lazy(() => import('@/pages/settings/ProfileSettings'));
const MembersSettings = lazy(() => import('@/pages/settings/MembersSettings'));
const ChannelsSettings = lazy(() => import('@/pages/settings/ChannelsSettings'));
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
    <Route element={<ProtectedRoute />}>
      <Route element={<DashboardLayout />}>
        <Route path="/dashboard" element={<Home />} />
        <Route path="/inbox" element={<Inbox />} />
        <Route path="/customers" element={<Customers />} />
        <Route path="/orders" element={<Orders />} />
        <Route path="/products" element={<Products />} />
        <Route path="/products/new" element={<AddProduct />} />
        <Route path="/inventory" element={<Inventory />} />
        <Route path="/marketing" element={<Marketing />}>
          <Route index element={<MarketingCampaigns />} />
          <Route path="audience" element={<MarketingAudience />} />
          <Route path="automation" element={<MarketingAutomation />} />
        </Route>
        <Route path="/ai" element={<AI />} />
        <Route path="/analytics" element={<Analytics />} />
        <Route path="/usage" element={<Usage />} />
        <Route path="/website" element={<Website />} />
      </Route>
      <Route element={<ProtectedRoute />}>
        <Route element={<SettingsLayout />}>
          <Route path="/settings" element={<ProfileSettings />} />
          <Route path="/settings/channels" element={<ChannelsSettings />} />
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
  if (['/dashboard', '/inbox', '/customers', '/orders', '/products', '/inventory', '/sales',
    '/marketing', '/ai', '/analytics', '/usage', '/website', '/settings'].some(under)) {
    return <DashboardRoutes />;
  }
  if (['/login', '/register', '/forgot-password', '/reset-password', '/accept-invitation'].some(under)) {
    return <AuthRoutes />;
  }
  return <MarketingRoutes />;
}

export default App
