/** The one control renderer for every registry-driven setting.
 *
 * Extracted from UnifiedSettings so a Settings Center page can render a single section's keys
 * with exactly the same behaviour — masked values never reach a control, approval-required keys
 * say so, and a key nothing reads is marked "not active" instead of implying it works.
 */
import React from "react";
import { ShieldAlert, Lock } from "lucide-react";
import { SettingRow } from "@/components/settings/SettingsShell";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/dashboard/ui";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";

/** What the server sends instead of a value the caller may not read (router MASKED_VALUE). */
export const MASKED_VALUE = "******";

/**
 * Whether this value is a redaction rather than a real one.
 *
 * The mask is the string "******", and a string is truthy: rendered into a switch it showed
 * a sensitive setting as ON, and into a number box it was an invalid number the user could
 * "edit". A masked value must never reach a control, so every field checks this first.
 */
export function isProtectedValue(value) {
  return value === MASKED_VALUE;
}

export function SettingField({ defn, value, onChange, isAr }) {
  const label = isAr ? defn.label_ar || defn.key : defn.label_en || defn.key;
  const desc = isAr ? defn.description_ar : defn.description_en;

  const renderControl = () => {
    if (isProtectedValue(value)) {
      return (
        <div className="flex items-center gap-2" data-testid="setting-protected">
          <Input
            disabled
            readOnly
            value="••••••"
            className="w-[160px] text-muted-foreground"
            aria-label={isAr ? "قيمة محمية" : "Protected value"}
            title={isAr ? "محتاج صلاحية قراءة القيم الحساسة" : "Needs the sensitive-read permission"}
          />
          <Badge tone="muted" className="shrink-0">
            <Lock className="mr-1 h-3 w-3" />
            {isAr ? "محمي" : "Protected"}
          </Badge>
        </div>
      );
    }

    if (defn.type === "bool") {
      return (
        <Switch
          checked={Boolean(value)}
          onCheckedChange={(checked) => onChange(defn.key, checked)}
        />
      );
    }

    if (defn.type === "enum" && defn.allowed_values) {
      return (
        <Select value={String(value ?? "")} onValueChange={(v) => onChange(defn.key, v)}>
          <SelectTrigger className="w-[200px]">
            <SelectValue placeholder={isAr ? "اختر…" : "Select…"} />
          </SelectTrigger>
          <SelectContent>
            {defn.allowed_values.map((v) => (
              <SelectItem key={v} value={v}>{v}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      );
    }

    if (defn.type === "number") {
      return (
        <Input
          type="number"
          className="w-[140px]"
          value={value ?? ""}
          min={defn.min_value ?? undefined}
          max={defn.max_value ?? undefined}
          onChange={(e) => onChange(defn.key, e.target.value === "" ? null : Number(e.target.value))}
        />
      );
    }

    if (defn.type === "list") {
      return (
        <Input
          className="w-[260px]"
          value={Array.isArray(value) ? value.join(", ") : String(value ?? "")}
          onChange={(e) => onChange(defn.key, e.target.value.split(",").map((s) => s.trim()).filter(Boolean))}
        />
      );
    }

    // string
    return (
      <Input
        className="w-[260px]"
        value={String(value ?? "")}
        maxLength={defn.max_length ?? undefined}
        onChange={(e) => onChange(defn.key, e.target.value)}
      />
    );
  };

  return (
    <SettingRow label={label} desc={desc} stretch={defn.type === "list" || defn.type === "string"}>
      <div className="flex items-center gap-2">
        {renderControl()}
        {defn.apply_mode === "approval_required" && (
          <Badge tone="warning" className="shrink-0">
            <ShieldAlert className="mr-1 h-3 w-3" />
            {isAr ? "تتطلب موافقة" : "Approval"}
          </Badge>
        )}
        {defn.enforced ? (
          <Badge tone="success">{isAr ? "مفعّل" : "Active"}</Badge>
        ) : (
          <Badge tone="muted">{isAr ? "غير مفعّل" : "Not active"}</Badge>
        )}
      </div>
    </SettingRow>
  );
}
