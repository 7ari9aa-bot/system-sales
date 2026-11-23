import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import InstagramStoryPerformance from "./InstagramStoryPerformance";
import { storyMetric, storyRows } from "@/lib/socialApi";

const html = (stories) => renderToStaticMarkup(<InstagramStoryPerformance stories={stories} lang="ar" />);

describe("a story's numbers are shown honestly", () => {
  it("Meta's -1 reads «أقل من ٥», never a negative number and never zero", () => {
    expect(storyMetric(-1, true).text).toBe("أقل من ٥");
    expect(storyMetric(-1, true).value).toBeNull();
    expect(storyMetric(-1, true).belowThreshold).toBe(true);
  });

  it("a metric Meta has not sent yet says so instead of showing 0", () => {
    expect(storyMetric(undefined, true).text).toBe("لسه موصلناش");
    expect(storyMetric(null, true).text).toBe("لسه موصلناش");
    expect(storyMetric(0, true).text).toBe("0");
  });

  it("only the metrics Meta actually named are listed", () => {
    const rows = storyRows({ impressions: 120, reach: -1 }, true);
    expect(rows.map((r) => r.key)).toEqual(["impressions", "reach"]);
    expect(rows[0].text).toBe("120");
    expect(rows[1].text).toBe("أقل من ٥");
  });

  it("renders a story with its rows", () => {
    const out = html([{ id: "s-1", isStory: true, insights: { impressions: 120, reach: -1 }, timeLabel: "أمس" }]);
    expect(out).toContain('data-testid="ig-story-s-1"');
    expect(out).toContain("مرات الظهور");
    expect(out).toContain("أقل من ٥");
  });

  it("says plainly when nothing has arrived yet, instead of an empty box", () => {
    expect(html([])).toContain("مفيش ستوري عندها أرقام");
    expect(html([{ id: "s-2", isStory: true, insights: {} }])).toContain("لسه موصلناش أرقامها");
  });
});
