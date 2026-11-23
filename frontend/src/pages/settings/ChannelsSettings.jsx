import React from "react";
import { Copy, Loader2, LinkIcon, ShieldCheck, Unplug } from "lucide-react";
import { useI18n, useT } from "@/lib/i18n";
import ChannelDiagnostics from "@/pages/settings/ChannelDiagnostics";
import FacebookRelinkNotice, { facebookNeedsRelink } from "@/pages/settings/FacebookRelinkNotice";
import MetaPageChoiceDialog from "@/pages/settings/MetaPageChoiceDialog";
import { api } from "@/lib/api";
import { useRealChannels } from "@/hooks/useRealData";
import SettingsShell, { SettingCard } from "@/components/settings/SettingsShell";
import ChannelIcon from "@/components/dashboard/ChannelIcon";
import { Badge } from "@/components/dashboard/ui";

const CONNECTION_FIELDS = {
  whatsapp: [
    { name: "phone_number_id", type: "text", label: ["معرّف رقم الهاتف", "Phone number ID"] },
    { name: "access_token", type: "password", label: ["رمز الوصول", "Access token"] },
  ],
  facebook: [
    { name: "page_id", type: "text", label: ["معرّف الصفحة", "Page ID"] },
    { name: "page_access_token", type: "password", label: ["رمز وصول الصفحة", "Page access token"] },
  ],
  instagram: [
    { name: "account_id", type: "text", label: ["معرّف الحساب", "Account ID"] },
    { name: "api_key", type: "password", label: ["رمز وصول الحساب", "Account access token"] },
  ],
  messenger: [
    { name: "api_key", type: "password", label: ["رمز وصول صفحة فيسبوك", "Facebook Page access token"] },
  ],
  telegram: [
    { name: "bot_token", type: "password", label: ["رمز البوت", "Bot token"] },
  ],
  webchat: [],
};

const ATTENTION_STATES = new Set(["reauth_required", "restricted", "disconnected", "degraded", "error"]);

/** Channels that use Meta OAuth popup flow (Instagram, Messenger, Facebook). */
const META_OAUTH_CHANNELS = new Set(["messenger", "instagram", "facebook"]);

/** WhatsApp Embedded Signup event type from Meta's JS SDK. */
const WA_SIGNUP_EVENT = "WA_EMBEDDED_SIGNUP";

/** Meta OAuth popup result event type (sent by our callback page). */
const META_OAUTH_RESULT = "META_OAUTH_RESULT";

/**
 * The Facebook SDK script address, in the owner's language.
 *
 * The locale used to be fixed to en_US, so an Arabic-speaking owner pressed a Connect button in
 * Arabic and then met Meta's login and permission dialogs in English, in the one window where they
 * decide what to grant. The SDK takes the dialog language from the script it was loaded from, so a
 * language switched after the SDK has loaded applies from the next page load.
 */
export function facebookSdkUrl(isAr) {
  return `https://connect.facebook.net/${isAr ? "ar_AR" : "en_US"}/sdk.js`;
}

export function loadFacebookSdk(appId, version, isAr) {
  return new Promise((resolve, reject) => {
    const configKey = `${appId}:${version}`;
    const init = () => {
      if (!window.FB) {
        reject(new Error(isAr ? "لم تكتمل تهيئة Facebook SDK." : "Facebook SDK did not initialize."));
        return;
      }
      if (window.__fihristMetaSdkConfig !== configKey) {
        try {
          window.FB.init({ appId, cookie: true, xfbml: true, version });
          window.__fihristMetaSdkConfig = configKey;
        } catch {
          reject(new Error(isAr ? "تعذرت تهيئة Facebook SDK." : "Could not initialize Facebook SDK."));
          return;
        }
      }
      resolve(window.FB);
    };

    if (window.FB) {
      init();
      return;
    }

    const script = document.querySelector?.("script[data-fihrist-meta-sdk]") || document.createElement("script");
    const setTimer = window.setTimeout?.bind(window) || setTimeout;
    const clearTimer = window.clearTimeout?.bind(window) || clearTimeout;
    const timer = setTimer(() => {
      reject(new Error(isAr ? "انتهت مهلة تحميل Facebook SDK. أعد المحاولة." : "Facebook SDK timed out. Try again."));
    }, 15_000);
    window.fbAsyncInit = () => {
      clearTimer(timer);
      init();
    };
    script.onerror = () => {
      clearTimer(timer);
      reject(
        new Error(
          isAr
            ? "تعذر تحميل Facebook SDK — إذا كنت تستخدم مانع إعلانات (AdBlocker) يرجى إيقافه مؤقتًا لهذه الصفحة ثم إعادة المحاولة."
            : "Could not load the Facebook SDK — if using an AdBlocker, please disable it for this page and retry."
        )
      )
    };
    if (!script.src) {
      script.src = facebookSdkUrl(isAr);
      script.async = true;
      script.defer = true;
      script.crossOrigin = "anonymous";
      if (script.dataset) script.dataset.fihristMetaSdk = "true";
      document.body.appendChild(script);
    }
  });
}

export function isMetaSdkOrigin(origin) {
  try {
    const { protocol, hostname } = new URL(origin);
    return (
      protocol === "https:" &&
      (hostname === "facebook.com" ||
        hostname.endsWith(".facebook.com") ||
        hostname === "fb.com" ||
        hostname.endsWith(".fb.com"))
    );
  } catch {
    return false;
  }
}

/**
 * A WhatsApp Embedded Signup message we may act on (W11).
 *
 * `isMetaSdkOrigin` alone let any frame that can name a Meta origin talk this page into accepting a
 * code. The signup itself runs in a popup the SDK opens, so the message must come FROM another
 * browsing context: a message with no source, or one this page posted to itself, is not the popup.
 * The host set stays Meta-owned on purpose — a `*.facebook.com` name cannot be registered by anyone
 * else, so it is the source check, not the host list, that is the gate here.
 */
export function isMetaSignupMessage(event) {
  if (!event || !isMetaSdkOrigin(event.origin)) return false;
  const source = event.source;
  if (!source) return false;
  const self = typeof window === "undefined" ? null : window;
  return self === null || source !== self;
}

/** Map channel connect or OAuth error strings to actionable sentences. */
function friendlyChannelError(raw, isAr) {
  const detail = String(raw || "");
  if (detail.includes("plan does not include this channel")) {
    return isAr
      ? "باقتك السابقة لم تكن تشمل هذه القناة (باقة Starter تشمل واتساب وشات الموقع فقط). تم ترقية باقتك إلى Enterprise بنجاح — أعد المحاولة الآن وسيتم الربط."
      : "Your previous plan did not include this channel. Your plan has been upgraded to Enterprise — retry now to connect.";
  }
  if (detail.includes("Telegram rejected this bot token") || detail.includes("rejected these credentials")) {
    return isAr
      ? "رمز البوت غير صحيح أو تم رفضه من قِبل المزود. تأكد من نسخ الرمز بالكامل وبدقة من @BotFather."
      : "The bot token was rejected by the provider. Please verify and copy the complete token.";
  }
  if (detail.includes("Telegram webhook security is not configured")) {
    return isAr
      ? "إعداد أمان ويبهوك تيليجرام غير مكتمل على الخادم."
      : "Telegram webhook security is not configured on the server.";
  }
  if (detail.includes("Could not reach Telegram")) {
    return isAr
      ? "تعذر الاتصال بخوادم تيليجرام للتحقق من الاتصال. يرجى إعادة المحاولة."
      : "Could not reach Telegram to verify the connection. Please try again.";
  }
  return friendlyMetaError(detail, isAr);
}

export function isMetaOAuthPopupMessage(event, popup, origin) {
  return event?.origin === origin && event?.source === popup;
}

export function extractWhatsAppSignupIds(session) {
  const messagingAccountIds = Array.isArray(session?.messaging_account_ids)
    ? session.messaging_account_ids
    : [];
  return {
    wabaId: String(session?.waba_id || session?.wabaId || messagingAccountIds[0] || ""),
    phoneNumberId: String(session?.phone_number_id || session?.phoneNumberId || ""),
  };
}

/** Map the marker the OAuth callback appended onto a sentence the operator can act on. */
export function friendlyMetaError(raw, isAr) {
  const detail = String(raw || "");
  if (detail.includes("Invalid Scopes") || detail.includes("instagram_basic")) {
    return isAr
      ? "تطبيق Meta ينقصه صلاحيات إنستجرام: يرجى إضافة منتج Instagram Graph API وصلاحيات instagram_basic وinstagram_manage_messages في لوحة مطوري Meta (developers.facebook.com)."
      : "The Meta app is missing Instagram permissions: add Instagram Graph API and permissions (instagram_basic, instagram_manage_messages) in Meta Developer Console.";
  }
  if (detail.includes("No messaging-capable page") || detail.includes("لم يتم العثور على أي صفحة")) {
    return isAr
      ? "لم يتم العثور على أي صفحة فيسبوك تدعم المراسلة في حسابك، أو لم يتم تحديد الصفحة أثناء منح الصلاحيات."
      : "No messaging-capable Facebook page was authorized on your account.";
  }
  if (detail.includes("غير مرتبطة بحساب إنستجرام") || detail.includes("No Instagram professional account")) {
    return isAr
      ? "صفحة فيسبوك غير مرتبطة بحساب إنستجرام احترافي — يرجى ربط حساب إنستجرام بالصفحة أولاً من Meta Business Suite."
      : "No Instagram professional account is linked to the authorized Facebook page.";
  }
  if (detail.startsWith("access_denied")) {
    return isAr
      ? "لم تُمنح صلاحيات فيسبوك: إما أن الموافقة أُلغيت، أو التطبيق في وضع التطوير وحسابك ليس Tester أو Admin عليه. أضف الحساب من Meta Developer Console ثم أعد المحاولة."
      : "Meta did not grant the permissions: either the consent was cancelled, or the app is in development mode and your account is not a tester or admin of it. Add the account in the Meta Developer Console, then retry.";
  }
  if (detail.includes("redirect_uri")) {
    return isAr
      ? "رابط العودة غير مسجّل في تطبيق فيسبوك: أضف الرابط الظاهر في رسالة الخطأ إلى Valid OAuth Redirect URIs (التفاصيل في docs/META_SETUP.md)."
      : "The redirect URI is not whitelisted on the Meta app: add the exact URL from the error to Valid OAuth Redirect URIs (see docs/META_SETUP.md).";
  }
  if (detail === "invalid_state") {
    return isAr
      ? "انتهت صلاحية نافذة ربط فيسبوك (عشر دقائق). أعد المحاولة من الزر."
      : "The Facebook connect window (10 minutes) expired. Press connect again.";
  }
  if (detail === "missing_code_or_state" || detail === "invalid_provider") {
    return isAr
      ? "أُلغيت العملية أو عاد ربط فيسبوك بلا بيانات مكتملة. أعد المحاولة."
      : "The Facebook connect returned without a complete response. Retry.";
  }
  if (detail.startsWith("meta_unavailable")) {
    // Meta (or the path to it) was down or rate limiting. Nothing is wrong with the setup.
    return isAr
      ? "خوادم فيسبوك لا تستجيب الآن. هذه ليست مشكلة في الإعدادات، أعد المحاولة بعد دقيقة."
      : "Meta is not responding right now. This is not a setup problem. Try again in a minute.";
  }
  if (detail.startsWith("meta_exchange_failed")) {
    return isAr
      ? "فشل تبادل رمز التفويض مع خوادم فيسبوك. تحقق من إعدادات التطبيق ثم أعد المحاولة."
      : "The authorization code could not be exchanged with Meta. Check the app settings, then retry.";
  }
  return detail;
}

/** Open a centered popup window. */
/**
 * How long the one-time code may wait for the signup window to report the new number.
 *
 * Meta's authorization code lives about five minutes, and the connect only goes to the server when
 * the code AND the window's own report have both arrived. The report used to be allowed ten minutes,
 * so an owner who lingered in the window held a code that had already died: the server then said
 * "Meta rejected the authorization code" about a number that was in fact created. Give up a little
 * inside the code's life and say what happened instead.
 */
export const SIGNUP_REPORT_WAIT_MS = 4 * 60 * 1000;

/** The whole signup window, from opening it to the report. Longer than the code's wait on purpose. */
export const SIGNUP_WINDOW_MS = 10 * 60 * 1000;

/** What the owner is told when the code outlived the wait for the signup report. */
export function signupCodeExpiredError(isAr) {
  return new Error(
    isAr
      ? "انتهت صلاحية رمز التفويض قبل أن تكتمل الخطوات في نافذة فيسبوك. أعد المحاولة وأكملها خلال دقائق قليلة."
      : "The authorization expired before the steps in the Facebook window were finished. Try again and finish them within a few minutes."
  );
}

/**
 * What to tell the owner when Meta's signup window reports CANCEL or ERROR.
 *
 * Both used to read "cancelled", so a refusal by Meta looked like the owner closing the window and
 * the reason (and the id support needs) was thrown away. A CANCEL names the step the owner left on;
 * an ERROR carries Meta's own message and ids, shown as they are.
 */
export function whatsappSignupInterruption(payload, isAr) {
  const data = payload?.data && typeof payload.data === "object" ? payload.data : {};
  const text = (value) => (typeof value === "string" || typeof value === "number" ? String(value).trim() : "");
  if (payload?.event === "ERROR") {
    const message = text(data.error_message);
    const code = text(data.error_id) || text(data.error_code);
    const session = text(data.session_id);
    const reference = [code && `${isAr ? "رمز" : "code"} ${code}`, session && `${isAr ? "جلسة" : "session"} ${session}`]
      .filter(Boolean)
      .join(" · ");
    const head = isAr ? "رفضت Meta إكمال ربط واتساب." : "Meta could not complete the WhatsApp signup.";
    const body = message || (isAr ? "لم تذكر Meta السبب." : "Meta gave no reason.");
    return new Error(`${head} ${body}${reference ? ` (${reference})` : ""}`);
  }
  const step = text(data.current_step);
  if (step) {
    return new Error(
      isAr
        ? `أُغلقت نافذة الربط عند الخطوة "${step}" قبل اكتمالها.`
        : `The signup window was closed at the "${step}" step, before it finished.`
    );
  }
  return new Error(isAr ? "أُغلقت نافذة الربط قبل اكتمالها." : "The signup window was closed before it finished.");
}

/** What FB.login's answer means for the WhatsApp connect.
 *  Facebook calls back as soon as its window is closed or refused, with no code. That is final, so
 *  the button must be freed now, like Facebook/Messenger/Instagram do when their window closes, and
 *  not after the 10 minute signup timeout. A window that stopped on a message from Meta itself
 *  ("can't onboard customers right now") ends here too, so the reason names the Meta app. */
export function whatsappLoginOutcome(response, isAr) {
  const code = response?.authResponse?.code;
  if (code) return { code };
  return {
    error: new Error(isAr
      ? "لم يكتمل الربط في نافذة فيسبوك. إن توقفت النافذة عند عبارة «ليس بإمكان التطبيق تأهيل العملاء الآن» فهذا إعداد تطبيق ميتا نفسه (التحقق من النشاط التجاري وTech Provider ومراجعة التطبيق) وليس عطلًا هنا، وتفاصيله في docs/META_SETUP.md. وإن ظهرت «App not active» فالتطبيق غير مفعّل. غير ذلك أعد المحاولة."
      : "The Facebook window closed before the connect finished. If it stopped on \"can't onboard customers right now\", that is the Meta app's own setup (business verification, Tech Provider, App Review), not a fault here; see docs/META_SETUP.md. If it said \"App not active\", the app is switched off. Otherwise try again."),
  };
}

/** A line shown under the "Connecting…" banner once WhatsApp has waited long enough that the window is
 *  probably parked on a message from Meta. Facebook/Messenger/Instagram watch their window and free the
 *  button when it closes; WhatsApp's Facebook window gives no signal while it sits on that message, so
 *  without this the page just spins. */
export const CONNECTING_HINT_AFTER_MS = 45_000;
export function connectingHint(elapsedMs, channelId, isAr) {
  if (channelId !== "whatsapp" || elapsedMs < CONNECTING_HINT_AFTER_MS) return "";
  return isAr
    ? "لو توقفت نافذة فيسبوك عند رسالة من ميتا مثل «ليس بإمكان التطبيق تأهيل العملاء الآن» فهذا إعداد تطبيق ميتا (التحقق من النشاط التجاري وTech Provider ومراجعة التطبيق) وليس عطلًا هنا. أغلق النافذة وراجع docs/META_SETUP.md، وانسخ Session ID من أسفلها لدعم ميتا."
    : "If the Facebook window stopped on a message from Meta such as \"can't onboard customers right now\", that is the Meta app's own setup (business verification, Tech Provider, App Review), not a fault here. Close the window, see docs/META_SETUP.md, and copy the Session ID at its bottom for Meta Support.";
}

function openCenteredPopup(url, name, w = 600, h = 700) {
  const left = window.screenX + (window.outerWidth - w) / 2;
  const top = window.screenY + (window.outerHeight - h) / 2;
  return window.open(
    url,
    name,
    `width=${w},height=${h},left=${Math.max(0, left)},top=${Math.max(0, top)},scrollbars=yes,resizable=yes`
  );
}

function withTimeout(promise, timeoutMs, message) {
  let timer;
  return Promise.race([
    promise,
    new Promise((_, reject) => {
      timer = window.setTimeout(() => reject(new Error(message)), timeoutMs);
    }),
  ]).finally(() => window.clearTimeout(timer));
}

export default function ChannelsSettings() {
  const t = useT();
  const { lang } = useI18n();
  const isAr = lang === "ar";
  const { channels, loading, error, reload } = useRealChannels();
  const [editingId, setEditingId] = React.useState("");
  const [values, setValues] = React.useState({});
  const [saving, setSaving] = React.useState(false);
  const [verifyingId, setVerifyingId] = React.useState("");
  const [metaConnecting, setMetaConnecting] = React.useState("");
  const [connectingMs, setConnectingMs] = React.useState(0);
  React.useEffect(() => {
    if (!metaConnecting) { setConnectingMs(0); return undefined; }
    const startedAt = Date.now();
    const tick = window.setInterval(() => setConnectingMs(Date.now() - startedAt), 5000);
    return () => window.clearInterval(tick);
  }, [metaConnecting]);
  const [whatsappSdkLoading, setWhatsappSdkLoading] = React.useState(true);
  const [whatsappSdkError, setWhatsappSdkError] = React.useState("");
  const whatsappSignupRef = React.useRef(null);
  const metaPopupRef = React.useRef(null);
  const metaPollTimerRef = React.useRef(null);
  const metaTimeoutRef = React.useRef(null);
  const [formError, setFormError] = React.useState("");
  // The owner ticked several Pages: the connect waits here for the one to use.
  const [pageChoice, setPageChoice] = React.useState(null);
  const [pageChoiceBusy, setPageChoiceBusy] = React.useState(false);
  const [pageChoiceError, setPageChoiceError] = React.useState("");
  const [notice, setNotice] = React.useState("");
  const [copiedTarget, setCopiedTarget] = React.useState("");

  const editing = channels.find((channel) => channel.id === editingId) || null;

  const clearMetaConnectTimers = React.useCallback((closePopup = false) => {
    if (metaPollTimerRef.current) window.clearInterval(metaPollTimerRef.current);
    if (metaTimeoutRef.current) window.clearTimeout(metaTimeoutRef.current);
    metaPollTimerRef.current = null;
    metaTimeoutRef.current = null;
    const popup = metaPopupRef.current;
    metaPopupRef.current = null;
    if (closePopup && popup && !popup.closed) popup.close();
  }, []);

  React.useEffect(() => () => clearMetaConnectTimers(true), [clearMetaConnectTimers]);

  async function choosePage(pageId) {
    if (!pageChoice) return;
    setPageChoiceBusy(true);
    setPageChoiceError("");
    try {
      const result = await api("/integrations/meta/oauth/choose-page", {
        method: "POST",
        body: { ticket: pageChoice.ticket, page_id: pageId },
      });
      const connected = String(result?.connected || "");
      const pageName = connected.includes(":") ? connected.slice(connected.indexOf(":") + 1) : connected;
      setPageChoice(null);
      setNotice(
        isAr
          ? `تم ربط صفحة ${pageName || "فيسبوك"} بنجاح.`
          : `Connected the page ${pageName || "Facebook"} successfully.`
      );
      setFormError("");
      void reload().catch(() => {});
    } catch (chooseError) {
      // The ticket works once, so a refusal means pressing connect again; say so plainly.
      setPageChoiceError(chooseError?.message || (isAr ? "تعذر ربط الصفحة. اضغط ربط من جديد." : "Could not connect that Page. Press connect again."));
    } finally {
      setPageChoiceBusy(false);
    }
  }

  function cancelPageChoice() {
    setPageChoice(null);
    setPageChoiceError("");
  }

  // Load Meta's config and SDK before the operator presses Connect. FB.login
  // opens Meta's consent popup, so waiting for network/SDK work inside the
  // click handler loses the browser's short-lived user activation.
  React.useEffect(() => {
    let mounted = true;
    setWhatsappSdkLoading(true);
    void api("/integrations/whatsapp/embedded-signup/start")
      .then(async (config) => {
        if (!config?.app_id || !config?.config_id) {
          throw new Error(
            "WhatsApp connect is not configured on the server: set META_WHATSAPP_CONFIG_ID (see docs/META_SETUP.md)."
          );
        }
        const fb = await loadFacebookSdk(config.app_id, config.graph_version || "v27.0", isAr);
        return { fb, configId: config.config_id };
      })
      .then((prepared) => {
        if (!mounted) return;
        whatsappSignupRef.current = prepared;
        setWhatsappSdkError("");
      })
      .catch((prepareError) => {
        if (!mounted) return;
        whatsappSignupRef.current = null;
        setWhatsappSdkError(prepareError?.message || "Could not prepare WhatsApp signup.");
      })
      .finally(() => {
        if (mounted) setWhatsappSdkLoading(false);
      });
    return () => {
      mounted = false;
      whatsappSignupRef.current = null;
    };
  }, [isAr]);

  // Listen for Meta OAuth popup results (postMessage / BroadcastChannel / storage).
  React.useEffect(() => {
    function handleResult(data) {
      if (!data || data.type !== META_OAUTH_RESULT) return;
      clearMetaConnectTimers(true);
      const { connected, error: oauthError, choose } = data;
      if (choose && typeof choose.ticket === "string" && Array.isArray(choose.pages) && choose.pages.length > 1) {
        setPageChoice({
          ticket: choose.ticket,
          provider: choose.provider,
          pages: choose.pages.map((page) => ({ id: String(page.id), name: String(page.name || page.id) })),
        });
        setPageChoiceError("");
        setFormError("");
        setMetaConnecting("");
        return;
      }
      if (connected) {
        const sep = connected.indexOf(":");
        const pageName = sep === -1 ? connected : connected.slice(sep + 1);
        setNotice(
          isAr
            ? `تم ربط صفحة ${pageName || "فيسبوك"} بنجاح.`
            : `Connected the page ${pageName || "Facebook"} successfully.`
        );
        setFormError("");
      } else if (oauthError) {
        setFormError(
          isAr
            ? `تعذر إكمال الربط: ${friendlyMetaError(oauthError, isAr)}`
            : `Could not complete the connect: ${friendlyMetaError(oauthError, isAr)}`
        );
      }
      setMetaConnecting("");
      void reload().catch(() => {});
    }

    function onMessage(event) {
      if (!isMetaOAuthPopupMessage(event, metaPopupRef.current, window.location.origin)) return;
      handleResult(event.data);
    }

    function onStorage(event) {
      if (event.key === "meta_oauth_result" && event.newValue) {
        try {
          const parsed = JSON.parse(event.newValue);
          localStorage.removeItem("meta_oauth_result");
          handleResult(parsed);
        } catch {}
      }
    }

    let bc = null;
    try {
      bc = new BroadcastChannel("meta_oauth");
      bc.onmessage = (event) => handleResult(event.data);
    } catch {}

    window.addEventListener("message", onMessage);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener("message", onMessage);
      window.removeEventListener("storage", onStorage);
      if (bc) bc.close();
    };
  }, [reload, isAr, clearMetaConnectTimers]);

  // Also handle legacy URL params (in case the popup was blocked and the
  // callback redirected instead).
  const oauthHandled = React.useRef(false);
  React.useEffect(() => {
    if (oauthHandled.current) return;
    oauthHandled.current = true;
    const params = new URLSearchParams(window.location.search);
    const connected = params.get("meta_connected");
    const oauthError = params.get("meta_error");
    if (!connected && !oauthError) return;
    params.delete("meta_connected");
    params.delete("meta_error");
    const rest = params.toString();
    window.history.replaceState(null, "", window.location.pathname + (rest ? `?${rest}` : ""));
    if (connected) {
      const sep = connected.indexOf(":");
      const pageName = sep === -1 ? connected : connected.slice(sep + 1);
      setNotice(isAr
        ? `تم ربط صفحة ${pageName || "فيسبوك"} بنجاح.`
        : `Connected the page ${pageName || "Facebook"} successfully.`);
    } else {
      setFormError(isAr
        ? `تعذر إكمال الربط: ${friendlyMetaError(oauthError, isAr)}`
        : `Could not complete the connect: ${friendlyMetaError(oauthError, isAr)}`);
    }
    void reload().catch(() => {});
  }, [reload, isAr]);

  /** Connect WhatsApp via Embedded Signup (JS SDK popup). */
  async function connectWhatsApp(channel) {
    if (metaConnecting) return;
    const prepared = whatsappSignupRef.current;
    if (!prepared) {
      setFormError(whatsappSdkError || (isAr ? "تعذر تجهيز نافذة ربط واتساب. أعد تحميل الصفحة ثم حاول مجددًا." : "WhatsApp signup is not ready. Reload the page and try again."));
      return;
    }
    setMetaConnecting(channel.id);
    setFormError("");
    setNotice("");
    try {
      const { fb, configId } = prepared;

      let resolveCode;
      let rejectCode;
      let rejectSession = () => {};
      let staleCodeTimer = null;
      let signupReported = false;
      let cleanupSignup = () => {};
      const codePromise = new Promise((resolve, reject) => {
        resolveCode = resolve;
        rejectCode = (error) => {
          cleanupSignup();
          reject(error);
        };
      });
      const sessionPromise = new Promise((resolve, reject) => {
        rejectSession = reject;
        const timer = window.setTimeout(() => {
          cleanupSignup();
          reject(new Error(isAr ? "انتهت مدة الربط. أعد المحاولة." : "The signup timed out. Try again."));
        }, SIGNUP_WINDOW_MS);

        function onMessage(event) {
          if (!isMetaSignupMessage(event)) return;
          let payload;
          try {
            payload = typeof event.data === "string" ? JSON.parse(event.data) : event.data;
          } catch {
            return;
          }
          if (payload?.type !== WA_SIGNUP_EVENT) return;
          if (payload.event === "CANCEL" || payload.event === "ERROR") {
            cleanupSignup();
            reject(whatsappSignupInterruption(payload, isAr));
            return;
          }
          if (payload.event === "FINISH") {
            signupReported = true;
            cleanupSignup();
            resolve(payload.data || {});
          } else if (payload.event === "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING") {
            cleanupSignup();
            reject(new Error(
              isAr
                ? "هذا الرقم مربوط حاليًا بتطبيق WhatsApp Business. افصل التطبيق أو أعد المحاولة برقم مؤهل لـCloud API."
                : "This number is connected to the WhatsApp Business app. Disconnect it or retry with a number eligible for Cloud API."
            ));
          }
        }

        cleanupSignup = () => {
          window.clearTimeout(timer);
          if (staleCodeTimer) window.clearTimeout(staleCodeTimer);
          window.removeEventListener("message", onMessage);
        };
        window.addEventListener("message", onMessage);
        fb.login(
          (response) => {
            const outcome = whatsappLoginOutcome(response, isAr);
            if (outcome.code) {
              resolveCode(outcome.code);
              // The code is alive for about five minutes; from now the report has until then.
              // When the report came first there is nothing left to wait for, so no timer starts.
              if (!signupReported) {
                staleCodeTimer = window.setTimeout(() => {
                  cleanupSignup();
                  rejectSession(signupCodeExpiredError(isAr));
                }, SIGNUP_REPORT_WAIT_MS);
              }
            } else {
              rejectCode(outcome.error);
            }
          },
          {
            config_id: configId,
            response_type: "code",
            override_default_response_type: true,
            extras: {
              setup: {},
              version: "v5",
              features: [{ name: "whatsapp_business_app_onboarding", enabled: false }],
            },
          }
        );
      });

      let authCode;
      let session;
      try {
        [authCode, session] = await Promise.all([codePromise, sessionPromise]);
      } finally {
        cleanupSignup();
      }
      const { wabaId, phoneNumberId } = extractWhatsAppSignupIds(session);
      if (!wabaId || !phoneNumberId) {
        throw new Error(
          isAr
            ? "أكمل خطوات إنشاء رقم واتساب داخل نافذة فيسبوك، ثم أعد المحاولة."
            : "Finish creating the WhatsApp number inside the Facebook window, then retry."
        );
      }
      await api("/integrations/whatsapp/embedded-signup/complete", {
        method: "POST",
        body: { code: authCode, waba_id: wabaId, phone_number_id: phoneNumberId },
      });
      setNotice(isAr ? "تم ربط رقم واتساب بنجاح." : "The WhatsApp number is connected.");
      setMetaConnecting("");
      await reload().catch(() => {});
    } catch (connectError) {
      setFormError(connectError?.message || (isAr ? "تعذر ربط واتساب." : "Could not connect WhatsApp."));
      setMetaConnecting("");
    }
  }

  /** Connect a Meta channel (Instagram/Messenger/Facebook) via popup OAuth. */
  async function connectViaMeta(channel, popup) {
    if (metaConnecting) {
      if (popup && !popup.closed) popup.close();
      return;
    }
    if (!popup || popup.closed) {
      setFormError(isAr
        ? "تعذر فتح نافذة الربط — اسمح بالنوافذ المنبثقة لهذا الموقع ثم أعد المحاولة."
        : "Could not open the connect window. Allow popups for this site, then retry.");
      return;
    }
    metaPopupRef.current = popup;
    setMetaConnecting(channel.id);
    setFormError("");
    setNotice("");
    try {
      const { authorize_url: authorizeUrl } = await withTimeout(
        api(`/integrations/meta/oauth/start?provider=${encodeURIComponent(channel.id)}`),
        30_000,
        isAr ? "استغرق تجهيز نافذة الربط وقتًا أطول من المتوقع. أعد المحاولة." : "Preparing the connect window took too long. Please retry."
      );
      if (!authorizeUrl) {
        throw new Error(isAr ? "لم يصل رابط التفويض من الخادم." : "The server returned no authorize URL.");
      }
      if (!popup || popup.closed) {
        throw new Error(
          isAr
            ? "تعذر فتح نافذة الربط — تأكد من السماح بالنوافذ المنبثقة لهذا الموقع."
            : "Could not open the connect window — make sure popups are allowed for this site."
        );
      }
      // The popup is opened synchronously in the click handler so browser
      // popup blockers keep it attached to the user's gesture.
      popup.location.replace(authorizeUrl);
      metaPollTimerRef.current = window.setInterval(() => {
        if (popup.closed) {
          clearMetaConnectTimers();
          setMetaConnecting((prev) => {
            if (prev === channel.id) return "";
            return prev;
          });
          setFormError(isAr
            ? "أُغلقت نافذة الربط قبل وصول تأكيد. راجع حالة القناة أو أعد المحاولة."
            : "The connect window closed before confirmation arrived. Check the channel status or retry.");
          void reload().catch(() => {});
        }
      }, 800);
      metaTimeoutRef.current = window.setTimeout(() => {
        clearMetaConnectTimers(true);
        setMetaConnecting((prev) => prev === channel.id ? "" : prev);
        setFormError(isAr
          ? "انتهت مهلة ربط القناة. أعد المحاولة من زر الربط."
          : "The channel connection timed out. Start again from the connect button.");
        void reload().catch(() => {});
      }, 10 * 60 * 1000);
    } catch (connectError) {
      clearMetaConnectTimers(true);
      const raw = connectError?.message || "";
      setFormError(
        raw.includes("not configured") || raw.includes("META_")
          ? (isAr
            ? `ربط فيسبوك غير مُعد على الخادم: ${raw}`
            : `Facebook connect is not configured on the server: ${raw}`)
          : (raw || (isAr ? "تعذر بدء الربط." : "Could not start the connect."))
      );
      setMetaConnecting("");
    }
  }

  /** Unified connect handler — routes to the right flow per channel type. */
  function handleConnect(channel) {
    if (channel.id === "whatsapp") {
      connectWhatsApp(channel);
    } else if (META_OAUTH_CHANNELS.has(channel.id)) {
      if (metaConnecting) return;
      const popup = openCenteredPopup("about:blank", "meta_oauth_popup");
      if (!popup || popup.closed) {
        setFormError(isAr
          ? "تعذر فتح نافذة الربط — اسمح بالنوافذ المنبثقة لهذا الموقع ثم أعد المحاولة."
          : "Could not open the connect window. Allow popups for this site, then retry.");
        return;
      }
      connectViaMeta(channel, popup);
    } else {
      // Manual credential entry (Telegram, Webchat)
      openConnection(channel);
    }
  }

  function openConnection(channel) {
    setFormError("");
    setNotice("");
    setCopiedTarget("");
    setEditingId(channel.id);
    setValues(channel.id === "webchat"
      ? { public_key: channel.publicKey || "" }
      : {});
  }

  function closeConnection() {
    if (saving) return;
    setEditingId("");
    setValues({});
    setFormError("");
  }

  async function saveConnection(event) {
    event.preventDefault();
    if (!editing || !CONNECTION_FIELDS[editing.id] || editing.status === "disabled") return;
    setSaving(true);
    setFormError("");
    setNotice("");

    const channelConfig = {};
    const credentials = {};
    if (editing.id === "whatsapp") {
      channelConfig.phone_number_id = String(values.phone_number_id || "").trim();
      credentials.access_token = String(values.access_token || "").trim();
    } else if (editing.id === "facebook") {
      channelConfig.page_id = String(values.page_id || "").trim();
      credentials.page_access_token = String(values.page_access_token || "").trim();
    } else if (editing.id === "instagram") {
      channelConfig.account_id = String(values.account_id || "").trim();
      credentials.api_key = String(values.api_key || "").trim();
    } else if (editing.id === "messenger") {
      credentials.api_key = String(values.api_key || "").trim();
    } else if (editing.id === "telegram") {
      credentials.bot_token = String(values.bot_token || "").trim();
    }

    try {
      await api("/integrations/connect", {
        method: "POST",
        body: { provider: editing.id, credentials, config: channelConfig },
      });
    } catch (saveError) {
      setSaving(false);
      setFormError(friendlyChannelError(saveError?.message, isAr) || (isAr ? "تعذر حفظ إعدادات القناة." : "Could not save channel settings."));
      void reload().catch(() => {});
      return;
    }

    setEditingId("");
    setValues({});
    try {
      await reload();
      setNotice(isAr
        ? "تم التحقق من بيانات الحساب وحفظ الاتصال. حالة استقبال الرسائل موضحة بجوار القناة."
        : "Provider credentials were verified and saved. Webhook reception is shown beside the channel.");
    } catch {
      setNotice(isAr
        ? "تم الحفظ، لكن تعذر تحديث حالة القناة. أعد تحميل الصفحة."
        : "Saved, but the channel status could not be refreshed. Reload the page.");
    } finally {
      setSaving(false);
    }
  }

  async function disconnectConnection(channel) {
    if (!channel.integrationId || saving) return;
    const confirmMessage = isAr
      ? `هل أنت متأكد من فك ارتباط ${t(`channel.${channel.id}`)}؟ سيتوقف تدفق الرسائل عبر هذه القناة.`
      : `Are you sure you want to disconnect ${t(`channel.${channel.id}`)}? Message flow will stop.`;
    if (!window.confirm(confirmMessage)) return;

    setSaving(true);
    setFormError("");
    setNotice("");
    try {
      await api(`/integrations/${encodeURIComponent(channel.integrationId)}/disconnect`, {
        method: "POST",
        body: { confirm: true },
      });
      await reload();
      setNotice(isAr ? "تم فك ارتباط القناة بنجاح." : "Channel disconnected successfully.");
    } catch (err) {
      setFormError(friendlyChannelError(err?.message, isAr) || (isAr ? "تعذر فك ارتباط القناة." : "Could not disconnect channel."));
    } finally {
      setSaving(false);
    }
  }

  async function verifyConnection(channel) {
    if (!channel.integrationId || verifyingId) return;
    setVerifyingId(channel.id);
    setFormError("");
    setNotice("");
    try {
      const result = await api(`/integrations/${encodeURIComponent(channel.integrationId)}/verify`, {
        method: "POST",
      });
      await reload();
      setNotice(result.credentials_verified
        ? (isAr ? "بيانات الحساب صالحة وتم تحديث التحقق." : "Credentials are valid and verification was refreshed.")
        : (result.message || (isAr ? "بيانات الحساب مرفوضة؛ أعد ربط القناة." : "The provider rejected these credentials. Reconnect the channel.")));
    } catch (verifyError) {
      setFormError(friendlyChannelError(verifyError?.message, isAr) || (isAr ? "تعذر التحقق من القناة." : "Could not verify the channel."));
    } finally {
      setVerifyingId("");
    }
  }

  async function copyValue(value, target) {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      setCopiedTarget(target);
      setFormError("");
    } catch {
      setFormError(isAr
        ? "تعذر النسخ تلقائيًا؛ حدّد المفتاح وانسخه يدويًا."
        : "Could not copy automatically. Select and copy the key manually.");
    }
  }

  function statusFor(channel) {
    if (channel.connected) return t("channels.connected");
    if (channel.integrationId && ["active", "connected"].includes(channel.status) && !channel.credentialsVerified) {
      return isAr ? "يتطلب اختبار الاتصال" : "Verification required";
    }
    if (["pending", "connecting"].includes(channel.status)) return isAr ? "جارٍ الإعداد" : "Connecting";
    if (ATTENTION_STATES.has(channel.status)) return t("channels.needsAttention");
    if (channel.status === "disabled") return isAr ? "معطّل نهائيًا" : "Permanently disabled";
    return t("channels.notConnected");
  }

  function webhookStatusFor(channel) {
    const statuses = {
      ready: isAr ? "جاهز لاستقبال رسائل الموقع" : "Ready for website chat",
      receiving: isAr ? "يستقبل Webhooks" : "Receiving webhooks",
      awaiting_first_event: isAr ? "لم يصل أول Webhook بعد" : "Waiting for the first webhook",
      server_setup_required: isAr ? "إعداد Webhook على الخادم مطلوب" : "Server webhook setup required",
    };
    return statuses[channel.webhookStatus] || "";
  }

  /** Whether the channel can be connected via a single-click flow (Meta popup or WA SDK). */
  function hasOneClickConnect(channel) {
    return channel.id === "whatsapp" || META_OAUTH_CHANNELS.has(channel.id);
  }

  return (
    <SettingsShell title={t("channels.title")} subtitle={t("channels.subtitle")}>
      {pageChoice ? (
        <MetaPageChoiceDialog
          choice={pageChoice}
          isAr={isAr}
          busy={pageChoiceBusy}
          error={pageChoiceError}
          onChoose={choosePage}
          onCancel={cancelPageChoice}
        />
      ) : null}
      <SettingCard>
        {error && <div role="alert" className="mb-3 rounded-lg bg-destructive/10 px-3 py-2 text-[12px] text-destructive">{error}</div>}
        {formError && !editingId && <div role="alert" className="mb-3 rounded-lg bg-destructive/10 px-3 py-2 text-[12px] text-destructive">{formError}</div>}
        {notice && <div role="status" className="mb-3 text-[12px] text-primary">{notice}</div>}
        {metaConnecting && <div role="status" aria-live="polite" className="mb-3 flex items-start gap-2 text-[12px] leading-relaxed text-primary">
          <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin" />
          <span>{isAr
            ? `جارٍ فتح نافذة ربط ${t(`channel.${metaConnecting}`)}. أكمل خطوات تسجيل الدخول فيها بعد ظهورها؛ ستظهر هنا نتيجة الربط.`
            : `Opening the ${t(`channel.${metaConnecting}`)} connect window. Complete sign-in there when it appears; the result will show here.`}
            {connectingHint(connectingMs, metaConnecting, isAr) && <span className="mt-1 block text-amber-700" data-testid="connecting-hint">{connectingHint(connectingMs, metaConnecting, isAr)}</span>}</span>
        </div>}

        {loading && channels.length === 0 ? (
          <div className="py-8 text-center text-[13px] text-muted-foreground">{isAr ? "جارٍ تحميل القنوات…" : "Loading channels…"}</div>
        ) : (
          <div className="divide-y divide-border">
            {channels.map((channel) => {
              const status = statusFor(channel);
              const needsAttention = ATTENTION_STATES.has(channel.status);
              const needsVerification = channel.integrationId && ["active", "connected"].includes(channel.status) && !channel.credentialsVerified;
              const needsRelink = facebookNeedsRelink(channel);
              const terminal = channel.status === "disabled";
              const fields = CONNECTION_FIELDS[channel.id];
              const isConnected = channel.connected || channel.webhookStatus === "receiving";
              const isConnecting = metaConnecting === channel.id;
              const localizedChannelName = t(`channel.${channel.id}`);
              const displayName = channel.id === "webchat" && channel.displayName?.trim().toLowerCase() === "website chat"
                ? localizedChannelName
                : channel.displayName?.trim();

              return (
                <div key={channel.id} className="py-3.5 first:pt-1 last:pb-1">
                  {/* Main channel row — RTL aligned */}
                  <div className="flex flex-wrap items-center gap-3" style={{ direction: isAr ? "rtl" : "ltr" }}>
                    <ChannelIcon channel={channel.id} />
                    <div className="min-w-0 flex-1">
                      <div className="text-[13.5px] font-medium">{localizedChannelName}</div>
                      <div className="text-[12px] text-muted-foreground">{status}</div>
                      {displayName && displayName !== localizedChannelName && <div className="text-[11px] text-muted-foreground">{displayName}</div>}
                      <FacebookRelinkNotice channel={channel} isAr={isAr} />
                      <ChannelDiagnostics channel={channel} isAr={isAr} />
                      {channel.integrationId && (
                        <div className="mt-1 text-[11px] text-muted-foreground">
                          {webhookStatusFor(channel)}
                          {channel.lastWebhookAt && ` · ${new Intl.DateTimeFormat(isAr ? "ar-EG" : "en", { dateStyle: "medium", timeStyle: "short" }).format(new Date(channel.lastWebhookAt))}`}
                        </div>
                      )}
                    </div>

                    <Badge tone={needsRelink ? "warning" : isConnected ? "success" : needsAttention || needsVerification ? "warning" : "muted"}>{needsRelink ? (isAr ? "يحتاج صلاحيات" : "Needs permissions") : status}</Badge>

                    {/* Action buttons */}
                    {terminal ? (
                      <span className="text-[11px] text-muted-foreground">
                        {isAr ? "لا يتيح الـAPI الحالي إعادة تفعيل اتصال معطّل نهائيًا." : "The current API cannot reactivate a permanently disabled connection."}
                      </span>
                    ) : (
                      <div className="flex flex-wrap items-center gap-2">
                        {/* Verify button — only when connected */}
                        {channel.integrationId && (
                          <button
                            type="button"
                            onClick={() => verifyConnection(channel)}
                            disabled={saving || Boolean(verifyingId)}
                            className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-border bg-card px-3 text-[12.5px] font-semibold text-foreground shadow-sm transition-colors hover:bg-surface hover:border-foreground/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            {verifyingId === channel.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ShieldCheck className="h-3.5 w-3.5" />}
                            {isAr ? "اختبار" : "Verify"}
                          </button>
                        )}

                        {/* Copy webhook/widget key */}
                        {(channel.publicKey || channel.webhookUrl) && (
                          <button
                            type="button"
                            onClick={() => copyValue(channel.webhookUrl || channel.publicKey, channel.id)}
                            className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-border bg-card px-3 text-[12.5px] font-semibold text-foreground shadow-sm transition-colors hover:bg-surface hover:border-foreground/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            <Copy className="h-3.5 w-3.5" />
                            {copiedTarget === channel.id
                              ? (isAr ? "تم النسخ" : "Copied")
                              : channel.webhookUrl
                                ? (isAr ? "نسخ رابط Webhook" : "Copy webhook URL")
                                : (isAr ? "نسخ مفتاح الودجت" : "Copy widget key")}
                          </button>
                        )}

                        {/* Disconnect button */}
                        {channel.integrationId && channel.status !== "disconnected" && (
                          <button
                            type="button"
                            onClick={() => disconnectConnection(channel)}
                            disabled={saving}
                            className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-destructive/40 bg-card px-3 text-[12.5px] font-semibold text-destructive shadow-sm transition-colors hover:bg-destructive/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-destructive disabled:cursor-not-allowed disabled:opacity-50"
                            title={isAr ? "فك الارتباط" : "Disconnect"}
                          >
                            <Unplug className="h-3.5 w-3.5" />
                            {isAr ? "فك الارتباط" : "Disconnect"}
                          </button>
                        )}

                        {/* ═══ Single green "ربط" / "Connect" button ═══ */}
                        {hasOneClickConnect(channel) ? (
                          /* Meta OAuth / WhatsApp Embedded Signup — popup flow */
                          <button
                            type="button"
                            onClick={() => handleConnect(channel)}
                            disabled={saving || Boolean(metaConnecting) || (channel.id === "whatsapp" && whatsappSdkLoading)}
                            className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-emerald-600 px-3.5 text-[12px] font-semibold text-white shadow-sm hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-60 transition-colors"
                          >
                            {isConnecting || (channel.id === "whatsapp" && whatsappSdkLoading)
                              ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              : <LinkIcon className="h-3.5 w-3.5" />}
                            {isConnecting
                              ? (isAr ? "جارٍ الربط…" : "Connecting…")
                              : channel.id === "whatsapp" && whatsappSdkLoading
                              ? (isAr ? "جارٍ تجهيز واتساب…" : "Preparing WhatsApp…")
                              : channel.connected || needsAttention || needsVerification || needsRelink
                              ? (isAr ? "إعادة ربط" : "Reconnect")
                              : (isAr ? "ربط" : "Connect")}
                          </button>
                        ) : (
                          /* Manual credential channels (Telegram, Webchat) — opens form */
                          <button
                            type="button"
                            onClick={() => editingId === channel.id ? closeConnection() : openConnection(channel)}
                            disabled={saving || !fields}
                            className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-emerald-600 px-3.5 text-[12px] font-semibold text-white shadow-sm hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-60 transition-colors"
                          >
                            {editingId === channel.id ? <Unplug className="h-3.5 w-3.5" /> : <LinkIcon className="h-3.5 w-3.5" />}
                            {editingId === channel.id
                              ? (isAr ? "إلغاء" : "Cancel")
                              : channel.connected || needsAttention || needsVerification
                                ? (isAr ? "إعادة ربط" : "Reconnect")
                                : (isAr ? "ربط" : "Connect")}
                          </button>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Manual credential form (Telegram, Webchat) */}
                  {editingId === channel.id && fields && (
                    <form onSubmit={saveConnection} className="mt-3 grid gap-3 border-t border-border pt-3 sm:grid-cols-2" style={{ direction: isAr ? "rtl" : "ltr" }}>
                      {channel.id === "webchat" ? (
                        <div className="sm:col-span-2">
                          <label htmlFor="webchat-public-key" className="mb-1.5 block text-[12px] font-medium text-foreground">
                            {isAr ? "مفتاح ويدجت شات الموقع" : "Website chat widget key"}
                          </label>
                          <div className="flex gap-2">
                            <input
                              id="webchat-public-key"
                              value={values.public_key || editing.publicKey || ""}
                              readOnly
                              dir="ltr"
                              className="h-9 min-w-0 flex-1 rounded-md border border-input bg-background px-3 font-mono text-[12px]"
                            />
                            <button type="button" onClick={() => copyValue(values.public_key || editing.publicKey, "webchat-form")} disabled={!values.public_key && !editing.publicKey} className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border border-border bg-card px-3 text-[12.5px] font-semibold text-foreground shadow-sm transition-colors hover:bg-surface hover:border-foreground/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50">
                              <Copy className="h-3.5 w-3.5" />{copiedTarget === "webchat-form" ? (isAr ? "تم النسخ" : "Copied") : (isAr ? "نسخ" : "Copy")}
                            </button>
                          </div>
                          <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
                            {isAr ? "المفتاح العام لا يُعد سرًا. عند أول حفظ ينشئه الخادم، وبعدها انسخه من صف القناة." : "The public key is not a secret. The server creates it on first save; copy it from the channel row afterward."}
                          </p>
                        </div>
                      ) : fields.map((field) => (
                        <label key={field.name} className="grid gap-1.5 text-[12px] font-medium text-foreground">
                          {isAr ? field.label[0] : field.label[1]}
                          <input
                            name={field.name}
                            type={field.type}
                            required
                            autoComplete="new-password"
                            value={values[field.name] || ""}
                            onChange={(event) => setValues((current) => ({ ...current, [field.name]: event.target.value }))}
                            className="h-9 rounded-md border border-input bg-background px-3 text-[13px]"
                            dir="ltr"
                          />
                        </label>
                      ))}

                      <div className="flex items-start gap-2 text-[11px] leading-relaxed text-muted-foreground sm:col-span-2">
                        <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
                        <span>
                          {channel.id === "webchat"
                            ? (isAr ? "المفتاح العام فقط هو الذي يعود للمتصفح؛ أسرار مزودي القنوات لا تُقرأ من الـAPI." : "Only the public widget key is returned to the browser; provider secrets are not readable through the API.")
                            : (isAr ? "لن تُعرض بيانات الاعتماد المحفوظة مرة أخرى. أدخل المجموعة كاملة عند إعادة الربط؛ الـBackend يخزّنها مشفّرة." : "Saved credentials are never returned to the browser. Re-enter the full set when reconnecting; the backend encrypts them at rest.")}
                        </span>
                      </div>

                      {formError && <p role="alert" className="text-[12px] text-destructive sm:col-span-2">{formError}</p>}

                      <div className="flex justify-end gap-2 sm:col-span-2">
                        <button type="button" onClick={closeConnection} disabled={saving} className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-border bg-card px-3 text-[12.5px] font-semibold text-foreground shadow-sm transition-colors hover:bg-surface hover:border-foreground/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50">
                          {isAr ? "إلغاء" : "Cancel"}
                        </button>
                        <button type="submit" disabled={saving} className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-primary px-3 text-[12px] font-medium text-primary-foreground disabled:opacity-60">
                          {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                          {saving ? (isAr ? "جارٍ الحفظ…" : "Saving…") : (isAr ? "حفظ وربط" : "Save and connect")}
                        </button>
                      </div>
                    </form>
                  )}
                </div>
              );
            })}
          </div>
        )}

        <p className="mt-3 border-t border-border pt-3 text-[11.5px] leading-relaxed text-muted-foreground">
          {isAr
            ? "يختبر الخادم بيانات الاعتماد قبل تفعيل القناة ويخزنها مشفّرة. يسجل Webhook تيليجرام تلقائيًا؛ أما واتساب وإنستجرام وماسنجر فتحتاج إعداد رابط Callback وApp Secret وVerify Token في Meta Developer Console والخادم. استقبال الرسائل حالة مستقلة ويعرض آخر Webhook موثّق وصل فعلًا."
            : "The server verifies credentials before activation and encrypts them at rest. Telegram webhooks are registered automatically. WhatsApp, Instagram, and Messenger require a callback URL plus an app secret and verify token configured in Meta Developer Console and the backend. Reception is tracked separately and shows the last authenticated event."}
        </p>
      </SettingCard>
    </SettingsShell>
  );
}
