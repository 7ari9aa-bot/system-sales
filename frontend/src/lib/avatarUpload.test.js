import { describe, expect, it } from "vitest";
import { AVATAR_MAX_BYTES, avatarErrorKey, isAcceptedImage } from "./avatarUpload";

const file = (type, size) => ({ type, size });

describe("isAcceptedImage", () => {
  it.each(["image/png", "image/jpeg", "image/webp"])("accepts %s", (type) => {
    expect(isAcceptedImage(file(type, 1024))).toBe(true);
  });

  it.each([["image/gif"], ["image/svg+xml"], ["application/pdf"], [""]])("refuses %s", (type) => {
    expect(isAcceptedImage(file(type, 1024))).toBe(false);
  });

  it("refuses an oversized file before it is uploaded", () => {
    expect(isAcceptedImage(file("image/png", AVATAR_MAX_BYTES + 1))).toBe(false);
    expect(isAcceptedImage(file("image/png", AVATAR_MAX_BYTES))).toBe(true);
  });

  it("refuses a missing file", () => {
    expect(isAcceptedImage(null)).toBe(false);
    expect(isAcceptedImage(undefined)).toBe(false);
  });
});

describe("avatarErrorKey", () => {
  it("names the limit rather than the transport when the file is too big", () => {
    expect(avatarErrorKey({ status: 413 })).toBe("avatar.tooLarge");
  });

  it("says the file is not a supported picture", () => {
    expect(avatarErrorKey({ status: 415 })).toBe("avatar.notImage");
    expect(avatarErrorKey({ status: 400, code: "unsupported_media_type" })).toBe("avatar.notImage");
  });

  it("says a permission problem instead of promising a retry", () => {
    expect(avatarErrorKey({ status: 403 })).toBe("avatar.forbidden");
    expect(avatarErrorKey({ status: 401 })).toBe("avatar.forbidden");
  });

  it("offers a retry only when the failure is transient", () => {
    expect(avatarErrorKey({ status: 503, retryable: true })).toBe("avatar.retry");
    expect(avatarErrorKey({ status: 0, code: "network", retryable: true })).toBe("avatar.retry");
  });

  it("falls back to a plain failure for anything else", () => {
    expect(avatarErrorKey({ status: 400, code: "validation_error" })).toBe("avatar.failed");
    expect(avatarErrorKey(undefined)).toBe("avatar.failed");
  });
});
