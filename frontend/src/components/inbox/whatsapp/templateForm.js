// What the agent must fill in to send a WhatsApp template, and what the server is sent.
//
// A template is stored the way Meta wants it: `components` with a HEADER (text, or an image /
// video / document), a BODY with {{1}} {{2}} variables, a FOOTER, and BUTTONS. The send route
// takes the values as `template_vars`: body_params, header_params, header_media, button_params.
// Everything is checked here BEFORE the request, with the field named, because a send that Meta
// refuses has already used the customer's one chance to reach them outside the 24-hour window.

const VAR = /\{\{\s*(\d+)\s*\}\}/g;
export const MEDIA_FORMATS = ["IMAGE", "VIDEO", "DOCUMENT"];

/** The variable numbers in a text, in order, without repeats. */
export function variableNumbers(text) {
  const seen = [];
  for (const m of String(text ?? "").matchAll(VAR)) {
    const n = Number(m[1]);
    if (!seen.includes(n)) seen.push(n);
  }
  return seen;
}

const part = (components, type) => (components || []).find((c) => String(c?.type).toUpperCase() === type);

/**
 * The inputs a template asks for.
 * @returns {{ header: null|{kind:"text"|"image"|"video"|"document", text?:string, slots:number},
 *             bodySlots:number[], buttons: Array<{index:number, type:"quick_reply"|"url", text:string, needsInput:boolean}>,
 *             footer: string|null }}
 */
export function formShape(template) {
  const components = template?.components?.length
    ? template.components
    : [{ type: "BODY", text: template?.body_text || "" }];
  const header = part(components, "HEADER");
  const body = part(components, "BODY");
  const footer = part(components, "FOOTER");
  const buttons = part(components, "BUTTONS")?.buttons || [];

  let headerShape = null;
  if (header) {
    const format = String(header.format || "TEXT").toUpperCase();
    if (format === "TEXT") {
      headerShape = { kind: "text", text: header.text || "", slots: variableNumbers(header.text).length };
    } else if (MEDIA_FORMATS.includes(format)) {
      headerShape = { kind: format.toLowerCase(), slots: 0 };
    }
    // LOCATION and other header formats are not sendable from here: left out, see canSendFromInbox.
  }

  const shaped = buttons.map((b, index) => {
    const type = String(b.type || "").toUpperCase();
    if (type === "QUICK_REPLY") return { index, type: "quick_reply", text: b.text || "", needsInput: true };
    if (type === "URL") return { index, type: "url", text: b.text || "", needsInput: variableNumbers(b.url).length > 0 };
    // A phone button carries its number in the template: nothing to fill.
    return { index, type: "phone", text: b.text || "", needsInput: false };
  });

  return {
    header: headerShape,
    bodySlots: variableNumbers(body?.text ?? template?.body_text),
    buttons: shaped,
    footer: footer?.text || null,
  };
}

/** Why a template cannot be sent from the inbox, or null when it can. */
export function cannotSendReason(template) {
  if (!template) return "missing";
  if (template.status !== "approved") return "not_approved";
  const header = part(template.components || [], "HEADER");
  const format = header ? String(header.format || "TEXT").toUpperCase() : "TEXT";
  if (format !== "TEXT" && !MEDIA_FORMATS.includes(format)) return "unsupported_header";
  return null;
}

/** The body with the agent's values put in, as the customer will read it. */
export function renderBody(template, values = {}) {
  const body = part(template?.components || [], "BODY")?.text ?? template?.body_text ?? "";
  return body.replace(VAR, (whole, n) => {
    const v = (values.body || [])[Number(n) - 1];
    return v && String(v).trim() ? String(v) : whole;
  });
}

const isHttps = (s) => /^https:\/\/\S+$/i.test(String(s || "").trim());

/**
 * Check what the agent filled in.
 * @returns {{ ok: true, vars: object, language: string } | { ok: false, errors: Record<string,string> }}
 * `errors` is keyed by field: "body.1", "header.1", "header.media", "button.0".
 */
export function buildSend(template, values = {}, t = (k) => k) {
  const reason = cannotSendReason(template);
  if (reason) return { ok: false, errors: { template: reason } };
  const shape = formShape(template);
  const errors = {};
  const vars = {};

  const body = shape.bodySlots.map((n, i) => String((values.body || [])[i] ?? "").trim());
  shape.bodySlots.forEach((n, i) => { if (!body[i]) errors[`body.${n}`] = t("required"); });
  if (body.length) vars.body_params = body;

  if (shape.header?.kind === "text" && shape.header.slots) {
    const v = String((values.header || [])[0] ?? "").trim();
    if (!v) errors["header.1"] = t("required");
    else vars.header_params = [v];
  } else if (shape.header && shape.header.kind !== "text") {
    const link = String(values.headerMedia?.link ?? "").trim();
    if (!isHttps(link)) errors["header.media"] = t("https");
    else {
      vars.header_media = { type: shape.header.kind, link };
      const filename = String(values.headerMedia?.filename ?? "").trim();
      if (shape.header.kind === "document" && filename) vars.header_media.filename = filename;
    }
  }

  const buttonParams = [];
  for (const b of shape.buttons) {
    if (!b.needsInput) continue;
    if (b.type === "quick_reply") {
      // A quick reply returns its payload when tapped: the label is a sensible default.
      const payload = String((values.buttons || {})[b.index] ?? b.text).trim();
      if (!payload) errors[`button.${b.index}`] = t("required");
      else buttonParams.push({ index: b.index, type: "quick_reply", payload });
    } else {
      const text = String((values.buttons || {})[b.index] ?? "").trim();
      if (!text) errors[`button.${b.index}`] = t("required");
      else buttonParams.push({ index: b.index, type: "url", text });
    }
  }
  if (buttonParams.length) vars.button_params = buttonParams;

  if (Object.keys(errors).length) return { ok: false, errors };
  return { ok: true, vars, language: template.language || "ar" };
}
