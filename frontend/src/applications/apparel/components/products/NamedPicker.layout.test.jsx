import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import NamedPicker from "./NamedPicker";

const html = () =>
  renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <NamedPicker items={[]} value="" onChange={() => {}} onCreate={async () => ({})} noneLabel="بدون فئة" addLabel="+ فئة جديدة" placeholder="اسم الفئة" />
    </QueryClientProvider>,
  );

// In a narrow form column the "+ new" button used to push out of its column and sit on top of the next field.
// The row wraps, and the list takes the free width, so the button drops below instead of overlapping.
describe("NamedPicker row stays inside its column", () => {
  it("wraps its row", () => {
    expect(html()).toMatch(/<div class="flex flex-wrap gap-2">/);
  });
  it("lets the list shrink and share the row", () => {
    const h = html();
    expect(h).toContain("min-w-0");
    expect(h).toContain("flex-1");
    expect(h).toContain("basis-32");
  });
  it("keeps the add button", () => {
    expect(html()).toContain("+ فئة جديدة");
  });
});
