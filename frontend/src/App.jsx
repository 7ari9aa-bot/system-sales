import { Suspense, lazy } from 'react';
import { Toaster } from "@/components/ui/toaster"
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClientInstance } from '@/lib/query-client'
import { BrowserRouter as Router, Route, Routes, Navigate, useLocation, useParams } from 'react-router-dom';
import PageNotFound from './lib/PageNotFound';
import { AuthProvider, useAuth } from '@/lib/AuthContext';
import { LanguageProvider } from '@/lib/marketing-i18n';
import ScrollToTop from './components/ScrollToTop';
import DashboardLayout from '@/components/dashboard/DashboardLayout';
import { ThemeProvider } from '@/lib/themeContext';
import { I18nProvider } from '@/lib/i18n';
import { RegionalProvider } from '@/lib/regional';
import { CountryProvider } from '@/lib/CountryContext';
import ProtectedRoute from '@/components/ProtectedRoute';
import VisitorTracker from '@/components/VisitorTracker';
import { ALL_LOCALIZED_ROUTES } from '@/lib/public-seo-routes.mjs';
const Fihrist = lazy(() => import('@/pages/Fihrist'));
const Login = lazy(() => import('@/pages/Login'));
const Register = lazy(() => import('@/pages/Register'));
const ForgotPassword = lazy(() => import('@/pages/ForgotPassword'));
const ResetPassword = lazy(() => import('@/pages/ResetPassword'));
const VerifyEmail = lazy(() => import('@/pages/VerifyEmail'));
const AcceptInvitation = lazy(() => import('@/pages/AcceptInvitation'));
const Home = lazy(() => import('@/pages/Home'));
const Inbox = lazy(() => import('@/pages/Inbox'));
const InstagramLayout = lazy(() => import('@/pages/instagram/InstagramLayout'));
const InstagramDirectPage = lazy(() => import('@/pages/instagram/InstagramDirectPage'));
const InstagramActivityPage = lazy(() => import('@/pages/instagram/InstagramActivityPage'));
const InstagramProfilePage = lazy(() => import('@/pages/instagram/InstagramProfilePage'));
const InstagramUserPage = lazy(() => import('@/pages/instagram/InstagramUserPage'));
const InstagramSettingsPage = lazy(() => import('@/pages/instagram/InstagramSettingsPage'));
const FacebookLayout = lazy(() => import('@/pages/facebook/FacebookLayout'));
const FacebookPostsPage = lazy(() => import('@/pages/facebook/FacebookPostsPage'));
const FacebookMessagesRedirect = lazy(() => import('@/pages/facebook/FacebookMessagesRedirect'));
const FacebookActivityPage = lazy(() => import('@/pages/facebook/FacebookActivityPage'));
const FacebookInsightsPage = lazy(() => import('@/pages/facebook/FacebookInsightsPage'));
const FacebookReelsPage = lazy(() => import('@/pages/facebook/FacebookReelsPage'));
const Customers = lazy(() => import('@/pages/Customers'));
const Inventory = lazy(() => import('@/pages/Inventory'));
const CashierApp = lazy(() => import('@/cashier/CashierApp'));

// وضع معاينة الكاشير: يفتح مسار /cashier/* فقط بدون تسجيل دخول، لمعاينة الواجهة (بيانات تجريبية) على Vercel Preview.
// vite.config.js يمنع البناء تماماً لو اتفعّل مع بيئة الإنتاج، فلا يمكن أن يصل لمستخدمين حقيقيين.
const CASHIER_PREVIEW = import.meta.env.VITE_CASHIER_PREVIEW === '1';
const AI = lazy(() => import('@/pages/AI'));
const SalesAssistant = lazy(() => import('@/pages/SalesAssistant'));
const Analytics = lazy(() => import('@/pages/Analytics'));
const OwnerConsole = lazy(() => import('@/pages/OwnerConsole'));
const Usage = lazy(() => import('@/pages/Usage'));
// «My Website» — a pointer to the standalone Fihrist Sites platform (Fihrist no longer builds sites).
const Websites = lazy(() => import('@/pages/Websites'));
import SettingsLayout from '@/components/settings/SettingsLayout';
const ProfileSettings = lazy(() => import('@/pages/settings/ProfileSettings'));
const WorkspaceSettings = lazy(() => import('@/pages/settings/WorkspaceSettings'));
const MembersSettings = lazy(() => import('@/pages/settings/MembersSettings'));
const TeamSettings = lazy(() => import('@/pages/settings/TeamSettings'));
const ChannelsSettings = lazy(() => import('@/pages/settings/ChannelsSettings'));
const PosSettings = lazy(() => import('@/pages/settings/PosSettings'));
const SecuritySettings = lazy(() => import('@/pages/settings/SecuritySettings'));
const LoginSettings = lazy(() => import('@/pages/settings/LoginSettings'));
const PreferencesSettings = lazy(() => import('@/pages/settings/PreferencesSettings'));
const NotificationPreferences = lazy(() => import('@/pages/settings/NotificationPreferences'));
const SettingsSection = lazy(() => import('@/pages/settings/SettingsSection'));
const UnifiedSettings = lazy(() => import('@/pages/settings/UnifiedSettings'));
const BillingSettings = lazy(() => import('@/pages/settings/BillingSettings'));
const DataSettings = lazy(() => import('@/pages/settings/DangerZoneSettings'));

/** الموقع العام (الماركتنج) — عام للزوار، بدون مصادقة.
 *  Fihrist بيقرأ المسار بنفسه ويرسم الصفحة المناسبة داخل Layout الموحد. */
const MarketingRoutes = () => (
  <LanguageProvider>
    <CountryProvider>
      <Routes>
        {ALL_LOCALIZED_ROUTES.map(({ path }) => (
          <Route key={path} path={path} element={<Fihrist />} />
        ))}
        {/* Support legacy unprefixed paths gracefully mapping to default market */}
        <Route path="/product" element={<Fihrist />} />
        <Route path="/conversations" element={<Fihrist />} />
        <Route path="/assistant" element={<Fihrist />} />
        <Route path="/automation" element={<Fihrist />} />
        <Route path="/pricing" element={<Fihrist />} />
        <Route path="/security" element={<Fihrist />} />
        <Route path="/privacy" element={<Fihrist />} />
        <Route path="/terms" element={<Fihrist />} />
        <Route path="/data-deletion" element={<Fihrist />} />
        <Route path="/contact-sales" element={<Fihrist />} />
        <Route path="/support" element={<Fihrist />} />
        <Route path="/download" element={<Fihrist />} />
        <Route path="/mobile" element={<Fihrist />} />
        <Route path="/solutions/*" element={<Fihrist />} />
        <Route path="/blog/*" element={<Fihrist />} />
        <Route path="*" element={<PageNotFound />} />
      </Routes>
    </CountryProvider>
  </LanguageProvider>
);

const AuthRoutes = () => (
  <LanguageProvider>
    <VisitorTracker />
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
        {/* Instagram: one real page per section, so links, back and refresh keep your place. */}
        <Route path="/instagram" element={<InstagramLayout />}>
          {/* Same addresses as instagram.com, under /instagram. */}
          <Route index element={<Navigate to="direct/inbox" replace />} />
          <Route path="direct" element={<Navigate to="/instagram/direct/inbox" replace />} />
          <Route path="direct/inbox" element={<InstagramDirectPage />} />
          <Route path="direct/general" element={<InstagramDirectPage folder="general" />} />
          <Route path="direct/requests" element={<InstagramDirectPage folder="requests" />} />
          <Route path="direct/archived" element={<InstagramDirectPage folder="archived" />} />
          <Route path="direct/t/:threadId" element={<InstagramDirectPage />} />
          <Route path="activity" element={<InstagramActivityPage />} />
          <Route path="settings" element={<InstagramSettingsPage />} />
          <Route path="profile" element={<InstagramProfilePage />} />
          <Route path="profile/reels" element={<InstagramProfilePage tab="reels" />} />
          <Route path="p/:postId" element={<InstagramProfilePage />} />
          <Route path="u/:customerId" element={<InstagramUserPage />} />
          <Route path="*" element={<Navigate to="/instagram/direct/inbox" replace />} />
        </Route>
        {/* Facebook: one real page per section, so links, back and refresh keep your place. */}
        <Route path="/facebook" element={<FacebookLayout />}>
          <Route index element={<Navigate to="posts" replace />} />
          <Route path="posts" element={<FacebookPostsPage />} />
          <Route path="posts/:postId" element={<FacebookPostsPage />} />
          <Route path="messages" element={<FacebookMessagesRedirect />} />
          <Route path="messages/:threadId" element={<FacebookMessagesRedirect />} />
          <Route path="activity" element={<FacebookActivityPage />} />
          <Route path="reels" element={<FacebookReelsPage />} />
          <Route path="insights" element={<FacebookInsightsPage />} />
          <Route path="*" element={<Navigate to="/facebook/posts" replace />} />
        </Route>
        <Route path="/customers" element={<Customers />} />
        {/* المنتجات والمخزون انتقلوا للكاشير: الروابط القديمة تحوّل للصفحات الجديدة. */}
        <Route path="/products" element={<Navigate to="/cashier/inventory" replace />} />
        <Route path="/products/new" element={<Navigate to="/cashier/products/new" replace />} />
        {/* رابط تعديل منتج قديم كان بيقع على 404 لأن الصفحة بقت تحت /cashier. */}
        <Route path="/products/:productId/edit" element={<LegacyProductEditRedirect />} />
        <Route path="/inventory" element={<Navigate to="/cashier/inventory" replace />} />
        <Route path="/supply-chain" element={<Navigate to="/cashier/supply-chain" replace />} />
        <Route path="/pos" element={<Navigate to="/cashier/pos" replace />} />
        {/* The manual sales workspace is gone; the cashier took its place. Old
            links (bookmarks, cached ?s=new|returns|exchanges) redirect there
            instead of landing on the 404 screen. */}
        <Route path="/orders" element={<Navigate to="/cashier/pos" replace />} />
        <Route path="/orders/:rest" element={<Navigate to="/cashier/pos" replace />} />
        {/* Marketing is not part of the first release: the old links land on the dashboard, not on a 404. */}
        <Route path="/marketing/*" element={<Navigate to="/dashboard" replace />} />
        <Route path="/ai" element={<Navigate to="/settings/ai" replace />} />
        <Route path="/sales-assistant" element={<SalesAssistant />} />
        <Route path="/analytics" element={<Analytics />} />
        <Route path="/owner" element={<OwnerConsole />} />
        <Route path="/usage" element={<Navigate to="/settings/usage" replace />} />
        <Route path="/website" element={<Websites />} />
      </Route>
      <Route element={<ProtectedRoute />}>
        <Route element={<SettingsLayout />}>
          <Route path="/settings" element={<ProfileSettings />} />
          <Route path="/settings/workspace" element={<WorkspaceSettings />} />
          <Route path="/settings/workspace/:section" element={<WorkspaceSettings />} />
          <Route path="/settings/channels" element={<ChannelsSettings />} />
          {/* Section 12's cross-channel pages must be registered BEFORE :channel, or the
              parameter route swallows them and reports "no channel with this name". */}
          <Route path="/settings/channels/data-sync" element={<ChannelSectionPage page="data-sync" />} />
          <Route path="/settings/channels/external-integrations" element={<ChannelSectionPage page="external-integrations" />} />
          <Route path="/settings/channels/connection-health" element={<ChannelSectionPage page="connection-health" />} />
          <Route path="/settings/channels/:channel" element={<ChannelsSettings />} />
          <Route path="/settings/ai" element={<AI />} />
          <Route path="/settings/ai/:page" element={<SettingsSection section="ai" />} />
          <Route path="/settings/analytics/:page" element={<SettingsSection section="analytics" />} />
          <Route path="/settings/automation/:page" element={<SettingsSection section="automation" />} />
          <Route path="/settings/usage" element={<Usage />} />
          {/* Section 08 owns /settings/pos. The old wrapper's slugs that now have a canonical
              home forward to it, so an old bookmark lands on the single place that edits the
              setting instead of a second editor. The tool screens that are not settings (receipts
              tracking, team access, backup) stay reachable under /settings/pos/tools. */}
          <Route path="/settings/pos" element={<Navigate to="/settings/pos/pos-settings" replace />} />
          <Route path="/settings/pos/legacy/:section" element={<PosSettings />} />
          <Route path="/settings/pos/shop" element={<Navigate to="/settings/store/business-profile" replace />} />
          <Route path="/settings/pos/policy" element={<Navigate to="/settings/store/business-policies" replace />} />
          <Route path="/settings/pos/einvoice" element={<Navigate to="/settings/sales/taxes-and-fees" replace />} />
          <Route path="/settings/pos/print" element={<Navigate to="/settings/pos/invoices-and-receipts" replace />} />
          <Route path="/settings/pos/lists" element={<Navigate to="/settings/catalog/categories" replace />} />
          <Route path="/settings/pos/devices" element={<Navigate to="/settings/pos/registers-and-devices" replace />} />
          <Route path="/settings/pos/tools/:section" element={<PosSettings />} />
          <Route path="/settings/pos/:page" element={<SettingsSection section="pos" />} />
          <Route path="/settings/purchasing" element={<Navigate to="/settings/purchasing/suppliers" replace />} />
          <Route path="/settings/purchasing/:page" element={<SettingsSection section="purchasing" />} />
          <Route path="/settings/customers" element={<Navigate to="/settings/customers/customer-records" replace />} />
          <Route path="/settings/customers/:page" element={<SettingsSection section="customers" />} />
          <Route path="/settings/policies" element={<Navigate to="/settings/store/business-policies" replace />} />
          <Route path="/settings/billing" element={<BillingSettings />} />
          <Route path="/settings/members" element={<MembersSettings />} />
          <Route path="/settings/team" element={<TeamSettings />} />
          <Route path="/settings/team/:section" element={<TeamSettings />} />
          <Route path="/settings/all" element={<UnifiedSettings />} />
          <Route path="/settings/security" element={<SecuritySettings />} />
          {/* Section 18. The path is longer than the personal-security screen above on purpose:
              "my password and my devices" and "the shop's security policies" are two different
              screens, and merging them would put a workspace control on a personal page. */}
          <Route path="/settings/security/:page" element={<SettingsSection section="security" />} />
          <Route path="/settings/login" element={<LoginSettings />} />
          <Route path="/settings/preferences" element={<PreferencesSettings />} />
          <Route path="/settings/notifications" element={<NotificationPreferences />} />
          <Route path="/settings/notifications/:page" element={<SettingsSection section="notifications" />} />
          <Route path="/settings/data/:page" element={<SettingsSection section="data" />} />
          <Route path="/settings/danger" element={<DataSettings />} />
          {/* The Settings Center map: a section is a navigation group with its own pages, and
              each page renders only the keys whose registry home is that section+page. */}
          <Route path="/settings/store" element={<Navigate to="/settings/store/business-profile" replace />} />
          <Route path="/settings/store/:page" element={<SettingsSection section="store" />} />
          <Route path="/settings/locations" element={<Navigate to="/settings/locations/all-branches" replace />} />
          <Route path="/settings/locations/:page" element={<SettingsSection section="locations" />} />
          <Route path="/settings/catalog" element={<Navigate to="/settings/catalog/product-settings" replace />} />
          <Route path="/settings/catalog/:page" element={<SettingsSection section="catalog" />} />
          <Route path="/settings/sales" element={<Navigate to="/settings/sales/sales-settings" replace />} />
          <Route path="/settings/sales/:page" element={<SettingsSection section="sales" />} />
          <Route path="/settings/inventory" element={<Navigate to="/settings/inventory/inventory-settings" replace />} />
          <Route path="/settings/inventory/:page" element={<SettingsSection section="inventory" />} />
        </Route>
      </Route>
    </Route>
    <Route path="*" element={<PageNotFound />} />
  </Routes>
);

function LegacyProductEditRedirect() {
  const { productId } = useParams();
  return <Navigate to={`/cashier/products/${productId}/edit`} replace />;
}

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
  if (['/dashboard', '/inbox', '/instagram', '/facebook', '/customers', '/products', '/inventory', '/supply-chain', '/pos', '/cashier', '/sales',
    '/sales-assistant', '/marketing', '/ai', '/analytics', '/owner', '/usage', '/website', '/settings'].some(under)) {
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
