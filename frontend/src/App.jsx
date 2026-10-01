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
import Fihrist from '@/pages/Fihrist';
import Login from '@/pages/Login';
import Register from '@/pages/Register';
import ForgotPassword from '@/pages/ForgotPassword';
import ResetPassword from '@/pages/ResetPassword';
import AcceptInvitation from '@/pages/AcceptInvitation';
import Home from '@/pages/Home';
import Inbox from '@/pages/Inbox';
import Customers from '@/pages/Customers';
import Orders from '@/pages/Orders';
import Products from '@/pages/Products';
import Inventory from '@/pages/Inventory';
import Marketing from '@/pages/Marketing';
import MarketingCampaigns from '@/pages/marketing/Campaigns';
import MarketingAudience from '@/pages/marketing/Audience';
import MarketingAutomation from '@/pages/marketing/Automation';
import AI from '@/pages/AI';
import Analytics from '@/pages/Analytics';
import Usage from '@/pages/Usage';
import SettingsLayout from '@/components/settings/SettingsLayout';
import ProfileSettings from '@/pages/settings/ProfileSettings';
import MembersSettings from '@/pages/settings/MembersSettings';
import ChannelsSettings from '@/pages/settings/ChannelsSettings';
import SecuritySettings from '@/pages/settings/SecuritySettings';
import BillingSettings from '@/pages/settings/BillingSettings';
import DangerZoneSettings from '@/pages/settings/DangerZoneSettings';

/** الموقع العام (الماركتنج) — عام للزوار، بدون مصادقة.
 *  Fihrist بيقرأ المسار بنفسه ويرسم الصفحة المناسبة داخل Layout الموحد. */
const MarketingRoutes = () => (
  <LanguageProvider>
    <Routes>
      <Route path="/" element={<Fihrist />} />
      <Route path="/product" element={<Fihrist />} />
      <Route path="/conversations" element={<Fihrist />} />
      <Route path="/context" element={<Fihrist />} />
      <Route path="/assistant" element={<Fihrist />} />
      <Route path="/automation" element={<Fihrist />} />
      <Route path="/pricing" element={<Fihrist />} />
      <Route path="/security" element={<Fihrist />} />
      <Route path="/privacy" element={<Fihrist />} />
      <Route path="/terms" element={<Fihrist />} />
      <Route path="/contact-sales" element={<Fihrist />} />
      <Route path="/support" element={<Fihrist />} />
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
        <Route path="/inventory" element={<Inventory />} />
        <Route path="/marketing" element={<Marketing />}>
          <Route index element={<MarketingCampaigns />} />
          <Route path="audience" element={<MarketingAudience />} />
          <Route path="automation" element={<MarketingAutomation />} />
        </Route>
        <Route path="/ai" element={<AI />} />
        <Route path="/analytics" element={<Analytics />} />
        <Route path="/usage" element={<Usage />} />
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
                <PathRouter />
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
  if (['/dashboard', '/inbox', '/customers', '/orders', '/products', '/inventory',
    '/marketing', '/ai', '/analytics', '/usage', '/settings'].some(under)) {
    return <DashboardRoutes />;
  }
  if (['/login', '/register', '/forgot-password', '/reset-password', '/accept-invitation'].some(under)) {
    return <AuthRoutes />;
  }
  return <MarketingRoutes />;
}

export default App
