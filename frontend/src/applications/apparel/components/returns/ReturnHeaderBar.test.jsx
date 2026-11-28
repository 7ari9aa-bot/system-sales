import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import ReturnHeaderBar from "./ReturnHeaderBar";

const html = (props) => renderToStaticMarkup(<MemoryRouter><ReturnHeaderBar employee="سارة" {...props} /></MemoryRouter>);

describe("ReturnHeaderBar", () => {
  it("names the return screen by default", () => {
    const h = html({ number: "R-1" });
    expect(h).toContain("تسجيل مرتجع");
    expect(h).toContain("رقم المرتجع");
  });
  it("names the exchange screen as an exchange, not a return", () => {
    const h = html({ title: "تسجيل استبدال", numberLabel: "رقم الاستبدال", number: "X-1" });
    expect(h).toContain("تسجيل استبدال");
    expect(h).toContain("رقم الاستبدال");
    expect(h).not.toContain("تسجيل مرتجع");
    expect(h).not.toContain("رقم المرتجع");
  });
});
