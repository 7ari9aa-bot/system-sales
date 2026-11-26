import React from "react";
import { useParams } from "react-router-dom";
import { useI18n, useT } from "@/lib/i18n";
import { api } from "@/lib/api";
import { useRealChannels } from "@/hooks/useRealData";
import ChannelsView from "@/pages/settings/channels/ChannelsView";
import { useChannelConnect } from "@/pages/settings/channels/useChannelConnect";
import {
  ATTENTION_STATES,
  CONNECTING_HINT_AFTER_MS,
  CONNECTION_FIELDS,
  META_OAUTH_CHANNELS,
  SIGNUP_REPORT_WAIT_MS,
  SIGNUP_WINDOW_MS,
  connectingHint,
  extractWhatsAppSignupIds,
  facebookSdkUrl,
  friendlyChannelError,
  friendlyMetaError,
  isMetaOAuthPopupMessage,
  isMetaSdkOrigin,
  isMetaSignupMessage,
  loadFacebookSdk,
  metaOauthProvider,
  signupCodeExpiredError,
  whatsappConnectedNotice,
  whatsappLoginOutcome,
  whatsappSignupInterruption,
} from "@/pages/settings/channels/channelHelpers";

export { CONNECTING_HINT_AFTER_MS };
export { SIGNUP_REPORT_WAIT_MS };
export { SIGNUP_WINDOW_MS };
export { connectingHint };
export { extractWhatsAppSignupIds };
export { facebookSdkUrl };
export { friendlyMetaError };
export { isMetaOAuthPopupMessage };
export { isMetaSdkOrigin };
export { isMetaSignupMessage };
export { loadFacebookSdk };
export { metaOauthProvider };
export { signupCodeExpiredError };
export { whatsappConnectedNotice };
export { whatsappLoginOutcome };
export { whatsappSignupInterruption };

export default function ChannelsSettings() {
  const t = useT();
  const { lang } = useI18n();
  const isAr = lang === "ar";
  // كل قناة ليها صفحتها: /settings/channels/<id>. الصفحة الأم بتعرض القنوات كلها،
  // وصفحة القناة بتعرض قناتها بس — نفس المكوّن ونفس الحالة، فالسلوك ما اتغيّرش.
  const { channel: channelId } = useParams();
  const { channels: allChannels, loading, error, reload } = useRealChannels();
  const channels = channelId ? allChannels.filter((c) => c.id === channelId) : allChannels;
  const unknownChannel = Boolean(channelId) && !loading && allChannels.length > 0 && channels.length === 0;
  const {
    metaConnecting,
    instagramMethod,
    setInstagramMethod,
    connectingMs,
    whatsappSdkLoading,
    pageChoice,
    pageChoiceBusy,
    pageChoiceError,
    notice,
    setNotice,
    formError,
    setFormError,
    choosePage,
    cancelPageChoice,
    handleConnect,
  } = useChannelConnect({ isAr, reload });
  const [editingId, setEditingId] = React.useState("");
  const [values, setValues] = React.useState({});
  const [saving, setSaving] = React.useState(false);
  const [verifyingId, setVerifyingId] = React.useState("");
  const [copiedTarget, setCopiedTarget] = React.useState("");

  const editing = channels.find((channel) => channel.id === editingId) || null;



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
    if (editing.id === "facebook") {
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
    <ChannelsView
      s={{
        t,
        isAr,
        channelId,
        channels,
        loading,
        error,
        unknownChannel,
        pageChoice,
        pageChoiceBusy,
        pageChoiceError,
        choosePage,
        cancelPageChoice,
        formError,
        notice,
        metaConnecting,
        connectingMs,
        editingId,
        editing,
        values,
        setValues,
        saving,
        verifyingId,
        instagramMethod,
        setInstagramMethod,
        statusFor,
        webhookStatusFor,
        hasOneClickConnect,
        handleConnect,
        openConnection,
        closeConnection,
        saveConnection,
        disconnectConnection,
        verifyConnection,
        copyValue,
        copiedTarget,
        whatsappSdkLoading,
      }}
    />
  );
}
