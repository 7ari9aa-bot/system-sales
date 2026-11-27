/**
 * One vocabulary for what a channel capability can do, shared by every channel screen.
 *
 * The backend already decides each state from measured facts (granted scopes, the asset
 * subscription, and the webhook fields Meta actually delivered). This file only names them and
 * turns them into a decision a control can use, so a dead button is explained instead of shown,
 * and so no screen invents its own wording for the same state.
 */

/** States that mean the capability works today. */
const WORKING = new Set(["available"]);

/** Every state the backend can report, with the label an owner should read. */
export const STATE_LABELS = {
  available: ["متاح", "Available"],
  needs_permission: ["يتطلب صلاحية", "Needs permission"],
  needs_advanced_access: ["يتطلب Advanced Access", "Needs Advanced Access"],
  needs_app_review: ["يتطلب App Review", "Needs App Review"],
  account_ineligible: ["الحساب غير مؤهل", "Account ineligible"],
  not_requested: ["لم يُطلب بعد", "Not requested"],
  eligibility_unknown: ["الأهلية غير معروفة بعد", "Eligibility unknown"],
  region_restricted: ["ممنوع في بلدك", "Region restricted"],
  unsupported_by_api: ["ميتا لا تدعمه", "Not supported by Meta"],
  not_implemented: ["غير منفَّذ عندنا بعد", "Not built yet"],
  needs_connection: ["يتطلب ربط القناة", "Not connected"],
  temporary_failure: ["فشل مؤقت", "Temporary failure"],
  no_live_event_verified: ["لم نجرّبه بعد", "No live event yet"],
  dashboard_field_missing: ["الحقل غير مفعّل في لوحة Meta", "Dashboard field missing"],
  asset_subscription_missing: ["الصفحة/الحساب غير مشترك في الحقل", "Asset subscription missing"],
};

/** What each capability is called, in the owner's words. */
export const CAPABILITY_LABELS = {
  inbox: ["الرسائل", "Messages"],
  staff_reply_sync: ["ردود فريقك من Meta Business Suite", "Staff replies from Meta Business Suite"],
  handover: ["تسليم المحادثة لإنسان", "Hand a thread to a human"],
  message_edit: ["تعديل رسالة", "Message edits"],
  reactions: ["التفاعلات", "Reactions"],
  profile_settings: ["إعدادات صفحة المراسلة", "Messenger profile settings"],
  inbox_labels: ["تصنيفات المحادثات", "Inbox labels"],
  conversation_history: ["قراءة المحادثات السابقة", "Earlier conversations"],
  marketing_optin: ["موافقة الرسائل التسويقية", "Marketing message opt-in"],
  posts: ["المنشورات", "Posts"],
  comments: ["التعليقات", "Comments"],
  mentions: ["الإشارات إليك", "Mentions"],
  insights: ["الأرقام والتحليلات", "Insights"],
  direct: ["الرسائل الخاصة", "Direct messages"],
  live_comments: ["تعليقات البث المباشر", "Live comments"],
  story_insights: ["أرقام الستوري", "Story insights"],
  publishing: ["النشر", "Publishing"],
  reels_publishing: ["نشر الريلز", "Reel publishing"],
  stories_publishing: ["نشر الستوري", "Story publishing"],
  messages: ["الرسائل", "Messages"],
  templates: ["القوالب", "Templates"],
  account_alerts: ["تنبيهات الحساب", "Account alerts"],
  number_quality: ["جودة الرقم", "Number quality"],
  flows: ["Flows", "Flows"],
  catalog_messages: ["الكتالوج والمنتجات", "Catalog and products"],
  coexistence: ["Coexistence", "Coexistence"],
  calls: ["المكالمات", "Calls"],
};

/** The label of one state, falling back to the key so an unknown state is never blank. */
export function stateLabel(state, isAr) {
  const pair = STATE_LABELS[state];
  return pair ? pair[isAr ? 0 : 1] : String(state || "");
}

/** The label of one capability, falling back to the key. */
export function capabilityLabel(key, isAr) {
  const pair = CAPABILITY_LABELS[key];
  return pair ? pair[isAr ? 0 : 1] : String(key || "");
}

/**
 * Whether a control for this capability may be used, and why not.
 *
 * `capabilities` is the list the diagnostics report carries; a capability the report did not
 * mention is `unknown` — the screen must not treat silence as permission.
 */
export function capabilityNotice(capabilities, key, isAr) {
  const found = (Array.isArray(capabilities) ? capabilities : []).find((c) => c?.key === key);
  if (!found) {
    return {
      known: false,
      state: "unknown",
      enabled: false,
      label: isAr ? "غير معروف" : "Unknown",
      reason: isAr ? "لا يوجد تقرير عن هذه الوظيفة" : "No report for this capability",
    };
  }
  const enabled = WORKING.has(found.state);
  const state = String(found.state || "");
  return {
    known: true,
    state,
    enabled,
    label: stateLabel(state, isAr),
    // The backend's reason is Meta's own wording or ours; shown as it came, never rewritten.
    reason: found.reason || (enabled ? "" : isAr ? "الوظيفة غير جاهزة" : "This capability is not ready"),
  };
}

/** The capabilities worth showing: what is broken or unproven first, then what works. */
export function sortCapabilities(capabilities) {
  const rank = (state) => (WORKING.has(state) ? 2 : state === "not_implemented" ? 1 : 0);
  return [...(Array.isArray(capabilities) ? capabilities : [])]
    .map((capability, index) => ({ capability, index }))
    .sort((a, b) => rank(a.capability?.state) - rank(b.capability?.state) || a.index - b.index)
    .map(({ capability }) => capability);
}
