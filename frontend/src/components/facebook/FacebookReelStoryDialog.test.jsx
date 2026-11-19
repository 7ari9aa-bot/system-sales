import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import FacebookReelStoryDialog from "@/components/facebook/FacebookReelStoryDialog";

const html = (kind, lang = "en") => renderToStaticMarkup(<FacebookReelStoryDialog kind={kind} lang={lang} onPublishReel={() => {}} onPublishStory={() => {}} onClose={() => {}} />);
const buttons = (out) => [...out.matchAll(/<button\b[^>]*>/g)].map((m) => m[0]);

describe("the Reel and Story dialog before a file is chosen", () => {
  it("is a labelled dialog and tells the rules of each kind", () => {
    const reel = html("reel");
    expect(reel).toContain('role="dialog"');
    expect(reel).toContain('aria-label="Create reel"');
    expect(reel).toMatch(/9:16 mp4, at least 540x960, 3 to 90 seconds/);
    const story = html("story");
    expect(story).toContain('aria-label="Create story"');
    expect(story).toMatch(/up to 60 seconds, or a picture up to 10 MB/);
  });
  it("cannot be posted yet: the submit button is disabled with no file", () => {
    for (const kind of ["reel", "story"]) {
      const submit = buttons(html(kind)).find((b) => b.includes('type="submit"'));
      expect(submit).toContain("disabled");
    }
  });
  it("a Reel can be scheduled or marked AI-made; a Story has neither, because Meta takes neither", () => {
    const reel = html("reel");
    expect(reel).toContain("Schedule");
    expect(reel).toContain("Made with AI");
    expect(reel).toContain("Reel description");
    const story = html("story");
    expect(story).not.toContain("Schedule");
    expect(story).not.toContain("Made with AI");
    expect(story).not.toContain("description");
  });
  it("a Reel takes only mp4; a Story takes mp4 and the pictures Meta lists", () => {
    expect(html("reel")).toContain('accept="video/mp4"');
    const accept = html("story").match(/data-testid="fb-reel-input" type="file" accept="([^"]+)"/)[1];
    expect(accept.split(",")).toEqual(["video/mp4", "image/jpeg", "image/png", "image/gif", "image/bmp", "image/tiff"]);
  });
  it("every button does something real: close, choose a file, or (Reel only) the two options", () => {
    const names = (kind) => buttons(html(kind)).map((b) => (b.match(/aria-label="([^"]+)"/) || [])[1] || (b.includes('type="submit"') ? "submit" : "choose"));
    expect(names("story").sort()).toEqual(["Close", "choose", "submit"]);
    expect(names("reel").length).toBe(5); // close, choose, submit, schedule, AI
  });
  it("speaks Arabic and flips direction", () => {
    const out = html("reel", "ar");
    expect(out).toContain('dir="rtl"');
    expect(out).toContain("إنشاء ريل");
    expect(out).toContain("اختر فيديو");
  });
});
