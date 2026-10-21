import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual("@/lib/api");
  return { ...actual, api: async (...a) => apiMock(...a) };
});

import { MAX_IMAGE_BYTES, imageProblem, imagesOf, uploadProductImage, uploadProductImages } from "./productImage";

// Same fields as lib/api.js ApiError (message, status, code); built by hand so the mock factory needs no import.
const serverError = (message, status, code = null) => Object.assign(new Error(message), { name: "ApiError", status, code });

const file = (over = {}) => ({ name: "a.png", type: "image/png", size: 1000, ...over });

beforeEach(() => {
  apiMock.mockReset();
  apiMock.mockResolvedValue({});
});

describe("imageProblem", () => {
  it("accepts a normal image", () => expect(imageProblem(file())).toBeNull());
  it("accepts every type the backend accepts", () => {
    for (const type of ["image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp"]) expect(imageProblem(file({ type }))).toBeNull();
  });
  it("rejects what the backend would reject", () => {
    expect(imageProblem(null)).toMatch(/اختر/);
    expect(imageProblem(file({ type: "application/pdf" }))).toMatch(/غير مدعوم/);
    expect(imageProblem(file({ type: "image/svg+xml" }))).toMatch(/غير مدعوم/);
    expect(imageProblem(file({ size: 0 }))).toMatch(/فارغ/);
    expect(imageProblem(file({ size: MAX_IMAGE_BYTES + 1 }))).toMatch(/10/);
  });
  it("allows exactly the limit", () => expect(imageProblem(file({ size: MAX_IMAGE_BYTES }))).toBeNull());
});

describe("imagesOf", () => {
  it("orders by position and drops entries without a url", () => {
    const out = imagesOf({ images: [{ id: "b", url: "u2", position: 1 }, { id: "x", url: "" }, { id: "a", url: "u1", position: 0 }] });
    expect(out.map((i) => i.id)).toEqual(["a", "b"]);
  });
  it("is empty when there are no images", () => {
    expect(imagesOf(undefined)).toEqual([]);
    expect(imagesOf({})).toEqual([]);
  });
});

describe("uploadProductImage", () => {
  it("sends the raw file with its own content type", async () => {
    apiMock.mockResolvedValue({ id: "i1" });
    const f = file();
    await uploadProductImage("p/1", f);
    expect(apiMock).toHaveBeenCalledWith("/products/p%2F1/images/upload", { method: "POST", body: f, rawBody: true, contentType: "image/png" });
  });
  it("does not call the server for an invalid file", async () => {
    await expect(uploadProductImage("p1", file({ type: "text/plain" }))).rejects.toThrow(/غير مدعوم/);
    expect(apiMock).not.toHaveBeenCalled();
  });
  it("explains a 503 (storage down) in plain words", async () => {
    apiMock.mockImplementation(() => Promise.reject(serverError("Object storage is unavailable", 503, "storage_unavailable")));
    const err = await uploadProductImage("p1", file()).catch((e) => e);
    expect(err.message).toMatch(/تخزين الصور غير متاح/);
  });
  it("passes any other server error through unchanged", async () => {
    apiMock.mockImplementation(() => Promise.reject(serverError("image exceeds the 10 MB upload limit", 422)));
    const err = await uploadProductImage("p1", file()).catch((e) => e);
    expect(err.message).toMatch(/10 MB/);
    expect(err.status).toBe(422);
  });
});

describe("uploadProductImages", () => {
  it("reports which photo failed without failing the rest", async () => {
    apiMock.mockResolvedValueOnce({ id: "i1" }).mockRejectedValueOnce(new Error("boom")).mockResolvedValueOnce({ id: "i3" });
    const r = await uploadProductImages("p1", [file({ name: "1.png" }), file({ name: "2.png" }), file({ name: "3.png" })]);
    expect(r.uploaded.map((u) => u.id)).toEqual(["i1", "i3"]);
    expect(r.failed).toEqual([{ name: "2.png", message: "boom" }]);
  });
  it("uploads in the order picked", async () => {
    apiMock.mockResolvedValue({});
    await uploadProductImages("p1", [file({ name: "first" }), file({ name: "second" })]);
    expect(apiMock.mock.calls.map((c) => c[1].body.name)).toEqual(["first", "second"]);
  });
  it("handles no files", async () => expect(await uploadProductImages("p1", [])).toEqual({ uploaded: [], failed: [] }));
});
