import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// The setup screens are JSX the test setup cannot render, so the links that matter are guarded at
// the source: a broken one either traps a user in a dialog, asks a cashier, sends a sector the
// platform does not serve, or applies the preset without the owner's yes.
// The application tree moved under src/applications/apparel, one level deeper than
// it used to sit. A helper path is written either from the application root or
// from src, so resolve against both instead of guessing which one this file meant.
const read = (rel) => {
  for (const base of ["../../../../", "../../../", "../../"]) {
    try {
      return readFileSync(new URL(base + rel, import.meta.url), "utf8");
    } catch {
      // try the next base
    }
  }
  throw new Error(`cannot resolve ${rel}`);
};
const dialog = read("apparel/components/setup/ActivitySetupDialog.jsx");
const gate = read("apparel/components/setup/ActivitySetupGate.jsx");
const reopen = read("apparel/components/setup/ReopenActivitySetup.jsx");
const hooks = read("apparel/api/useActivitySetup.js");
const api = read("apparel/api/catalogApi.js");
const layout = read("components/dashboard/DashboardLayout.jsx");
const profile = read("apparel/components/settings/ShopProfileForm.jsx");
const register = read("pages/Register.jsx");

describe("the gate", () => {
  it("is mounted in the dashboard layout, so it covers the dashboard and the till", () => {
    expect(layout).toMatch(/import ActivitySetupGate from "@\/applications\/apparel\/components\/setup\/ActivitySetupGate"/);
    expect(layout).toMatch(/<ActivitySetupGate \/>/);
  });
  it("renders nothing unless the server says this owner is due, and nothing once closed", () => {
    expect(gate).toMatch(/if \(!setup\.needsSetup \|\| closed\) return null;/);
  });
  it("reads the answer through the safe hook, never straight from the api", () => {
    expect(gate).toMatch(/useActivitySetup\(\)/);
    expect(gate).not.toMatch(/catalogApi/);
  });
  it("finishing goes to the till", () => {
    expect(gate).toMatch(/navigate\(appPath\("\/pos"\)\)/);
  });
});

describe("the dialog never traps anyone", () => {
  it("closing it by any route is a skip", () => {
    expect(dialog).toMatch(/onOpenChange=\{\(next\) => \{ if \(!next\) \(step === 3 \? onDone\?\.\(\) : doSkip\(\)\); \}\}/);
  });
  it("the skip button is on both asking steps", () => {
    expect(dialog.match(/تخطّي دلوقتي/g)?.length).toBe(2);
  });
  it("even a failed skip closes it, so a broken server never keeps it on screen", () => {
    expect(dialog).toMatch(/onSuccess: \(\) => onClose\?\.\(\), onError: \(\) => onClose\?\.\(\)/);
  });
  it("buttons are held while a request is in flight, so a double tap sends once", () => {
    expect(dialog).toMatch(/const busy = complete\.isPending \|\| skip\.isPending;/);
    expect(dialog).toMatch(/if \(!body \|\| busy\) return;/);
  });
});

describe("only what the server serves can be sent", () => {
  it("a card is picked only through isSelectable and the body only through completeBody", () => {
    expect(dialog).toMatch(/if \(!isSelectable\(setup, id\)\) return;/);
    expect(dialog).toMatch(/const body = completeBody\(setup, choice, applyPreset\);/);
  });
  it("a coming-soon card is a disabled button", () => {
    expect(dialog).toMatch(/aria-disabled=\{c\.disabled\}/);
    // the real attribute, not just the aria one that happens to contain the same text
    expect(dialog).toMatch(/^\s+disabled=\{c\.disabled\}$/m);
  });
  it("the preset box starts on and is sent only if left on", () => {
    expect(dialog).toMatch(/useState\(true\)/);
    expect(dialog).toMatch(/onCheckedChange=\{\(v\) => setApplyPreset\(v === true\)\}/);
  });
  it("the summary counts what the server will set instead of a number written here", () => {
    expect(dialog).toMatch(/presetCount\(setup, choice\)/);
  });
});

describe("answering refreshes what the shop shows", () => {
  it("the setup, the size and colour lists and the stock screens are all refetched", () => {
    expect(hooks).toMatch(/invalidateQueries\(\{ queryKey: ACTIVITY_SETUP_KEY \}\)/);
    expect(hooks).toMatch(/invalidateQueries\(\{ queryKey: SHOP_OPTIONS_KEY \}\)/);
    expect(hooks).toMatch(/invalidateQueries\(\{ queryKey: STOCK_SCREENS_KEY \}\)/);
  });
  it("a failed read is never retried into a trap and reads as not asking", () => {
    expect(hooks).toMatch(/retry: 0/);
    expect(hooks).toMatch(/setup: normaliseSetup\(q\.data\)/);
  });
});

describe("the four calls hit the routes the server has", () => {
  it("get, complete, skip and reopen", () => {
    expect(api).toMatch(/activitySetup: \(\) => api\("\/activity-setup"\)/);
    expect(api).toMatch(/completeActivitySetup: \(body\) => post\("\/activity-setup\/complete", body\)/);
    expect(api).toMatch(/skipActivitySetup: \(\) => post\("\/activity-setup\/skip", \{\}\)/);
    expect(api).toMatch(/reopenActivitySetup: \(\) => post\("\/activity-setup\/reopen", \{\}\)/);
  });
});

describe("reopening from settings", () => {
  it("is in the shop-details screen and shows only after the setup was answered", () => {
    expect(profile).toMatch(/<ReopenActivitySetup \/>/);
    expect(reopen).toMatch(/if \(!canReopen\(raw\)\) return null;/);
  });
  it("tells the owner their own settings are safe", () => {
    expect(reopen).toMatch(/مش هيغيّر أي إعداد انت ظبطته/);
  });
});

describe("signup", () => {
  it("builds its body through registerPayload, so the old two-field signup is unchanged", () => {
    expect(register).toMatch(/register\(registerPayload\(\{ email, password, captchaToken, shopName, country, terms \}\)\)/);
  });
  it("the three new fields are optional: the submit is not held by them", () => {
    expect(register).not.toMatch(/disabled=\{[^}]*(shopName|terms)/);
    expect(register).toMatch(/useState\("EG"\)/);
    expect(register).toMatch(/useState\(false\)/);
  });
  it("offers only the served markets", () => {
    expect(register).toMatch(/COUNTRIES\.map/);
  });
});
