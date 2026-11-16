import React, { createContext, useContext, useMemo } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  MARKETS,
  DEFAULT_COUNTRY_SLUG,
  getMarket,
  formatMarketPrice,
} from '@/lib/markets';
import { resolveLocalizedPath, buildLocalizedRoute } from '@/lib/public-seo-routes.mjs';

const CountryContext = createContext(null);

function useSafeLocation() {
  try {
    return useLocation();
  } catch {
    const pathname = typeof window !== 'undefined' ? window.location?.pathname || '/' : '/';
    return { pathname };
  }
}

function useSafeNavigate() {
  try {
    return useNavigate();
  } catch {
    return (newPath) => {
      if (typeof window !== 'undefined' && window.location) {
        window.location.pathname = newPath;
      }
    };
  }
}

function resolveMarketState(pathname) {
  const { country, locale, basePath, isSelector, isWaitlist, isLive, isUnknown } = resolveLocalizedPath(pathname);
  const activeCountrySlug = country || DEFAULT_COUNTRY_SLUG;
  const market = getMarket(activeCountrySlug) || MARKETS[DEFAULT_COUNTRY_SLUG];
  const activeLocale = locale || 'ar';
  const activeBasePath = basePath || '/';

  return {
    country: activeCountrySlug,
    market,
    locale: activeLocale,
    basePath: activeBasePath,
    isSelector: Boolean(isSelector),
    isWaitlist: Boolean(isWaitlist),
    isLive: Boolean(isLive),
    isUnknown: Boolean(isUnknown),
    formatPrice: (amount) => formatMarketPrice(amount, activeCountrySlug, activeLocale),
    hasCapability: (cap) => market?.capabilities?.includes(cap) ?? false,
  };
}

export function CountryProvider({ children }) {
  const location = useSafeLocation();
  const navigate = useSafeNavigate();

  const baseState = useMemo(() => {
    return resolveMarketState(location.pathname);
  }, [location.pathname]);

  const changeCountry = (newCountrySlug) => {
    const targetCountry = newCountrySlug.toLowerCase();
    const newPath = buildLocalizedRoute(targetCountry, baseState.locale, baseState.basePath);
    navigate(newPath);
  };

  const changeLocale = (newLocale) => {
    const newPath = buildLocalizedRoute(baseState.country, newLocale, baseState.basePath);
    navigate(newPath);
  };

  const value = {
    ...baseState,
    changeCountry,
    changeLocale,
  };

  return <CountryContext.Provider value={value}>{children}</CountryContext.Provider>;
}

export function useCountry() {
  const context = useContext(CountryContext);
  if (context) return context;

  // Graceful fallback for SSR prerendering and isolated component tests
  const pathname = typeof window !== 'undefined' ? window.location?.pathname || '/' : '/';
  const fallbackState = resolveMarketState(pathname);

  return {
    ...fallbackState,
    changeCountry: (newCountrySlug) => {
      if (typeof window !== 'undefined' && window.location) {
        window.location.pathname = buildLocalizedRoute(newCountrySlug.toLowerCase(), fallbackState.locale, fallbackState.basePath);
      }
    },
    changeLocale: (newLocale) => {
      if (typeof window !== 'undefined' && window.location) {
        window.location.pathname = buildLocalizedRoute(fallbackState.country, newLocale, fallbackState.basePath);
      }
    },
  };
}
