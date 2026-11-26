import React, { useEffect, useMemo, useState } from "react";
import { SCOPE_OPTIONS } from "@/components/settings/useSettings";
import { loadScopeOptions } from "@/components/settings/scopeOptions";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

/**
 * Scope selector for the unified settings page.
 *
 * The scope entity is chosen by name from the tenant's own rows — branch, warehouse, POS
 * profile, register, channel, user — and the id comes from that choice. The old free-text
 * UUID box meant the owner had to find an id the settings page never showed, so every
 * setting in practice lived at the tenant level.
 */
export default function ScopeSelector({ scope, scopeId, onScopeChange, onScopeIdChange, isAr }) {
  const [options, setOptions] = useState([]);
  const [state, setState] = useState({ loading: false, error: "" });

  useEffect(() => {
    let alive = true;
    if (scope === "tenant") {
      setOptions([]);
      setState({ loading: false, error: "" });
      return () => {
        alive = false;
      };
    }
    setState({ loading: true, error: "" });
    loadScopeOptions(scope)
      .then((rows) => {
        if (!alive) return;
        setOptions(rows);
        setState({ loading: false, error: "" });
      })
      .catch((error) => {
        if (!alive) return;
        setOptions([]);
        setState({ loading: false, error: error?.message || "" });
      });
    return () => {
      alive = false;
    };
  }, [scope]);

  const selected = useMemo(
    () => options.find((option) => option.id === scopeId) || null,
    [options, scopeId],
  );

  const scopeLabel = (opt) => (isAr ? opt.labelAr : opt.labelEn);

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select
        value={scope}
        onValueChange={(next) => {
          onScopeChange(next);
          // The previous id belongs to another scope: keeping it would send a branch id as
          // a register scope and the server would answer "not found".
          onScopeIdChange(null);
        }}
      >
        <SelectTrigger className="w-[160px]">
          <SelectValue placeholder={isAr ? "اختر النطاق…" : "Select scope…"} />
        </SelectTrigger>
        <SelectContent>
          {SCOPE_OPTIONS.map((opt) => (
            <SelectItem key={opt.value} value={opt.value}>
              {scopeLabel(opt)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {scope !== "tenant" && (
        <div className="flex items-center gap-2">
          <Select
            value={scopeId || ""}
            onValueChange={(next) => onScopeIdChange(next || null)}
            disabled={state.loading || options.length === 0}
          >
            <SelectTrigger className="min-w-[200px]">
              <SelectValue
                placeholder={
                  state.loading
                    ? isAr
                      ? "جارٍ التحميل…"
                      : "Loading…"
                    : options.length === 0
                      ? isAr
                        ? "لا يوجد شيء للاختيار"
                        : "Nothing to pick"
                      : isAr
                        ? "اختر بالاسم…"
                        : "Pick by name…"
                }
              />
            </SelectTrigger>
            <SelectContent>
              {options.map((option) => (
                <SelectItem key={option.id} value={option.id} disabled={option.disabled}>
                  {option.name}
                  {option.hint ? (
                    <span className="ms-2 text-[11px] text-muted-foreground">{option.hint}</span>
                  ) : null}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {selected ? (
            <span className="text-[11px] text-muted-foreground">
              {isAr ? "المعرّف" : "ID"}: {selected.id.slice(0, 8)}
            </span>
          ) : null}
          {state.error ? (
            <span className="text-[11px] text-destructive">
              {isAr ? "تعذّر تحميل القائمة" : "Could not load the list"}
            </span>
          ) : null}
        </div>
      )}
    </div>
  );
}
