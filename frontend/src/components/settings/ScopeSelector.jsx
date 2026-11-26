import React from "react";
import { SCOPE_OPTIONS } from "@/components/settings/useSettings";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

/**
 * Scope selector for the unified settings page.
 * Lets the user pick which scope to view/edit settings at (tenant, branch,
 * pos_profile, register, …) instead of the old hardcoded "tenant".
 *
 * The scope_id field appears when a non-tenant scope is selected so the
 * caller can provide the specific branch/register id.
 */
export default function ScopeSelector({ scope, scopeId, onScopeChange, onScopeIdChange, isAr }) {
  return (
    <div className="flex items-center gap-2">
      <Select value={scope} onValueChange={onScopeChange}>
        <SelectTrigger className="w-[160px]">
          <SelectValue placeholder={isAr ? "اختر النطاق…" : "Select scope…"} />
        </SelectTrigger>
        <SelectContent>
          {SCOPE_OPTIONS.map((opt) => (
            <SelectItem key={opt.value} value={opt.value}>
              {isAr ? opt.labelAr : opt.labelEn}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {scope !== "tenant" && (
        <input
          type="text"
          className="h-9 rounded-md border border-input bg-background px-3 text-[13px] outline-none focus:ring-1 focus:ring-ring"
          placeholder={isAr ? "معرّف النطاق (UUID)" : "Scope ID (UUID)"}
          value={scopeId || ""}
          onChange={(e) => onScopeIdChange(e.target.value || null)}
        />
      )}
    </div>
  );
}
