import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.fn();
const fetchMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual("@/lib/api");
  return { ...actual, api: async (...a) => apiMock(...a), fetchWithTimeout: async (...a) => fetchMock(...a) };
});

import {
  MAX_IMPORT_BYTES,
  SHEET_LABEL,
  assignField,
  cancelImport,
  canStart,
  canValidate,
  downloadErrorReport,
  downloadTemplate,
  errorText,
  getImportPreview,
  importErrorText,
  ignoredColumnsOf,
  importFileProblem,
  isFinished,
  mappingRows,
  progressOf,
  remainingOf,
  saveImportMapping,
  startImport,
  topProblems,
  totalsOf,
  uploadImportFile,
  validateImport,
} from "./importCenter";

const file = (over = {}) => ({ name: "products.xlsx", type: "application/vnd.ms-excel", size: 1000, ...over });

beforeEach(() => {
  apiMock.mockReset();
  apiMock.mockResolvedValue({});
  fetchMock.mockReset();
});

describe("importFileProblem", () => {
  it("accepts xlsx and csv, in any letter case", () => {
    expect(importFileProblem(file())).toBeNull();
    expect(importFileProblem(file({ name: "STOCK.CSV" }))).toBeNull();
  });
  it("asks for a re-save instead of accepting the legacy and macro formats", () => {
    for (const name of ["a.xls", "a.xlsm", "a.xlsb"]) expect(importFileProblem(file({ name }))).toMatch(/احفظ/);
  });
  it("refuses other types, empty files and files over 20 MB", () => {
    expect(importFileProblem(file({ name: "a.pdf" }))).toMatch(/المدعومة/);
    expect(importFileProblem(file({ size: 0 }))).toMatch(/فارغ/);
    expect(importFileProblem(file({ size: MAX_IMPORT_BYTES + 1 }))).toMatch(/20/);
    expect(importFileProblem(file({ size: MAX_IMPORT_BYTES }))).toBeNull();
    expect(importFileProblem(null)).toMatch(/اختر/);
  });
});

describe("importErrorText", () => {
  it("never shows the server's text for server-side failures", () => {
    expect(importErrorText({ status: 500, message: "psycopg2 exploded", retryable: true })).not.toMatch(/psycopg2/);
    expect(importErrorText({ status: 403, message: "x" })).toMatch(/صلاحية/);
    expect(importErrorText({ status: 413 })).toMatch(/20/);
    expect(importErrorText({ status: 409 })).toMatch(/تغيّرت/);
    expect(importErrorText({ status: 0, retryable: true })).toMatch(/الاتصال/);
  });
  it("shows a 400 message, since the backend writes those for the merchant", () => {
    expect(importErrorText({ status: 400, message: "save the file as .xlsx" })).toBe("save the file as .xlsx");
  });
});

describe("error codes", () => {
  it("has a merchant sentence for every code the backend can produce", () => {
    const codes = [
      "bad_status", "barcode_taken", "duplicate_in_file", "has_spaces", "negative", "no_identity", "not_a_number",
      "not_positive", "not_whole", "opening_stock_already_set", "required", "scientific_notation",
      "sku_belongs_to_other_product", "too_large", "too_long", "unknown_product", "unknown_sku", "unknown_warehouse",
    ];
    for (const c of codes) expect(errorText(c), c).not.toBe("قيمة غير صالحة");
  });
  it("falls back for a code it does not know", () => expect(errorText("brand_new")).toBe("قيمة غير صالحة"));
});

describe("api calls", () => {
  it("uploads the raw file with the file name in the query, not the body", async () => {
    const f = file({ name: "قائمة أسعار.xlsx" });
    await uploadImportFile(f);
    const [path, opts] = apiMock.mock.calls[0];
    expect(path).toBe(`/imports/sessions?filename=${encodeURIComponent("قائمة أسعار.xlsx")}`);
    expect(opts).toMatchObject({ method: "POST", body: f, rawBody: true });
  });
  it("does not call the server for a file it already knows is refused", async () => {
    await expect(uploadImportFile(file({ name: "a.xls" }))).rejects.toThrow();
    expect(apiMock).not.toHaveBeenCalled();
  });
  it("uses the documented verbs and paths", async () => {
    await saveImportMapping("abc", { mapping: { Products: { A: "title" } }, options: { duplicate_policy: "skip" } });
    await validateImport("abc");
    await getImportPreview("abc", { sample: 50 });
    await startImport("abc");
    await cancelImport("abc");
    expect(apiMock.mock.calls.map(([p, o]) => `${o?.method ?? "GET"} ${p}`)).toEqual([
      "PUT /imports/sessions/abc/mapping",
      "POST /imports/sessions/abc/validate",
      "GET /imports/sessions/abc/preview?sample=50",
      "POST /imports/sessions/abc/start",
      "POST /imports/sessions/abc/cancel",
    ]);
  });
  it("escapes a session id so it cannot change the path", async () => {
    await startImport("a/../b");
    expect(apiMock.mock.calls[0][0]).toBe("/imports/sessions/a%2F..%2Fb/start");
  });
});

describe("downloadErrorReport", () => {
  it("fetches with the cookie and saves a file", async () => {
    fetchMock.mockResolvedValue({ ok: true, blob: async () => new Blob(["x"]) });
    const link = { click: vi.fn(), remove: vi.fn() };
    vi.stubGlobal("document", { createElement: vi.fn(() => link), body: { appendChild: vi.fn() } });
    vi.stubGlobal("URL", { createObjectURL: vi.fn(() => "blob:1"), revokeObjectURL: vi.fn() });
    try {
      await downloadErrorReport("abc");
      expect(fetchMock.mock.calls[0][0]).toMatch(/\/imports\/sessions\/abc\/errors\.csv$/);
      expect(fetchMock.mock.calls[0][1]).toMatchObject({ credentials: "include" });
      expect(link).toMatchObject({ href: "blob:1", download: "import-errors.csv" });
      expect(link.click).toHaveBeenCalledOnce();
      expect(link.remove).toHaveBeenCalledOnce();
      expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:1");
    } finally {
      vi.unstubAllGlobals();
    }
  });
  it("throws with the status when the server refuses", async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 403 });
    await expect(downloadErrorReport("abc")).rejects.toMatchObject({ status: 403 });
  });
});

describe("downloadTemplate", () => {
  it("fetches the starter workbook with the cookie and saves it as an xlsx", async () => {
    fetchMock.mockResolvedValue({ ok: true, blob: async () => new Blob(["x"]) });
    const link = { click: vi.fn(), remove: vi.fn() };
    vi.stubGlobal("document", { createElement: vi.fn(() => link), body: { appendChild: vi.fn() } });
    vi.stubGlobal("URL", { createObjectURL: vi.fn(() => "blob:2"), revokeObjectURL: vi.fn() });
    try {
      await downloadTemplate();
      expect(fetchMock.mock.calls[0][0]).toMatch(/\/imports\/template\.xlsx$/);
      expect(fetchMock.mock.calls[0][1]).toMatchObject({ credentials: "include" });
      expect(link).toMatchObject({ href: "blob:2", download: "fihrist-import-template.xlsx" });
      expect(link.click).toHaveBeenCalledOnce();
      expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:2");
    } finally {
      vi.unstubAllGlobals();
    }
  });
  it("throws with the status when the server refuses", async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 403 });
    await expect(downloadTemplate()).rejects.toMatchObject({ status: 403 });
  });
});

describe("image import wording", () => {
  it("names the Images sheet and explains every code the server can return for a picture", () => {
    expect(SHEET_LABEL.Images).toBeTruthy();
    for (const code of ["not_a_link", "too_many_images", "image_unreachable", "not_an_image", "storage_unavailable"]) {
      expect(errorText(code), code).not.toBe("قيمة غير صالحة");
    }
  });
});

describe("customer import wording", () => {
  it("names the Customers sheet and explains every code the server can return for a customer", () => {
    expect(SHEET_LABEL.Customers).toBe("العملاء");
    for (const code of [
      "no_contact", "bad_phone", "bad_email", "already_a_customer", "phone_of_deleted_customer", "too_many_tags",
    ]) {
      expect(errorText(code), code).not.toBe("قيمة غير صالحة");
    }
  });
  it("does not blame a barcode when it is a phone number that Excel turned into 1E+9", () => {
    // the same server code serves barcodes and phones, so the sentence must fit both
    expect(errorText("scientific_notation")).not.toContain("الباركود");
  });
});

describe("ignoredColumnsOf", () => {
  it("separates stock typed on the wrong sheet from columns that are just unused", () => {
    const sheet = {
      ignored_columns: [
        { column: "الكمية", reason: "stock_on_wrong_sheet" },
        { column: "ملاحظات", reason: "unmatched" },
      ],
    };
    expect(ignoredColumnsOf(sheet)).toEqual({ stock: ["الكمية"], other: ["ملاحظات"] });
  });
  it("is empty when the server sent nothing", () => {
    expect(ignoredColumnsOf({})).toEqual({ stock: [], other: [] });
    expect(ignoredColumnsOf(undefined)).toEqual({ stock: [], other: [] });
  });
});

describe("mapping rules", () => {
  it("lists the columns in the file's order", () => {
    expect(mappingRows({ mapping: { Name: "title", Extra: null } })).toEqual([
      { header: "Name", field: "title" },
      { header: "Extra", field: "" },
    ]);
    expect(mappingRows(undefined)).toEqual([]);
  });
  it("lets one column own a field: choosing it again clears the other column", () => {
    const next = assignField({ A: "title", B: null }, "B", "title");
    expect(next).toEqual({ A: null, B: "title" });
  });
  it("ignoring a column maps it to null and leaves the others alone", () => {
    expect(assignField({ A: "title", B: "sku" }, "A", "")).toEqual({ A: null, B: "sku" });
  });
  it("does not change the input", () => {
    const m = { A: "title" };
    assignField(m, "B", "title");
    expect(m).toEqual({ A: "title" });
  });
  it("can validate only when no sheet is missing a required field", () => {
    expect(canValidate({ sheets: { Products: { missing_required: [] } } })).toBe(true);
    expect(canValidate({ sheets: { Products: { missing_required: ["title"] } } })).toBe(false);
    expect(canValidate({ sheets: { Products: { missing_required: [] }, Variants: { missing_required: ["sku"] } } })).toBe(false);
    expect(canValidate({ sheets: {} })).toBe(false);
    expect(canValidate(null)).toBe(false);
  });
});

describe("totals, start and progress", () => {
  const stats = {
    sheets: {
      Products: { total: 10, valid: 8, invalid: 2, create: 6, update: 2, skip: 0, error_codes: { required: 2 } },
      Variants: { total: 5, valid: 5, invalid: 0, create: 5, update: 0, skip: 0, error_codes: {} },
    },
  };
  it("adds the sheets up", () => {
    expect(totalsOf(stats)).toEqual({ total: 15, valid: 13, invalid: 2, create: 11, update: 2, skip: 0 });
    expect(totalsOf(undefined).total).toBe(0);
  });
  it("starts only a checked session that has something to apply", () => {
    expect(canStart({ status: "validated", stats })).toBe(true);
    expect(canStart({ status: "analyzed", stats })).toBe(false);
    expect(canStart({ status: "running", stats })).toBe(false);
    expect(canStart({ status: "validated", stats: { sheets: { Products: { valid: 0, invalid: 3 } } } })).toBe(false);
  });
  it("computes progress from what was done and what is left", () => {
    expect(progressOf({ applied: 50, skipped: 0, failed: 0, remaining: 50 })).toBe(50);
    expect(progressOf({ applied: 40, skipped: 5, failed: 5, remaining: 50 })).toBe(50);
    expect(progressOf({ applied: 10, remaining: 0 })).toBe(100);
    expect(progressOf({})).toBe(0);
    expect(progressOf(undefined)).toBe(0);
  });
  it("before the first batch finishes, the rows to apply stand in for what remains", () => {
    expect(remainingOf({ to_apply: 1200 })).toBe(1200);
    expect(progressOf({ to_apply: 1200 })).toBe(0);
    expect(remainingOf({ to_apply: 1200, applied: 500, skipped: 0, failed: 0 })).toBe(700);
    expect(remainingOf({ to_apply: 1200, applied: 500, remaining: 650 })).toBe(650);
    expect(remainingOf({ to_apply: 10, applied: 20 })).toBe(0);
    expect(remainingOf(undefined)).toBe(0);
  });
  it("lists the most common problems first", () => {
    const s = { sheets: { A: { error_codes: { required: 2, unknown_sku: 7 } }, B: { error_codes: { required: 3 } } } };
    expect(topProblems(s).map((p) => [p.code, p.count])).toEqual([["unknown_sku", 7], ["required", 5]]);
    expect(topProblems(s, 1)).toHaveLength(1);
  });
  it("knows which states are final", () => {
    for (const s of ["completed", "cancelled", "failed"]) expect(isFinished(s)).toBe(true);
    for (const s of ["analyzed", "validated", "running"]) expect(isFinished(s)).toBe(false);
  });
});
