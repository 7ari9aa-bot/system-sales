import React from "react";
import { Loader2, MonitorSmartphone, Sparkles } from "lucide-react";
import { useT, useI18n } from "@/lib/i18n";
import { useTheme } from "@/lib/themeContext";
import { api } from "@/lib/api";
import SettingsShell, { SettingCard, SettingRow } from "@/components/settings/SettingsShell";

/** How the product looks and reads to this person, wherever they sign in.

 * These five choices used to live in the browser: a localStorage key for the theme
 * and one for the language, which meant the same account on the till and on a phone
 * could disagree, and clearing site data silently reset them. They are the person's
 * own facts, not the shop's, so they now live on the account — and every control on
 * this page saves itself, because a preferences screen that needs a "save" button is
 * a screen people leave half-answered.
 */
const LOCALES = [
  { value: "ar", key: "prefs.language.ar" },
  { value: "en", key: "prefs.language.en" },
];
const THEMES = [
  { value: "system", key: "prefs.theme.system" },
  { value: "light", key: "prefs.theme.light" },
  { value: "dark", key: "prefs.theme.dark" },
];
const DATE_FORMATS = [
  { value: "dmy", key: "prefs.date.dmy" },
  { value: "mdy", key: "prefs.date.mdy" },
  { value: "ymd", key: "prefs.date.ymd" },
];
const PAGES = [
  { value: "/dashboard", key: "prefs.page.dashboard" },
  { value: "/inbox", key: "prefs.page.inbox" },
  { value: "/cashier", key: "prefs.page.cashier" },
  { value: "/customers", key: "prefs.page.customers" },
  { value: "/settings", key: "prefs.page.settings" },
];

/** The zones the runtime can actually resolve, in the order a person scans them. */
function timezoneOptions() {
  const supported =
    typeof Intl !== "undefined" && typeof Intl.supportedValuesOf === "function"
      ? Intl.supportedValuesOf("timeZone")
      : ["Africa/Cairo", "Asia/Riyadh", "Asia/Dubai", "Europe/London", "UTC"];
  return Array.from(new Set(["Africa/Cairo", ...supported]));
}

/** A real sample of the chosen shape, so the choice is not an abstraction. */
function sampleDate(format, lang) {
  const locale = lang === "ar" ? "ar-EG" : "en-GB";
  const options =
    format === "ymd"
      ? { year: "numeric", month: "2-digit", day: "2-digit" }
      : format === "mdy"
        ? { month: "2-digit", day: "2-digit", year: "numeric" }
        : { day: "2-digit", month: "2-digit", year: "numeric" };
  try {
    return new Intl.DateTimeFormat(locale, options).format(new Date(2026, 10, 26));
  } catch {
    return "";
  }
}

function Choice({ options, value, onChange, label, testid, disabled }) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className="inline-flex rounded-md border border-border p-0.5"
      data-testid={testid}
    >
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={value === option.value}
          disabled={disabled}
          onClick={() => onChange(option.value)}
          className={`h-8 rounded px-3 text-[13px] font-medium transition-colors disabled:opacity-50 ${
            value === option.value
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export default function PreferencesSettings() {
  const t = useT();
  const { lang, setLang } = useI18n();
  const { theme, setTheme } = useTheme();

  const [prefs, setPrefs] = React.useState(null);
  const [busy, setBusy] = React.useState("");
  const [error, setError] = React.useState("");
  const [notice, setNotice] = React.useState("");
  const zones = React.useMemo(timezoneOptions, []);

  React.useEffect(() => {
    let alive = true;
    api("/users/me/preferences")
      .then((data) => {
        if (alive) setPrefs(data);
      })
      .catch(() => {
        if (alive) setError(t("prefs.loadFailed"));
      });
    return () => {
      alive = false;
    };
  }, [t]);

  async function save(field, value, apply) {
    if (busy) return;
    setBusy(field);
    setError("");
    setNotice("");
    try {
      const next = await api("/users/me/preferences", {
        method: "PATCH",
        body: { [field]: value },
      });
      setPrefs(next);
      // the server answered with the whole set; the shell follows it immediately so
      // the person sees the change they just made, not on the next page load
      if (apply) apply(value);
      setNotice(t("prefs.saved"));
    } catch (failure) {
      setError(failure?.message || t("prefs.saveFailed"));
    } finally {
      setBusy("");
    }
  }

  const current = prefs || {};
  const zone = current.timezone || current.effective_timezone || "Africa/Cairo";

  return (
    <SettingsShell title={t("settings.preferences")} subtitle={t("settings.preferences.desc")}>
      <div className="grid grid-cols-1 items-start gap-x-10 gap-y-6 xl:grid-cols-2">
        <SettingCard title={t("prefs.appearance.title")} desc={t("prefs.appearance.desc")}>
          <SettingRow label={t("prefs.language")} desc={t("prefs.language.desc")}>
            <Choice
              label={t("prefs.language")}
              testid="prefs-language"
              value={current.locale || lang}
              disabled={Boolean(busy) || prefs == null}
              onChange={(value) => save("locale", value, setLang)}
              options={LOCALES.map((item) => ({ value: item.value, label: t(item.key) }))}
            />
          </SettingRow>
          <SettingRow label={t("prefs.theme")} desc={t("prefs.theme.desc")} last>
            <Choice
              label={t("prefs.theme")}
              testid="prefs-theme"
              value={current.theme || theme}
              disabled={Boolean(busy) || prefs == null}
              onChange={(value) => save("theme", value, setTheme)}
              options={THEMES.map((item) => ({ value: item.value, label: t(item.key) }))}
            />
          </SettingRow>
        </SettingCard>

        <SettingCard title={t("prefs.region.title")} desc={t("prefs.region.desc")}>
          <SettingRow label={t("prefs.timezone")} desc={t("prefs.timezone.desc")}>
            <div className="flex items-center gap-2">
              <select
                value={zone}
                disabled={Boolean(busy) || prefs == null}
                onChange={(event) => save("timezone", event.target.value)}
                data-testid="prefs-timezone"
                aria-label={t("prefs.timezone")}
                dir="ltr"
                className="h-9 max-w-[16rem] rounded-md border border-border bg-card px-2 text-[12.5px]"
              >
                {zones.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
              {!current.timezone && (
                <span className="text-[11.5px] text-muted-foreground">{t("prefs.timezone.inherited")}</span>
              )}
            </div>
          </SettingRow>
          <SettingRow
            label={t("prefs.dateFormat")}
            desc={t("prefs.dateFormat.desc", { sample: sampleDate(current.date_format || "dmy", lang) })}
          >
            <Choice
              label={t("prefs.dateFormat")}
              testid="prefs-date-format"
              value={current.date_format || "dmy"}
              disabled={Boolean(busy) || prefs == null}
              onChange={(value) => save("date_format", value)}
              options={DATE_FORMATS.map((item) => ({ value: item.value, label: t(item.key) }))}
            />
          </SettingRow>
          <SettingRow label={t("prefs.defaultPage")} desc={t("prefs.defaultPage.desc")} last>
            <select
              value={current.default_page || "/dashboard"}
              disabled={Boolean(busy) || prefs == null}
              onChange={(event) => save("default_page", event.target.value)}
              data-testid="prefs-default-page"
              aria-label={t("prefs.defaultPage")}
              className="h-9 rounded-md border border-border bg-card px-2 text-[12.5px]"
            >
              {PAGES.map((page) => (
                <option key={page.value} value={page.value}>
                  {t(page.key)}
                </option>
              ))}
            </select>
          </SettingRow>
        </SettingCard>
      </div>

      <div className="mt-6 space-y-2">
        {busy && (
          <p className="inline-flex items-center gap-2 text-[12.5px] text-muted-foreground" data-testid="prefs-saving">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            {t("prefs.saving")}
          </p>
        )}
        {error && (
          <div role="alert" className="rounded-lg bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
            {error}
          </div>
        )}
        {notice && !error && (
          <div
            role="status"
            className="inline-flex items-center gap-2 rounded-lg bg-success/10 px-3 py-2 text-[12px] text-foreground"
            data-testid="prefs-notice"
          >
            <Sparkles className="h-3.5 w-3.5" />
            {notice}
          </div>
        )}
        <p className="flex items-start gap-2 text-[11.5px] leading-relaxed text-muted-foreground">
          <MonitorSmartphone className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {t("prefs.followsAccount")}
        </p>
      </div>
    </SettingsShell>
  );
}
