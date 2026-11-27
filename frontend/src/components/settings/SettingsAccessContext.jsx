import React from "react";
import { loadSettingsAccess, canSeeSection, canWriteSettings } from "@/lib/settingsAccess";

/**
 * The Center's access answer, provided ONCE and read by the nav, the route guard and every
 * field.
 *
 * Three places used to decide separately (the layout by role name, the developer gate by role
 * name, and the field not at all), which is how a manager ended up able to edit a value the
 * save refuses. One provider, one rule, and `useSettingsAccess` works outside the provider too
 * (a page rendered in a test, the older UnifiedSettings screen) by loading the answer itself.
 */
export const SettingsAccessContext = React.createContext(null);

export function SettingsAccessProvider({ children }) {
  const [access, setAccess] = React.useState(null);
  const [failed, setFailed] = React.useState(false);

  React.useEffect(() => {
    let alive = true;
    loadSettingsAccess()
      .then((value) => {
        if (alive) setAccess(value);
      })
      .catch(() => {
        if (alive) setFailed(true);
      });
    return () => {
      alive = false;
    };
  }, []);

  const value = React.useMemo(
    () => ({
      access,
      loading: !access && !failed,
      // A failed read is not a refusal: the server still answers each request on its own, so
      // the screens stay usable and the 403s do the deciding.
      failed,
      canSee: (section) => canSeeSection(access, section),
      canWrite: canWriteSettings(access),
      can: (permission) => (access ? access.permissions.has(permission) : null),
    }),
    [access, failed]
  );

  return (
    <SettingsAccessContext.Provider value={value}>{children}</SettingsAccessContext.Provider>
  );
}

export function useSettingsAccess() {
  const provided = React.useContext(SettingsAccessContext);
  const [own, setOwn] = React.useState(null);
  const [failed, setFailed] = React.useState(false);
  const needsOwn = !provided;

  React.useEffect(() => {
    if (!needsOwn) return undefined;
    let alive = true;
    loadSettingsAccess()
      .then((value) => {
        if (alive) setOwn(value);
      })
      .catch(() => {
        if (alive) setFailed(true);
      });
    return () => {
      alive = false;
    };
  }, [needsOwn]);

  if (provided) return provided;
  return {
    access: own,
    loading: !own && !failed,
    failed,
    canSee: (section) => canSeeSection(own, section),
    canWrite: canWriteSettings(own),
    can: (permission) => (own ? own.permissions.has(permission) : null),
  };
}
