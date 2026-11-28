import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { StatusPanel, unsavedNote } from "./TaxSettings";
import { readiness } from "@/applications/apparel/api/taxSettings";

const GOOD = { "business.legal_name": "س", "business.tax_id": "123456789", "einvoice.eta_enabled": true, "einvoice.settings_confirmed": true, "einvoice.branch_code": "0", "einvoice.activity_code": "4771", "einvoice.branch_governate": "ق", "einvoice.branch_region_city": "م", "einvoice.branch_street": "ش", "einvoice.branch_building_number": "5" };
const draw = (v) => renderToStaticMarkup(<StatusPanel status={readiness(v)} enabled={v["einvoice.eta_enabled"]} confirmed={v["einvoice.settings_confirmed"]} />);

describe("the status panel", () => {
  it("says it is running when it is", () => {
    const h = draw(GOOD);
    expect(h).toContain('data-state="running"');
    expect(h).toContain("الإيصال الإلكتروني شغال");
  });

  it("says it is off, calmly, with nothing to fix", () => {
    const h = draw({ ...GOOD, "einvoice.eta_enabled": false });
    expect(h).toContain('data-state="off"');
    expect(h).toContain("مقفول");
    expect(h).not.toContain("واقف");
  });

  it("switched on but unconfirmed: says STOPPED and tells the merchant to confirm", () => {
    const h = draw({ ...GOOD, "einvoice.settings_confirmed": false });
    expect(h).toContain('data-state="blocked"');
    expect(h).toContain("متفعّل لكنه واقف");
    expect(h).toContain("أكّدها");
  });

  it("names every missing piece of data", () => {
    const h = draw({ ...GOOD, "business.tax_id": "123", "einvoice.branch_street": "" });
    expect(h).toContain("الرقم الضريبي (9 أرقام)");
    expect(h).toContain("الشارع");
  });

  it("always shows both switches, so the merchant can act from the panel", () => {
    const h = draw(GOOD);
    expect(h).toContain('aria-label="تفعيل الإيصال الإلكتروني"');
    expect(h).toContain("أكّدت إعدادات الأسعار والضريبة والدفع");
  });

  it("warns that the starting values are suggestions", () => {
    expect(draw(GOOD)).toContain("اقتراحات");
  });
});

describe("unsaved changes", () => {
  it("say plainly that the status above is the SAVED one, so a green panel never promises what is not saved", () => {
    expect(unsavedNote(3)).toContain("3");
    expect(unsavedNote(3)).toContain("لم يُحفظ بعد");
  });

  it("show nothing when there is nothing unsaved", () => {
    expect(unsavedNote(0)).toBeNull();
  });

  it("the panel shows that note when it is given one", () => {
    const h = renderToStaticMarkup(<StatusPanel status={readiness(GOOD)} enabled confirmed note={unsavedNote(2)} />);
    expect(h).toContain("لم يُحفظ بعد");
    expect(h).toContain('data-testid="tax-unsaved"');
  });

  it("no note, no banner", () => {
    expect(draw(GOOD)).not.toContain("tax-unsaved");
  });
});
