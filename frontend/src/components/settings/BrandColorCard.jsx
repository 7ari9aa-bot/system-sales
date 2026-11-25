import React from "react";
import { Palette } from "lucide-react";
import { useT } from "@/lib/i18n";
import { api } from "@/lib/api";
import { activeTenantId } from "@/lib/activeTenant";
import { SettingCard } from "@/components/settings/SettingsShell";
import { Input } from "@/components/ui/input";

/** Brand color picker — reads and writes ``organization.brand_color``.
 *
 * The color is stored as a HEX string (#RRGGBB). An empty value means no
 * custom brand color (the default theme applies). The color is also applied
 * as a CSS custom property on the document root so the UI can adapt.
 */
export default function BrandColorCard() {
  const t = useT();
  const tenantId = activeTenantId();
  const [color, setColor] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState("");
  const [loaded, setLoaded] = React.useState(false);

  React.useEffect(() => {
    if (!tenantId) return undefined;
    let alive = true;
    api("/settings/effective/organization.brand_color")
      .then((res) => {
        if (alive) {
          setColor(res?.value || "");
          setLoaded(true);
        }
      })
      .catch(() => {
        if (alive) setLoaded(true);
      });
    return () => {
      alive = false;
    };
  }, [tenantId]);

  // Apply the brand color as a CSS variable whenever it changes.
  React.useEffect(() => {
    if (color && /^#[0-9A-Fa-f]{6}$/.test(color)) {
      document.documentElement.style.setProperty("--brand-color", color);
    } else {
      document.documentElement.style.removeProperty("--brand-color");
    }
  }, [color]);

  async function handleSave() {
    if (!tenantId) return;
    const trimmed = color.trim();
    if (trimmed && !/^#[0-9A-Fa-f]{6}$/.test(trimmed)) {
      setError(t("settings.brandColor.invalid"));
      return;
    }
    setSaving(true);
    setError("");
    try {
      await api("/settings/organization.brand_color", {
        method: "PUT",
        body: JSON.stringify({ value: trimmed || null }),
      });
    } catch (err) {
      setError(err?.message || "Error");
    } finally {
      setSaving(false);
    }
  }

  if (!loaded) return null;

  return (
    <SettingCard icon={Palette} title={t("settings.brandColor.title")} description={t("settings.brandColor.desc")}>
      <div className="flex items-center gap-3">
        <Input
          type="color"
          value={color || "#2563EB"}
          onChange={(e) => setColor(e.target.value)}
          onBlur={handleSave}
          disabled={saving}
          className="h-10 w-14 cursor-pointer p-1 border border-border rounded-lg"
        />
        <Input
          type="text"
          value={color}
          onChange={(e) => setColor(e.target.value)}
          onBlur={handleSave}
          disabled={saving}
          placeholder="#2563EB"
          className="flex-1 max-w-[160px]"
          maxLength={7}
        />
        {error && <span className="text-xs text-destructive">{error}</span>}
      </div>
    </SettingCard>
  );
}
