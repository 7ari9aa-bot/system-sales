/**
 * Which optional stock screens the shop shows (backend: GET /inventory/screens, the owner's three
 * `inventory.show_*` switches). They only HIDE: no screen, tab or route is removed, so switching one
 * back on brings it back as it was.
 *
 * Until the answer arrives, or if it cannot be read, everything is shown: that is what the shop had
 * before the switches existed, and a failed read must never take a screen away from its owner.
 */

export const ALL_SHOWN = Object.freeze({
  warehouse_transfers: true,
  channel_allocation: true,
  units_of_measure: true,
});

/** The screen each stock-workspace tab belongs to. A tab not listed here is always shown. */
export const TAB_SCREEN = Object.freeze({
  transfers: "warehouse_transfers",
  allocations: "channel_allocation",
});

/** The server's answer as a full map. Only a real `false` hides; anything else (missing, odd) shows. */
export function normaliseScreens(raw) {
  const out = { ...ALL_SHOWN };
  if (raw && typeof raw === "object") {
    for (const name of Object.keys(ALL_SHOWN)) if (raw[name] === false) out[name] = false;
  }
  return out;
}

/** The tabs this shop shows, in their original order. */
export function visibleTabs(tabs, screens) {
  const shown = normaliseScreens(screens);
  return tabs.filter((tab) => {
    const screen = TAB_SCREEN[tab.id];
    return screen === undefined || shown[screen];
  });
}

/** The tab to be on: the current one if it is still shown, otherwise the first that is. */
export function activeOrFirst(activeId, tabs) {
  if (tabs.some((t) => t.id === activeId)) return activeId;
  return tabs[0]?.id ?? activeId;
}
