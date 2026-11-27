/**
 * Channel settings helpers: field definitions, Meta's OAuth handshake and the error
 * wording the owner reads. Extracted from ChannelsSettings so the page keeps the screen
 * and this file keeps the protocol. Nothing was rewritten in the move.
 */
// WhatsApp is deliberately absent: it has no credential form, because a pasted token cannot
// create a working WhatsApp channel. Meta's Embedded Signup is the only door, and the backend
// refuses WhatsApp on the generic connect route for the same reason.
export const CONNECTION_FIELDS = {
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

export const ATTENTION_STATES = new Set(["reauth_required", "restricted", "disconnected", "degraded", "error"]);

/** Channels that use Meta OAuth popup flow (Instagram, Messenger, Facebook). */
export const META_OAUTH_CHANNELS = new Set(["messenger", "instagram", "facebook"]);

/**
 * The `provider` the server's Meta OAuth start route expects for a channel.
 *
 * Instagram has two separate grants and the merchant's account decides which one works:
 * - "instagram_login": Instagram Login. No Facebook Page needed, its own Graph host. This is the
 *   default because most shops only have an Instagram professional account.
 * - "instagram": Facebook Login. The account must be linked to a Facebook Page.
 * Every other channel sends its own id unchanged.
 */
export function metaOauthProvider(channelId, instagramMethod) {
  if (channelId === "instagram" && instagramMethod !== "facebook") return "instagram_login";
  return channelId;
}

/** WhatsApp Embedded Signup event type from Meta's JS SDK. */
export const WA_SIGNUP_EVENT = "WA_EMBEDDED_SIGNUP";

/** Meta OAuth popup result event type (sent by our callback page). */
export const META_OAUTH_RESULT = "META_OAUTH_RESULT";

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
export function friendlyChannelError(raw, isAr) {
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

/** What to tell the shop after a WhatsApp connect, from what Meta said about the number.
 *
 * The server decides `onboarding_mode` from `is_on_biz_app` + `platform_type`; this only turns that
 * answer into one honest sentence. `not_on_business_app` is NOT an error — the channel is connected
 * and works — but the shop has to know that replies typed in the phone app will not appear here,
 * because that is the one promise coexistence makes and Cloud API alone cannot keep.
 */
export function whatsappConnectedNotice(result, isAr) {
  const mode = String(result?.onboarding_mode || "");
  const status = String(result?.coexistence_status || "");
  if (mode === "coexistence" || status === "verified") {
    return isAr
      ? "تم ربط رقم واتساب. التطبيق على الهاتف يعمل كما هو، وردودك من الهاتف ستظهر هنا كرسائل بشرية."
      : "The WhatsApp number is connected. The phone app keeps working, and replies you type there appear here as human messages.";
  }
  if (status === "not_on_business_app") {
    return isAr
      ? "تم ربط الرقم عبر Cloud API. وتفيد Meta أن الرقم غير مسجل على تطبيق WhatsApp Business، فلن تظهر هنا ردود من الهاتف — اربط الرقم من تطبيق WhatsApp Business إن أردت الجمع بينهما."
      : "The number is connected over the Cloud API. Meta reports it is not on the WhatsApp Business app, so replies from the phone will not appear here. Link it from the WhatsApp Business app if you want both together.";
  }
  return isAr ? "تم ربط رقم واتساب بنجاح." : "The WhatsApp number is connected.";
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

export function openCenteredPopup(url, name, w = 600, h = 700) {
  const left = window.screenX + (window.outerWidth - w) / 2;
  const top = window.screenY + (window.outerHeight - h) / 2;
  return window.open(
    url,
    name,
    `width=${w},height=${h},left=${Math.max(0, left)},top=${Math.max(0, top)},scrollbars=yes,resizable=yes`
  );
}

export function withTimeout(promise, timeoutMs, message) {
  let timer;
  return Promise.race([
    promise,
    new Promise((_, reject) => {
      timer = window.setTimeout(() => reject(new Error(message)), timeoutMs);
    }),
  ]).finally(() => window.clearTimeout(timer));
}
