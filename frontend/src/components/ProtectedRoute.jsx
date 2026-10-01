import { useEffect } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '@/lib/AuthContext';
import UserNotRegisteredError from '@/components/UserNotRegisteredError';
import { useT } from '@/lib/i18n';

const DefaultFallback = () => (
  <div className="fixed inset-0 flex items-center justify-center">
    <div className="w-8 h-8 border-4 border-slate-200 border-t-slate-800 rounded-full animate-spin"></div>
  </div>
);

export default function ProtectedRoute({ fallback = <DefaultFallback />, unauthenticatedElement }) {
  const { isAuthenticated, isLoadingAuth, authChecked, authError, checkUserAuth } = useAuth();
  const location = useLocation();
  const t = useT();
  const returnTo = `${location.pathname}${location.search}${location.hash}`;

  useEffect(() => {
    if (!authChecked && !isLoadingAuth) {
      checkUserAuth();
    }
  }, [authChecked, isLoadingAuth, checkUserAuth]);

  if (isLoadingAuth || !authChecked) {
    return fallback;
  }

  if (authError) {
    if (authError.type === 'user_not_registered') {
      return <UserNotRegisteredError />;
    }
    if (authError.type === 'auth_unavailable') {
      return (
        <div className="fixed inset-0 grid place-items-center bg-background p-6">
          <div className="max-w-md text-center">
            <p className="text-sm text-muted-foreground" role="alert">
              {authError.message || t('auth.sessionCheckFailed', 'Could not verify your session. Check your connection and try again.')}
            </p>
            <button
              type="button"
              onClick={() => { void checkUserAuth(); }}
              className="mt-4 h-10 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground"
            >
              {t('common.retry', 'Try again')}
            </button>
          </div>
        </div>
      );
    }
    return unauthenticatedElement ?? <Navigate to={`/login?returnTo=${encodeURIComponent(returnTo)}`} replace />;
  }

  if (!isAuthenticated) {
    return unauthenticatedElement ?? <Navigate to={`/login?returnTo=${encodeURIComponent(returnTo)}`} replace />;
  }

  return <Outlet />;
}
