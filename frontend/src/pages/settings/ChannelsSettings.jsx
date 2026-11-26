import React from "react";
import { Copy, Loader2, LinkIcon, ShieldCheck, Unplug } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { useI18n, useT } from "@/lib/i18n";
import ChannelDiagnostics from "@/pages/settings/ChannelDiagnostics";
import FacebookRelinkNotice, { facebookNeedsRelink } from "@/pages/settings/FacebookRelinkNotice";
import MetaPageChoiceDialog from "@/pages/settings/MetaPageChoiceDialog";
import { api } from "@/lib/api";
import { useRealChannels } from "@/hooks/useRealData";
import SettingsShell, { SettingCard } from "@/components/settings/SettingsShell";
import ChannelIcon from "@/components/dashboard/ChannelIcon";
import WhatsAppSyncCard from "@/components/settings/WhatsAppSyncCard";
import { Badge } from "@/components/dashboard/ui";
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
        {channelId && (
          <Link
            to="/settings/channels"
            className="mb-3 inline-flex items-center gap-1 text-[12px] font-medium text-primary hover:underline"
          >
            {isAr ? "→ كل القنوات" : "→ All channels"}
          </Link>
        )}
        {unknownChannel && (
          <div role="alert" className="mb-3 rounded-lg bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
            {isAr ? "مفيش قناة بالاسم ده. ارجع لكل القنوات." : "No channel with that name. Go back to all channels."}
          </div>
        )}
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
                      <div className="text-[13.5px] font-medium">
                        {channelId ? (
                          localizedChannelName
                        ) : (
                          <Link to={`/settings/channels/${channel.id}`} className="hover:underline">
                            {localizedChannelName}
                          </Link>
                        )}
                      </div>
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

                        {/* Not a choice: the journey IS the merchant's existing WhatsApp Business
                            app number, so the popup always asks Meta for that flow. What the line
                            warns about is what Meta does to the devices around that number. */}
                        {channel.id === "whatsapp" && !isConnected && (
                          <p
                            className="max-w-md text-[11px] leading-5 text-slate-600"
                            data-testid="whatsapp-coexistence-note"
                          >
                            {isAr
                              ? "اربط نفس الرقم اللي شغال على تطبيق WhatsApp Business — التطبيق هيفضل شغال على الموبايل والمحادثات هتظهر هنا كمان. الأجهزة المرتبطة (WhatsApp Web / Desktop) هتتفصل أثناء الربط وتقدر توصلها تاني، لكن WhatsApp for Windows و WearOS مش مدعومين في المسار ده. المجموعات والمكالمات والكتالوج مش بيوصلوا لفهرست — دي حدود واجهة Meta نفسها مش نقص في الربط."
                              : "Connect the same number that runs the WhatsApp Business app. The app keeps working on the phone and the conversations appear here too. Companion devices (WhatsApp Web / Desktop) are unlinked during the link and can be re-linked afterwards, but WhatsApp for Windows and WearOS are not supported on this path. Groups, calls and the catalog do not reach FIHRIST: that is Meta's API, not a gap in the link."}
                          </p>
                        )}

                        {/* The live half of the link: what Meta is still sending, a reservation it
                            never answered, and how close the number is to its 20/s cap. Read from
                            the status endpoint, not from the state captured at link time. */}
                        {channel.id === "whatsapp" && isConnected && (
                          <WhatsAppSyncCard lang={isAr ? "ar" : "en"} />
                        )}

                        {/* Instagram can be linked two ways and the merchant's account decides which
                            one works, so it is an explicit choice rather than a silent default. */}
                        {channel.id === "instagram" && !isConnected && (
                          <fieldset
                            className="flex flex-col gap-1 text-[11px] text-slate-600"
                            data-testid="instagram-method"
                          >
                            <legend className="sr-only">
                              {isAr ? "طريقة ربط إنستجرام" : "How to connect Instagram"}
                            </legend>
                            <label className="flex items-center gap-1.5">
                              <input
                                type="radio"
                                name="instagram-method"
                                value="login"
                                checked={instagramMethod === "login"}
                                onChange={() => setInstagramMethod("login")}
                              />
                              {isAr
                                ? "تسجيل الدخول عبر إنستجرام (بدون صفحة فيسبوك)"
                                : "Instagram Login (no Facebook Page needed)"}
                            </label>
                            <label className="flex items-center gap-1.5">
                              <input
                                type="radio"
                                name="instagram-method"
                                value="facebook"
                                checked={instagramMethod === "facebook"}
                                onChange={() => setInstagramMethod("facebook")}
                              />
                              {isAr
                                ? "عبر فيسبوك (الحساب مرتبط بصفحة فيسبوك)"
                                : "Facebook Login (account linked to a Facebook Page)"}
                            </label>
                          </fieldset>
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
