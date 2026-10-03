import React from "react";
import { Copy, Loader2, PlugZap, ShieldCheck, Unplug } from "lucide-react";
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

export default function ChannelsSettings() {
  const t = useT();
  const { lang } = useI18n();
  const isAr = lang === "ar";
  const { channels, loading, error, reload } = useRealChannels();
  const [editingId, setEditingId] = React.useState("");
  const [values, setValues] = React.useState({});
  const [saving, setSaving] = React.useState(false);
  const [verifyingId, setVerifyingId] = React.useState("");
  const [formError, setFormError] = React.useState("");
  const [notice, setNotice] = React.useState("");
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
    if (editing.id === "whatsapp") {
      channelConfig.phone_number_id = String(values.phone_number_id || "").trim();
      credentials.access_token = String(values.access_token || "").trim();
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
      setFormError(saveError?.message || (isAr ? "تعذر حفظ إعدادات القناة." : "Could not save channel settings."));
      await reload().catch(() => {});
      setSaving(false);
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
      setFormError(verifyError?.message || (isAr ? "تعذر التحقق من القناة." : "Could not verify the channel."));
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

  return (
    <SettingsShell title={t("channels.title")} subtitle={t("channels.subtitle")}>
      <SettingCard>
        {error && <div role="alert" className="mb-3 rounded-lg bg-destructive/10 px-3 py-2 text-[12px] text-destructive">{error}</div>}
        {formError && !editingId && <div role="alert" className="mb-3 rounded-lg bg-destructive/10 px-3 py-2 text-[12px] text-destructive">{formError}</div>}
        {notice && <div role="status" className="mb-3 rounded-lg border border-primary/20 bg-primary/5 px-3 py-2 text-[12px] text-primary">{notice}</div>}

        {loading && channels.length === 0 ? (
          <div className="py-8 text-center text-[13px] text-muted-foreground">{isAr ? "جارٍ تحميل القنوات…" : "Loading channels…"}</div>
        ) : (
          <div className="divide-y divide-border">
            {channels.map((channel) => {
              const status = statusFor(channel);
              const needsAttention = ATTENTION_STATES.has(channel.status);
              const needsVerification = channel.integrationId && ["active", "connected"].includes(channel.status) && !channel.credentialsVerified;
              const unsupported = channel.id === "facebook";
              const terminal = channel.status === "disabled";
              const fields = CONNECTION_FIELDS[channel.id];

              return (
                <div key={channel.id} className="py-3.5 first:pt-1 last:pb-1">
                  <div className="flex flex-wrap items-center gap-3">
                    <ChannelIcon channel={channel.id} />
                    <div className="min-w-0 flex-1">
                      <div className="text-[13.5px] font-medium">{t(`channel.${channel.id}`)}</div>
                      <div className="text-[12px] text-muted-foreground">{status}</div>
                      {channel.displayName && <div className="text-[11px] text-muted-foreground">{channel.displayName}</div>}
                      {channel.integrationId && (
                        <div className="mt-1 text-[11px] text-muted-foreground">
                          {webhookStatusFor(channel)}
                          {channel.lastWebhookAt && ` · ${new Intl.DateTimeFormat(isAr ? "ar-EG" : "en", { dateStyle: "medium", timeStyle: "short" }).format(new Date(channel.lastWebhookAt))}`}
                        </div>
                      )}
                    </div>
                    <Badge tone={channel.connected || channel.webhookStatus === "receiving" ? "success" : needsAttention || needsVerification ? "warning" : "muted"}>{status}</Badge>
                    {unsupported ? (
                      <span className="text-[11px] text-muted-foreground">
                        {isAr ? "رسائل صفحات فيسبوك تمر عبر تكامل Messenger؛ لا يوجد موصل Facebook منفصل بعد." : "Facebook Page messages use the Messenger integration; a separate Facebook connector is not available yet."}
                      </span>
                    ) : terminal ? (
                      <span className="text-[11px] text-muted-foreground">
                        {isAr ? "لا يتيح الـAPI الحالي إعادة تفعيل اتصال معطّل نهائيًا." : "The current API cannot reactivate a permanently disabled connection."}
                      </span>
                    ) : (
                      <div className="flex flex-wrap items-center gap-2">
                        {channel.integrationId && (
                          <button
                            type="button"
                            onClick={() => verifyConnection(channel)}
                            disabled={saving || Boolean(verifyingId)}
                            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border px-2.5 text-[12px] font-medium text-foreground hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            {verifyingId === channel.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ShieldCheck className="h-3.5 w-3.5" />}
                            {isAr ? "اختبار الاتصال" : "Verify"}
                          </button>
                        )}
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
                        <button
                          type="button"
                          onClick={() => editingId === channel.id ? closeConnection() : openConnection(channel)}
                          disabled={saving || !fields}
                          className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border px-2.5 text-[12px] font-medium text-foreground hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {editingId === channel.id ? <Unplug className="h-3.5 w-3.5" /> : <PlugZap className="h-3.5 w-3.5" />}
                          {editingId === channel.id
                            ? (isAr ? "إلغاء" : "Cancel")
                            : channel.connected || needsAttention || needsVerification
                              ? t("channels.reconnect")
                              : t("channels.connect")}
                        </button>
                      </div>
                    )}
                  </div>

                  {editingId === channel.id && fields && (
                    <form onSubmit={saveConnection} className="mt-3 grid gap-3 rounded-xl border border-border bg-surface/60 p-3.5 sm:grid-cols-2">
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
