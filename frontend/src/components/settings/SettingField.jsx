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
import { useSettingsAccess } from "@/components/settings/SettingsAccessContext";

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

/**
 * Where a value came from, in the reader's words.
 *
 * A settings screen that shows a number without saying whose number it is invites the wrong
 * conclusion: a branch reading the workspace's inherited discount believes it chose it, and
 * the next person "fixes" a value nobody broke. `is_default` is its own case — no one decided.
 */
export function sourceLabel(source, isAr) {
  if (!source) return "";
  if (source.isDefault) return isAr ? "القيمة الافتراضية" : "Default";
  const scope = isAr ? SCOPE_LABELS_AR[source.scope] || source.scope : source.scope;
  if (source.isInherited) return isAr ? `موروثة من ${scope}` : `From ${scope}`;
  return isAr ? `محدَّدة هنا (${scope})` : `Set here (${scope})`;
}

const SCOPE_LABELS_AR = {
  tenant: "النشاط",
  workspace: "المساحة",
  branch: "الفرع",
  warehouse: "المخزن",
  pos_profile: "ملف الكاشير",
  register: "الدرج",
  channel: "القناة",
  user: "المستخدم",
};

export function SettingField({ defn, value, onChange, isAr, source }) {
  const label = isAr ? defn.label_ar || defn.key : defn.label_en || defn.key;
  const desc = isAr ? defn.description_ar : defn.description_en;
  // A key the engine does not enforce is a promise nothing keeps: the row still says what it is
  // (and that it is not active), but it must not offer a control that looks like it saves.
  //
  // The same is true of a key this member may not WRITE. The registry says which permission
  // owns each key (`settings:write` for shop settings, `settings:branch_write` for a branch's
  // own), and a manager holds `settings:read` without `settings:write`: the field looked
  // editable, the value was typed, and the save came back 403. Asking the grant first makes
  // the control honest — it shows the value and says it is read-only, and where it is.
  const { can } = useSettingsAccess();
  const permission = defn.permission || "settings:write";
  const mayWrite = can(permission);
  const readOnly = mayWrite === false;
  const inert = defn.enforced === false || readOnly;

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
            title={isAr ? "يتطلب صلاحية قراءة القيم الحساسة" : "Needs the sensitive-read permission"}
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
          aria-label={label}
          checked={Boolean(value)}
          disabled={inert}
          onCheckedChange={(checked) => onChange(defn.key, checked)}
        />
      );
    }

    if (defn.type === "enum" && defn.allowed_values) {
      return (
        <Select value={String(value ?? "")} onValueChange={(v) => onChange(defn.key, v)}>
          <SelectTrigger className="w-[200px]" aria-label={label} disabled={inert}>
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
          disabled={inert}
          aria-label={label}
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
          disabled={inert}
          aria-label={label}
          value={Array.isArray(value) ? value.join(", ") : String(value ?? "")}
          onChange={(e) =>
            onChange(defn.key, [
              ...new Set(
                e.target.value
                  .split(",")
                  .map((s) => s.trim())
                  .filter(Boolean),
              ),
            ])
          }
        />
      );
    }

    // string
    return (
      <Input
        className="w-[260px]"
        disabled={inert}
        aria-label={label}
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
        {source && (
          <Badge
            tone={source.isDefault ? "muted" : source.isInherited ? "warning" : "success"}
            className="shrink-0"
            data-testid="setting-source"
            title={
              source.isDefault
                ? isAr
                  ? "محدش عدّلها، فهي قيمة النظام الافتراضية"
                  : "Nobody set it, so this is the system default"
                : source.isInherited
                  ? isAr
                    ? `موروثة من ${source.scope}`
                    : `Inherited from the ${source.scope}`
                  : isAr
                    ? `محدَّدة على مستوى ${source.scope}`
                    : `Set at ${source.scope} level`
            }
          >
            {sourceLabel(source, isAr)}
          </Badge>
        )}
        {readOnly && (
          <Badge tone="muted" className="shrink-0" data-testid="setting-read-only">
            <Lock className="mr-1 h-3 w-3" />
            {isAr ? "قراءة فقط" : "Read-only"}
          </Badge>
        )}
        {defn.apply_mode === "approval_required" && !readOnly && (
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
