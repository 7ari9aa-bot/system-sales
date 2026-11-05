import { describe, expect, it } from "vitest";
import { previewLine } from "./inboxPreview";

const AR = {
  "inbox.preview.image": "صورة",
  "inbox.preview.voice": "رسالة صوتية",
  "inbox.preview.video": "فيديو",
  "inbox.preview.file": "ملف",
  "inbox.preview.location": "موقع",
  "inbox.preview.contact": "جهة اتصال",
  "inbox.preview.buttons": "قائمة خيارات",
  "inbox.preview.list": "قائمة خيارات",
  "inbox.preview.reaction": "تفاعل",
  "inbox.preview.unsupported": "رسالة غير مدعومة",
  "inbox.preview.deleted": "رسالة محذوفة",
  "inbox.preview.empty": "رسالة",
};
const t = (key) => AR[key] ?? key;

describe("previewLine", () => {
  it("shows the message text when the server sent one", () => {
    expect(previewLine({ last_message_preview: "هل يوجد مقاس L؟" }, t)).toBe("هل يوجد مقاس L؟");
  });

  it.each([
    ["image", "صورة"],
    ["voice", "رسالة صوتية"],
    ["video", "فيديو"],
    ["file", "ملف"],
    ["location", "موقع"],
    ["contact", "جهة اتصال"],
    ["buttons", "قائمة خيارات"],
    ["reaction", "تفاعل"],
    ["unsupported", "رسالة غير مدعومة"],
  ])("names a %s message instead of leaving the row blank", (contentType, label) => {
    expect(previewLine({ last_message_content_type: contentType }, t)).toBe(label);
  });

  it("says a message was deleted rather than showing nothing", () => {
    expect(previewLine({ last_message_deleted: true, last_message_content_type: "text" }, t)).toBe(
      "رسالة محذوفة",
    );
  });

  it("never returns an empty string, which is how a blank row reads as broken", () => {
    for (const row of [
      {},
      { last_message_preview: "" },
      { last_message_preview: "   " },
      { last_message_preview: null, last_message_content_type: null },
      { last_message_preview: null, last_message_content_type: "text" },
    ]) {
      expect(previewLine(row, t)).toBe("رسالة");
    }
  });

  it("keeps whitespace-only text out of the row", () => {
    expect(previewLine({ last_message_preview: " \n ", last_message_content_type: "image" }, t)).toBe(
      "صورة",
    );
  });
});
