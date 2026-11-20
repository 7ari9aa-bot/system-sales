// The form behind "send buttons / a list / a link". Pure logic, so every rule can be tested
// without a screen.
//
// The limits are Meta's, copied from the server (backend/.../whatsapp_interactive.py) so that a
// field turns red while the agent types instead of after the server refuses. The server stays the
// judge: it checks the same things again and is the only one that decides.
//
// The three kinds do NOT share every limit (a list body takes 4096, buttons 1024; a list header is
// text only), which is why each is stated on its own.

export const KINDS = ["buttons", "list", "cta_url"];

export const LIMITS = {
  footer: 60,
  headerText: 60,
  buttonsBody: 1024,
  buttons: 3,
  buttonTitle: 20,
  buttonId: 256,
  listBody: 4096,
  listButton: 20,
  sections: 10,
  rows: 10, // across ALL sections together
  sectionTitle: 24,
  rowTitle: 24,
  rowDescription: 72,
  rowId: 200,
  ctaBody: 1024,
  ctaLabel: 20,
  url: 2000,
};

const text = (v) => (typeof v === "string" ? v.trim() : "");
// Meta counts characters, not bytes or UTF-16 units: an emoji is one.
const len = (s) => [...s].length;

/** A short, collision-free id for a choice the agent did not name (the customer never sees it). */
export function nextId(prefix, taken) {
  const used = new Set(taken);
  let n = 1;
  while (used.has(`${prefix}_${n}`)) n += 1;
  return `${prefix}_${n}`;
}

export function emptyForm(kind = "buttons") {
  return {
    kind,
    header: "",
    body: "",
    footer: "",
    buttons: [{ title: "" }],
    listButton: "",
    sections: [{ title: "", rows: [{ title: "", description: "" }] }],
    label: "",
    url: "",
  };
}

/** Switching kind keeps what the kinds share (header, body, footer) and starts the rest clean. */
export function switchKind(form, kind) {
  if (form.kind === kind) return form;
  return { ...emptyForm(kind), header: form.header, body: form.body, footer: form.footer };
}

export function bodyLimit(kind) {
  return kind === "list" ? LIMITS.listBody : kind === "cta_url" ? LIMITS.ctaBody : LIMITS.buttonsBody;
}

export function rowCount(form) {
  return form.sections.reduce((n, s) => n + s.rows.length, 0);
}

export function canAddButton(form) {
  return form.buttons.length < LIMITS.buttons;
}
export function canAddSection(form) {
  return form.sections.length < LIMITS.sections && rowCount(form) < LIMITS.rows;
}
export function canAddRow(form) {
  return rowCount(form) < LIMITS.rows;
}

function httpUrl(value) {
  try {
    const u = new URL(value);
    return (u.protocol === "https:" || u.protocol === "http:") && Boolean(u.host);
  } catch {
    return false;
  }
}

/**
 * Check the form. Returns `{ ok: true, spec }` (the exact shape the server takes) or
 * `{ ok: false, errors }` where `errors` maps a field path to its message key, e.g.
 * `buttons.1.title` or `sections.0.rows.2.title`. `t` turns a key and its numbers into words.
 */
export function buildInteractive(form, t = (key) => key) {
  const errors = {};
  const need = (path, value, max) => {
    const s = text(value);
    if (!s) errors[path] = t("required");
    else if (len(s) > max) errors[path] = t("tooLong", { max });
    return s;
  };
  const optional = (path, value, max) => {
    const s = text(value);
    if (s && len(s) > max) errors[path] = t("tooLong", { max });
    return s;
  };

  const kind = form.kind;
  if (!KINDS.includes(kind)) return { ok: false, errors: { kind: t("required") } };

  const spec = { kind };
  spec.body = need("body", form.body, bodyLimit(kind));
  const header = optional("header", form.header, LIMITS.headerText);
  if (header) spec.header = { type: "text", text: header };
  const footer = optional("footer", form.footer, LIMITS.footer);
  if (footer) spec.footer = footer;

  if (kind === "buttons") {
    const seen = new Set();
    spec.buttons = form.buttons.map((b, i) => {
      const title = need(`buttons.${i}.title`, b.title, LIMITS.buttonTitle);
      const key = title.toLowerCase();
      if (title && seen.has(key)) errors[`buttons.${i}.title`] = t("duplicate");
      seen.add(key);
      return { id: b.id || `btn_${i + 1}`, title };
    });
    if (spec.buttons.length < 1) errors.buttons = t("atLeastOne");
    if (spec.buttons.length > LIMITS.buttons) errors.buttons = t("tooMany", { max: LIMITS.buttons });
  } else if (kind === "list") {
    spec.button = need("listButton", form.listButton, LIMITS.listButton);
    let total = 0;
    spec.sections = form.sections.map((s, si) => {
      const title = need(`sections.${si}.title`, s.title, LIMITS.sectionTitle);
      if (s.rows.length < 1) errors[`sections.${si}.rows`] = t("atLeastOne");
      const rows = s.rows.map((r, ri) => {
        total += 1;
        const row = { id: r.id || `row_${si + 1}_${ri + 1}`, title: need(`sections.${si}.rows.${ri}.title`, r.title, LIMITS.rowTitle) };
        const description = optional(`sections.${si}.rows.${ri}.description`, r.description, LIMITS.rowDescription);
        if (description) row.description = description;
        return row;
      });
      return { title, rows };
    });
    if (spec.sections.length < 1) errors.sections = t("atLeastOne");
    if (spec.sections.length > LIMITS.sections) errors.sections = t("tooMany", { max: LIMITS.sections });
    if (total > LIMITS.rows) errors.rows = t("tooManyRows", { max: LIMITS.rows });
  } else {
    spec.label = need("label", form.label, LIMITS.ctaLabel);
    const url = need("url", form.url, LIMITS.url);
    if (url && !httpUrl(url)) errors.url = t("badUrl");
    spec.url = url;
  }

  return Object.keys(errors).length ? { ok: false, errors } : { ok: true, spec };
}

/** The same one-line-per-choice text the server keeps as the message's body. */
export function previewLines(spec) {
  const lines = [spec.body];
  if (spec.kind === "buttons") lines.push(...spec.buttons.map((b) => `[ ${b.title} ]`));
  else if (spec.kind === "list") {
    lines.push(`[ ${spec.button} ]`);
    for (const s of spec.sections) lines.push(...s.rows.map((r) => `- ${r.title}`));
  } else lines.push(`[ ${spec.label} ] ${spec.url}`);
  return lines.join("\n");
}

/**
 * The drawn shape (what the server returns for a sent message) from the spec we send, so the
 * message shows at once instead of after the next reload. It mirrors the server's builder and a
 * test compares the two on real server output.
 */
export function toDisplay(spec) {
  const out = { body: { text: spec.body } };
  if (spec.header) out.header = { type: "text", text: spec.header.text };
  if (spec.footer) out.footer = { text: spec.footer };
  if (spec.kind === "buttons") {
    return { type: "button", ...out, action: { buttons: spec.buttons.map((b) => ({ type: "reply", reply: { id: b.id, title: b.title } })) } };
  }
  if (spec.kind === "list") {
    return {
      type: "list", ...out,
      action: { button: spec.button, sections: spec.sections.map((s) => ({ title: s.title, rows: s.rows.map((r) => ({ id: r.id, title: r.title, ...(r.description ? { description: r.description } : {}) })) })) },
    };
  }
  return { type: "cta_url", ...out, action: { name: "cta_url", parameters: { display_text: spec.label, url: spec.url } } };
}

/**
 * A drawable shape from a form that may still be half filled, for the live preview. Empty choices
 * are left out and blank texts stay blank; nothing here decides whether the form can be sent
 * (buildInteractive does), it only lets the agent watch the message take shape.
 */
export function draftDisplay(form) {
  const keep = (list) => list.filter((x) => text(x.title));
  const spec = { kind: form.kind, body: text(form.body) };
  const header = text(form.header);
  if (header) spec.header = { type: "text", text: header };
  const footer = text(form.footer);
  if (footer) spec.footer = footer;
  if (form.kind === "buttons") {
    spec.buttons = keep(form.buttons).map((b, i) => ({ id: b.id || `btn_${i + 1}`, title: text(b.title) }));
  } else if (form.kind === "list") {
    spec.button = text(form.listButton);
    spec.sections = form.sections
      .map((s, si) => ({ title: text(s.title), rows: keep(s.rows).map((r, ri) => ({ id: r.id || `row_${si + 1}_${ri + 1}`, title: text(r.title), description: text(r.description) })) }))
      .filter((s) => s.rows.length > 0);
  } else {
    spec.label = text(form.label);
    spec.url = text(form.url);
  }
  return toDisplay(spec);
}
