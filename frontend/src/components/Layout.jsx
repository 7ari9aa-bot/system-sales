import React, { useState, useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Search, Globe2, Menu, X, ArrowRight, Sun, Moon } from 'lucide-react';
import { useI18n, T } from '@/lib/marketing-i18n';

const NAV = [
  { to: '/product', key: 'nav.platform' },
  { to: '/conversations', key: 'nav.conversations' },
  { to: '/assistant', key: 'nav.assistant' },
  { to: '/pricing', key: 'nav.pricing' },
  { to: '/security', key: 'nav.security' },
];

function Logo() {
  return (
    <Link to="/" className="flex items-center gap-2.5 select-none" aria-label="FIHRIST home">
      <img src="/fihrist-mark.svg" alt="" className="w-7 h-7" />
      <span className="term text-[15px] text-[var(--ink)]">FIHRIST</span>
    </Link>
  );
}

function ThemeToggle() {
  const [dark, setDark] = useState(true);
  useEffect(() => {
    const root = document.documentElement;
    if (dark) root.classList.remove('light'); else root.classList.add('light');
  }, [dark]);
  return (
    <button
      onClick={() => setDark((d) => !d)}
      className="w-9 h-9 grid place-items-center rounded-md border-[0.5px] border-[var(--line)] text-[var(--ink-2)] hover:text-[var(--ink)] transition-colors"
      aria-label="Toggle theme"
    >
      {dark ? <Sun size={15} /> : <Moon size={15} />}
    </button>
  );
}

export default function Layout({ children }) {
  const { locale, toggle, t } = useI18n();
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const location = useLocation();

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  useEffect(() => setOpen(false), [location.pathname]);

  return (
    <div className="min-h-screen bg-[var(--surface)] text-[var(--ink)]">
      {/* Global Command Header — universal anchor */}
      <header
        className={`sticky top-0 z-40 backdrop-blur-xl transition-colors ${
          scrolled ? 'bg-[var(--surface)]/85 border-b-[0.5px] border-[var(--line)]' : 'bg-transparent'
        }`}
      >
        <div className="max-w-[1240px] mx-auto px-6 h-[68px] flex items-center gap-8">
          <Logo />

          {/* Centrally-locked search — width static, depth expands on hover */}
          <div className="hidden md:flex flex-1 justify-center">
            <div className="search-anchor group flex items-center gap-2.5 w-[320px] h-9 px-3.5 rounded-md border-[0.5px] border-[var(--line)] bg-[var(--surface-2)] text-[var(--ink-3)] transition-[border-color,box-shadow] hover:border-[var(--accent)]/40 hover:shadow-[0_0_0_3px_rgba(59,130,246,0.08)]">
              <Search size={14} />
              <T k="nav.searchPlaceholder" className="text-[12.5px]" />
              <kbd className="ml-auto term text-[10px] text-[var(--ink-3)] border-[0.5px] border-[var(--line)] rounded px-1.5 py-0.5">⌘K</kbd>
            </div>
          </div>

          {/* Nav — spatially anchored, fixed gaps */}
          <nav className="hidden lg:flex items-center gap-7 text-[13px] text-[var(--ink-2)]">
            {NAV.map((item) => (
              <Link
                key={item.to}
                to={item.to}
                className={`anchor hover:text-[var(--ink)] transition-colors ${
                  location.pathname === item.to ? 'text-[var(--ink)]' : ''
                }`}
              >
                <T k={item.key} />
              </Link>
            ))}
          </nav>

          {/* Far-right actions — language switcher + auth */}
          <div className="flex items-center gap-3 ml-auto lg:ml-0">
            <button
              onClick={toggle}
              className="flex items-center gap-1.5 h-9 px-2.5 rounded-md border-[0.5px] border-[var(--line)] text-[12.5px] text-[var(--ink-2)] hover:text-[var(--ink)] hover:border-[var(--ink-3)] transition-colors"
              aria-label={t('nav.toggleLang')}
            >
              <Globe2 size={14} />
              <span className="term text-[12px]">{locale === 'ar' ? 'EN' : 'عربي'}</span>
            </button>
            <ThemeToggle />
            <Link to="/login" className="hidden sm:inline-flex btn-ghost">
              <T k="nav.signin" />
            </Link>
            <Link to="/login" className="hidden sm:inline-flex btn-primary">
              <T k="nav.start" />
              <ArrowRight size={15} />
            </Link>
            <button
              onClick={() => setOpen((o) => !o)}
              className="lg:hidden w-9 h-9 grid place-items-center text-[var(--ink-2)]"
              aria-label="Open menu"
            >
              {open ? <X size={18} /> : <Menu size={18} />}
            </button>
          </div>
        </div>

        {/* Mobile nav drawer */}
        {open && (
          <div className="lg:hidden border-t-[0.5px] border-[var(--line)] bg-[var(--surface)]">
            <nav className="max-w-[1240px] mx-auto px-6 py-4 flex flex-col gap-1">
              {NAV.map((item) => (
                <Link
                  key={item.to}
                  to={item.to}
                  className="py-2.5 text-[14px] text-[var(--ink-2)] hover:text-[var(--ink)]"
                >
                  <T k={item.key} />
                </Link>
              ))}
              <Link to="/login" className="py-2.5 text-[14px] text-[var(--ink-2)]">
                <T k="nav.signin" />
              </Link>
            </nav>
          </div>
        )}
      </header>

      <main>{children}</main>
    </div>
  );
}