import { afterEach, describe, expect, it, vi } from "vitest";
import {
  FB_VIDEO,
  facebookPublishFailure,
  facebookReelScheduleProblem,
  facebookReelStoryProblem,
  facebookStoryPhotoProblem,
  facebookVideoProblem,
  publishFacebookReel,
  publishFacebookStory,
} from "@/lib/facebookApi";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({ api: vi.fn(async () => ({ id: "9001", scheduled: false })) }));
afterEach(() => vi.mocked(api).mockClear());

const MB = 1024 * 1024;
const file = (type = "video/mp4", size = 1000, name = "v.mp4") => ({ type, size, name });
const GOOD = { width: 1080, height: 1920, seconds: 20 };
const NOW = Date.UTC(2026, 10, 19, 12, 0, 0);
const at = (minutes) => new Date(NOW + minutes * 60000).toISOString().slice(0, 16);

describe("a video is checked against Meta's Reel and Story rules before it is uploaded", () => {
  it("accepts a tall mp4 of a fair length, at the minimum size too", () => {
    expect(facebookVideoProblem(file(), GOOD, "reel", "en")).toBe("");
    expect(facebookVideoProblem(file(), { width: 540, height: 960, seconds: 3 }, "reel", "en")).toBe("");
    expect(facebookVideoProblem(file(), { width: 540, height: 960, seconds: 90 }, "reel", "en")).toBe("");
  });
  it("refuses anything but mp4, and a file over the ceiling", () => {
    expect(facebookVideoProblem(file("video/quicktime"), GOOD, "reel", "en")).toMatch(/mp4/);
    expect(facebookVideoProblem(file("video/mp4", FB_VIDEO.maxBytes + 1), GOOD, "reel", "en")).toMatch(/200 MB/);
    expect(facebookVideoProblem(file("video/mp4", FB_VIDEO.maxBytes), GOOD, "reel", "en")).toBe("");
  });
  it("refuses a small, a wide or an unreadable video and says what it measured", () => {
    expect(facebookVideoProblem(file(), { width: 360, height: 640, seconds: 10 }, "reel", "en")).toMatch(/at least 540 x 960.*360 x 640/);
    expect(facebookVideoProblem(file(), { width: 1920, height: 1080, seconds: 10 }, "reel", "en")).toMatch(/9:16.*1920 x 1080/);
    expect(facebookVideoProblem(file(), null, "reel", "en")).toMatch(/could not be read/);
    expect(facebookVideoProblem(file(), { width: 0, height: 0, seconds: NaN }, "reel", "en")).toMatch(/could not be read/);
  });
  it("a Reel runs 3 to 90 seconds but a Story stops at 60", () => {
    const len = (seconds) => ({ ...GOOD, seconds });
    expect(facebookVideoProblem(file(), len(2.9), "reel", "en")).toMatch(/at least 3/);
    expect(facebookVideoProblem(file(), len(90.4), "reel", "en")).toMatch(/at most 90/);
    expect(facebookVideoProblem(file(), len(75), "reel", "en")).toBe("");
    expect(facebookVideoProblem(file(), len(75), "story", "en")).toMatch(/at most 60/);
    expect(facebookVideoProblem(file(), len(60), "story", "en")).toBe("");
  });
  it("answers in Arabic", () => {
    expect(facebookVideoProblem(file("video/webm"), GOOD, "reel", "ar")).toMatch(/mp4/);
    expect(facebookVideoProblem(file(), { ...GOOD, seconds: 75 }, "story", "ar")).toMatch(/60/);
  });
});

describe("a Story picture and a Reel's time follow Meta's lists", () => {
  it("takes the types Meta lists and not webp or pdf, up to 10 MB", () => {
    for (const t of ["image/jpeg", "image/png", "image/gif", "image/bmp", "image/tiff"]) expect(facebookStoryPhotoProblem(file(t, 5 * MB), "en")).toBe("");
    expect(facebookStoryPhotoProblem(file("image/webp"), "en")).toMatch(/JPEG, PNG/);
    expect(facebookStoryPhotoProblem(file("application/pdf"), "en")).toMatch(/JPEG, PNG/);
    expect(facebookStoryPhotoProblem(file("image/png", 10 * MB), "en")).toBe("");
    expect(facebookStoryPhotoProblem(file("image/png", 10 * MB + 1), "en")).toMatch(/10 MB/);
  });
  it("schedules a Reel from 10 minutes to 29 days (not the 30 a post gets)", () => {
    expect(facebookReelScheduleProblem("", "en", NOW)).toBe("");
    expect(facebookReelScheduleProblem(at(9), "en", NOW)).toMatch(/10 minutes/);
    expect(facebookReelScheduleProblem(at(11), "en", NOW)).toBe("");
    expect(facebookReelScheduleProblem(at(29 * 1440 - 5), "en", NOW)).toBe("");
    expect(facebookReelScheduleProblem(at(29 * 1440 + 5), "en", NOW)).toMatch(/29 days/);
    expect(facebookReelScheduleProblem("garbage", "en", NOW)).toMatch(/not valid/);
  });
});

describe("the one rule the dialog uses to decide whether Post is enabled", () => {
  const ok = { kind: "reel", file: file(), info: GOOD };
  it("is empty only for a good file", () => {
    expect(facebookReelStoryProblem(ok, "en", NOW)).toBe("");
    expect(facebookReelStoryProblem({ kind: "reel" }, "en", NOW)).toMatch(/Pick a video/);
  });
  it("waits while the video is still being read, and reports a failed read", () => {
    expect(facebookReelStoryProblem({ ...ok, info: null, reading: true }, "en", NOW)).toMatch(/Reading/);
    expect(facebookReelStoryProblem({ ...ok, info: null, readError: "could not read" }, "en", NOW)).toBe("could not read");
  });
  it("a Reel is a video only, but a Story may be a picture", () => {
    const pic = file("image/png", 1000, "p.png");
    expect(facebookReelStoryProblem({ kind: "reel", file: pic }, "en", NOW)).toMatch(/video/);
    expect(facebookReelStoryProblem({ kind: "story", file: pic }, "en", NOW)).toBe("");
    expect(facebookReelStoryProblem({ kind: "story", file: file("image/webp") }, "en", NOW)).toMatch(/JPEG, PNG/);
  });
  it("the time only matters when scheduling is on, and only for a Reel", () => {
    expect(facebookReelStoryProblem({ ...ok, scheduleOn: true, scheduleAt: at(2) }, "en", NOW)).toMatch(/10 minutes/);
    expect(facebookReelStoryProblem({ ...ok, scheduleOn: false, scheduleAt: at(2) }, "en", NOW)).toBe("");
    expect(facebookReelStoryProblem({ ...ok, kind: "story", scheduleOn: true, scheduleAt: at(2) }, "en", NOW)).toBe("");
    expect(facebookReelStoryProblem({ ...ok, scheduleOn: true, scheduleAt: at(60) }, "en", NOW)).toBe("");
  });
});

describe("publishing sends the raw file and the text in headers", () => {
  it("sends the mp4 as the body with its text percent-encoded so Arabic survives", async () => {
    const f = file();
    await publishFacebookReel({ file: f, description: "  عرض #الجمعة  ", title: "خصم", scheduleAt: "2026-12-01T10:00", aiGenerated: true });
    const [path, opts] = vi.mocked(api).mock.calls[0];
    expect(path).toBe("/facebook/reels");
    expect(opts).toMatchObject({ method: "POST", body: f, rawBody: true, contentType: "video/mp4" });
    expect(decodeURIComponent(opts.headers["X-Description"])).toBe("عرض #الجمعة");
    expect(decodeURIComponent(opts.headers["X-Title"])).toBe("خصم");
    expect(opts.headers["X-Schedule-At"]).toMatch(/^2026-12-01T\d\d:00:00\.000Z$/);
    expect(opts.headers["X-AI-Generated"]).toBe("true");
    for (const v of Object.values(opts.headers)) expect(v).toMatch(/^[\x20-\x7e]*$/); // a header is ASCII
  });
  it("sends no empty headers", async () => {
    await publishFacebookReel({ file: file(), description: "  ", scheduleAt: "" });
    expect(vi.mocked(api).mock.calls[0][1].headers).toEqual({});
  });
  it("waits as long as the server does (upload plus Facebook's processing), not the 60 second default", async () => {
    await publishFacebookReel({ file: file() });
    await publishFacebookStory({ file: file() });
    for (const [, opts] of vi.mocked(api).mock.calls) expect(opts.timeoutMs).toBeGreaterThanOrEqual(5 * 60 * 1000);
  });
  it("a Story goes under its own type so the server knows picture from video", async () => {
    await publishFacebookStory({ file: file("image/png") });
    await publishFacebookStory({ file: file("video/mp4") });
    expect(vi.mocked(api).mock.calls.map(([p, o]) => [p, o.contentType])).toEqual([["/facebook/stories", "image/png"], ["/facebook/stories", "video/mp4"]]);
  });
});

describe("when publishing fails", () => {
  it("after a dropped connection it does not say 'failed': the post may have gone out", () => {
    for (const code of ["timeout", "network"]) {
      expect(facebookPublishFailure({ code, message: "x" }, "en")).toMatch(/may have been posted/);
      expect(facebookPublishFailure({ code }, "ar")).toMatch(/قد يكون نُشر/);
    }
  });
  it("otherwise it shows what the server said, with a fallback", () => {
    expect(facebookPublishFailure({ message: "Facebook allows 30 Reels a day" }, "en")).toBe("Facebook allows 30 Reels a day");
    expect(facebookPublishFailure({}, "en")).toBe("Could not publish");
    expect(facebookPublishFailure(null, "ar")).toBe("تعذّر النشر");
  });
});
