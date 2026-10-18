import React from "react";
import { Copy, Loader2, LinkIcon, ShieldCheck, Unplug } from "lucide-react";
import { useI18n, useT } from "@/lib/i18n";
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

function loadFacebookSdk(appId, version) {
  if (window.FB) return Promise.resolve(window.FB);
  return new Promise((resolve, reject) => {
    window.fbAsyncInit = function () {
      window.FB.init({ appId, cookie: true, xfbml: true, version });
      resolve(window.FB);
    };
    const script = document.createElement("script");
    script.src = "https://connect.facebook.net/en_US/sdk.js";
    script.async = true;
    script.defer = true;
    script.crossOrigin = "anonymous";
    script.onerror = () =>
      reject(
        new Error(
          isAr
            ? "تعذر تحميل Facebook SDK — إذا كنت تستخدم مانع إعلانات (AdBlocker) يرجى إيقافه مؤقتًا لهذه الصفحة ثم إعادة المحاولة."
            : "Could not load the Facebook SDK — if using an AdBlocker, please disable it for this page and retry."
        )
      );
    document.body.appendChild(script);
  });
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

/** Map the marker the OAuth callback appended onto a sentence the operator can act on. */
function friendlyMetaError(raw, isAr) {
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
  if (detail.startsWith("meta_exchange_failed")) {
    return isAr
      ? "فشل تبادل رمز التفويض مع خوادم فيسبوك. تحقق من إعدادات التطبيق ثم أعد المحاولة."
      : "The authorization code could not be exchanged with Meta. Check the app settings, then retry.";
  }
  return detail;
}

/** Open a centered popup window. */
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
  const metaPopupRef = React.useRef(null);
  const metaPollTimerRef = React.useRef(null);
  const metaTimeoutRef = React.useRef(null);
  const [formError, setFormError] = React.useState("");
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

  // Listen for Meta OAuth popup results (postMessage / BroadcastChannel / storage).
  React.useEffect(() => {
    function handleResult(data) {
      if (!data || data.type !== META_OAUTH_RESULT) return;
      clearMetaConnectTimers(true);
      const { connected, error: oauthError } = data;
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
      handleResult(event.data);
    }

    function onStorage(event) {
      if (event.key === "meta_oauth_result" && event.newValue) {
        try {
          const parsed = JSON.parse(event.newValue);
          localStorage.removeItem("meta_oauth_result");
          handleResult(parsed);
        } catch (_) {}
      }
    }

    let bc = null;
    try {
      bc = new BroadcastChannel("meta_oauth");
      bc.onmessage = (event) => handleResult(event.data);
    } catch (_) {}

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
    setMetaConnecting(channel.id);
    setFormError("");
    setNotice("");
    try {
      const { app_id: appId, config_id: configId, graph_version: version } = await api(
        "/integrations/whatsapp/embedded-signup/start"
      );
      if (!appId || !configId) {
        throw new Error(
          isAr
            ? "ربط واتساب غير مُعد على الخادم: اضبط META_WHATSAPP_CONFIG_ID (انظر docs/META_SETUP.md)."
            : "WhatsApp connect is not configured on the server: set META_WHATSAPP_CONFIG_ID (see docs/META_SETUP.md)."
        );
      }
      const fb = await loadFacebookSdk(appId, version || "v26.0");

      let resolveCode;
      let rejectCode;
      const codePromise = new Promise((resolve, reject) => {
        resolveCode = resolve;
        rejectCode = reject;
      });
      const sessionPromise = new Promise((resolve, reject) => {
        const timer = window.setTimeout(() => {
          window.removeEventListener("message", onMessage);
          reject(new Error(isAr ? "انتهت مدة الربط. أعد المحاولة." : "The signup timed out. Try again."));
        }, 10 * 60 * 1000);

        function onMessage(event) {
          if (!event.origin || (!event.origin.endsWith("facebook.com") && !event.origin.endsWith("fb.com"))) {
            return;
          }
          let payload;
          try {
            payload = typeof event.data === "string" ? JSON.parse(event.data) : event.data;
          } catch {
            return;
          }
          if (payload?.type !== WA_SIGNUP_EVENT) return;
          if (payload.event === "CANCEL" || payload.event === "ERROR") {
            window.clearTimeout(timer);
            window.removeEventListener("message", onMessage);
            reject(new Error(isAr ? "أُلغيت عملية الربط قبل اكتمالها." : "The signup was cancelled before it completed."));
            return;
          }
          if (payload.event === "FINISH" || payload.event === "FINISH_ONLY_WABA") {
            window.clearTimeout(timer);
            window.removeEventListener("message", onMessage);
            resolve(payload.data || {});
          }
        }

        window.addEventListener("message", onMessage);
        fb.login(
          (response) => {
            const code = response?.authResponse?.code;
            if (code) resolveCode(code);
            else rejectCode(new Error(isAr ? "لم يُرجع فيسبوك رمز التفويض. أعد المحاولة." : "Facebook returned no authorization code. Try again."));
          },
          {
            config_id: configId,
            response_type: "code",
            override_default_response_type: true,
            extras: { setup: {}, featureType: "", sessionInfoVersion: "3" },
          }
        );
      });

      const [authCode, session] = await Promise.all([codePromise, sessionPromise]);
      const wabaId = String(session.waba_id || session.wabaId || "");
      const phoneNumberId = String(session.phone_number_id || session.phoneNumberId || "");
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

  /** Whether the channel needs a manual credential form (Telegram, Webchat manual entry). */
  function needsManualForm(channel) {
    return channel.id === "telegram" || channel.id === "webchat";
  }

  /** Whether the channel can be connected via a single-click flow (Meta popup or WA SDK). */
  function hasOneClickConnect(channel) {
    return channel.id === "whatsapp" || META_OAUTH_CHANNELS.has(channel.id);
  }

  return (
    <SettingsShell title={t("channels.title")} subtitle={t("channels.subtitle")}>
      <SettingCard>
        {error && <div role="alert" className="mb-3 rounded-lg bg-destructive/10 px-3 py-2 text-[12px] text-destructive">{error}</div>}
        {formError && !editingId && <div role="alert" className="mb-3 rounded-lg bg-destructive/10 px-3 py-2 text-[12px] text-destructive">{formError}</div>}
        {notice && <div role="status" className="mb-3 rounded-lg border border-primary/20 bg-primary/5 px-3 py-2 text-[12px] text-primary">{notice}</div>}
        {metaConnecting && <div role="status" aria-live="polite" className="mb-3 flex items-start gap-2 rounded-lg border border-primary/20 bg-primary/5 px-3 py-2 text-[12px] leading-relaxed text-primary">
          <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin" />
          <span>{isAr
            ? `جارٍ فتح نافذة ربط ${t(`channel.${metaConnecting}`)}. أكمل خطوات تسجيل الدخول فيها بعد ظهورها؛ ستظهر هنا نتيجة الربط.`
            : `Opening the ${t(`channel.${metaConnecting}`)} connect window. Complete sign-in there when it appears; the result will show here.`}</span>
        </div>}

        {loading && channels.length === 0 ? (
          <div className="py-8 text-center text-[13px] text-muted-foreground">{isAr ? "جارٍ تحميل القنوات…" : "Loading channels…"}</div>
        ) : (
          <div className="divide-y divide-border">
            {channels.map((channel) => {
              const status = statusFor(channel);
              const needsAttention = ATTENTION_STATES.has(channel.status);
              const needsVerification = channel.integrationId && ["active", "connected"].includes(channel.status) && !channel.credentialsVerified;
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
                      {channel.integrationId && (
                        <div className="mt-1 text-[11px] text-muted-foreground">
                          {webhookStatusFor(channel)}
                          {channel.lastWebhookAt && ` · ${new Intl.DateTimeFormat(isAr ? "ar-EG" : "en", { dateStyle: "medium", timeStyle: "short" }).format(new Date(channel.lastWebhookAt))}`}
                        </div>
                      )}
                    </div>

                    <Badge tone={isConnected ? "success" : needsAttention || needsVerification ? "warning" : "muted"}>{status}</Badge>

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
                            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border px-2.5 text-[12px] font-medium text-foreground hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
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
                            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border px-2.5 text-[12px] font-medium text-foreground hover:bg-surface"
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
                            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-destructive/30 px-2.5 text-[12px] font-medium text-destructive hover:bg-destructive/10 disabled:cursor-not-allowed disabled:opacity-50"
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
                            disabled={saving || Boolean(metaConnecting)}
                            className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-emerald-600 px-3.5 text-[12px] font-semibold text-white shadow-sm hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-60 transition-colors"
                          >
                            {isConnecting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <LinkIcon className="h-3.5 w-3.5" />}
                            {isConnecting
                              ? (isAr ? "جارٍ الربط…" : "Connecting…")
                              : channel.connected || needsAttention || needsVerification
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
                    <form onSubmit={saveConnection} className="mt-3 grid gap-3 rounded-xl border border-border bg-surface/60 p-3.5 sm:grid-cols-2" style={{ direction: isAr ? "rtl" : "ltr" }}>
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
                            <button type="button" onClick={() => copyValue(values.public_key || editing.publicKey, "webchat-form")} disabled={!values.public_key && !editing.publicKey} className="inline-flex h-9 items-center gap-1.5 rounded-md border border-border px-3 text-[12px] hover:bg-background disabled:opacity-50">
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
                        <button type="button" onClick={closeConnection} disabled={saving} className="h-8 rounded-lg border border-border px-3 text-[12px] hover:bg-background disabled:opacity-50">
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
