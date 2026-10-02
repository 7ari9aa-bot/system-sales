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
const CONNECTING_STATES = new Set(["pending", "connecting"]);

function createPublicWidgetKey() {
  const bytes = new Uint8Array(24);
  window.crypto.getRandomValues(bytes);
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

function postIntegration(provider, { credentials = {}, config = {}, status = "active" } = {}) {
  return api("/integrations", {
    method: "POST",
    body: { provider, kind: "channel", credentials, config, status },
  });
}

export default function ChannelsSettings() {
  const t = useT();
  const { lang } = useI18n();
  const isAr = lang === "ar";
  const { channels, loading, error, reload } = useRealChannels();
  const [editingId, setEditingId] = React.useState("");
  const [values, setValues] = React.useState({});
  const [saving, setSaving] = React.useState(false);
  const [formError, setFormError] = React.useState("");
  const [notice, setNotice] = React.useState("");
  const [copied, setCopied] = React.useState(false);

  const editing = channels.find((channel) => channel.id === editingId) || null;

  function openConnection(channel) {
    setFormError("");
    setNotice("");
    setCopied(false);
    setEditingId(channel.id);
    setValues(channel.id === "webchat"
      ? { public_key: channel.publicKey || (channel.integrationId ? "" : createPublicWidgetKey()) }
      : {});
    if (channel.id === "webchat" && channel.integrationId && !channel.publicKey) {
      setFormError(isAr
        ? "تعذر قراءة مفتاح الودجت الحالي من الـAPI؛ أعد تحميل الصفحة قبل تعديل الاتصال."
        : "The API did not return the existing widget key. Reload before changing this connection.");
    }
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

    const credentials = Object.fromEntries(
      CONNECTION_FIELDS[editing.id]
        .map(({ name }) => [name, String(values[name] || "").trim()])
        .filter(([, value]) => value),
    );
    const config = editing.id === "webchat"
      ? { public_key: String(values.public_key || "").trim() }
      : {};
    const existing = Boolean(editing.integrationId);
    const body = { credentials, config };

    try {
      if (!existing) {
        // Use the backend lifecycle from its first state instead of creating a
        // channel directly in its final state.
        await postIntegration(editing.id, { ...body, status: "pending" });
        await postIntegration(editing.id, { config, status: "connecting" });
        await postIntegration(editing.id, { config, status: "active" });
      } else if (CONNECTING_STATES.has(editing.status)) {
        // The API enforces pending/disconnected -> connecting -> active.
        await postIntegration(editing.id, { ...body, status: "connecting" });
        await postIntegration(editing.id, { config, status: "active" });
      } else {
        await postIntegration(editing.id, {
          ...body,
          status: "active",
        });
      }
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
      setNotice(isAr ? "تم حفظ إعدادات القناة." : "Channel settings were saved.");
    } catch {
      setNotice(isAr
        ? "تم الحفظ، لكن تعذر تحديث حالة القناة. أعد تحميل الصفحة."
        : "Saved, but the channel status could not be refreshed. Reload the page.");
    } finally {
      setSaving(false);
    }
  }

  async function copyWidgetKey() {
    if (!values.public_key) return;
    try {
      await navigator.clipboard.writeText(values.public_key);
      setCopied(true);
      setFormError("");
    } catch {
      setFormError(isAr
        ? "تعذر النسخ تلقائيًا؛ حدّد المفتاح وانسخه يدويًا."
        : "Could not copy automatically. Select and copy the key manually.");
    }
  }

  function statusFor(channel) {
    if (channel.connected) return t("channels.connected");
    if (ATTENTION_STATES.has(channel.status)) return t("channels.needsAttention");
    if (CONNECTING_STATES.has(channel.status)) return isAr ? "جارٍ الإعداد" : "Connecting";
    if (channel.status === "disabled") return isAr ? "معطّل نهائيًا" : "Permanently disabled";
    return t("channels.notConnected");
  }

  return (
    <SettingsShell title={t("channels.title")} subtitle={t("channels.subtitle")}>
      <SettingCard>
        {error && <div role="alert" className="mb-3 rounded-lg bg-destructive/10 px-3 py-2 text-[12px] text-destructive">{error}</div>}
        {notice && <div role="status" className="mb-3 rounded-lg border border-primary/20 bg-primary/5 px-3 py-2 text-[12px] text-primary">{notice}</div>}

        {loading && channels.length === 0 ? (
          <div className="py-8 text-center text-[13px] text-muted-foreground">{isAr ? "جارٍ تحميل القنوات…" : "Loading channels…"}</div>
        ) : (
          <div className="divide-y divide-border">
            {channels.map((channel) => {
              const status = statusFor(channel);
              const needsAttention = ATTENTION_STATES.has(channel.status);
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
                    </div>
                    <Badge tone={channel.connected ? "success" : needsAttention ? "warning" : "muted"}>{status}</Badge>
                    {unsupported ? (
                      <span className="text-[11px] text-muted-foreground">
                        {isAr ? "رسائل صفحات فيسبوك تمر عبر تكامل Messenger؛ لا يوجد موصل Facebook منفصل بعد." : "Facebook Page messages use the Messenger integration; a separate Facebook connector is not available yet."}
                      </span>
                    ) : terminal ? (
                      <span className="text-[11px] text-muted-foreground">
                        {isAr ? "لا يتيح الـAPI الحالي إعادة تفعيل اتصال معطّل نهائيًا." : "The current API cannot reactivate a permanently disabled connection."}
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => editingId === channel.id ? closeConnection() : openConnection(channel)}
                        disabled={saving || !fields}
                        className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border px-2.5 text-[12px] font-medium text-foreground hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {editingId === channel.id ? <Unplug className="h-3.5 w-3.5" /> : <PlugZap className="h-3.5 w-3.5" />}
                        {editingId === channel.id
                          ? (isAr ? "إلغاء" : "Cancel")
                          : channel.connected || needsAttention
                            ? t("channels.reconnect")
                            : t("channels.connect")}
                      </button>
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
                              value={values.public_key || ""}
                              readOnly
                              dir="ltr"
                              className="h-9 min-w-0 flex-1 rounded-md border border-input bg-background px-3 font-mono text-[12px]"
                            />
                            <button type="button" onClick={copyWidgetKey} className="inline-flex h-9 items-center gap-1.5 rounded-md border border-border px-3 text-[12px] hover:bg-background">
                              <Copy className="h-3.5 w-3.5" />{copied ? (isAr ? "تم النسخ" : "Copied") : (isAr ? "نسخ" : "Copy")}
                            </button>
                          </div>
                          <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
                            {isAr ? "هذا معرّف عام للودجت، وليس سرًا. بعد الحفظ استخدمه في إعداد ويدجت الموقع." : "This is a public widget identifier, not a secret. Save it, then use it in your website chat widget."}
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
                        <button type="submit" disabled={saving || (channel.id === "webchat" && !values.public_key?.trim())} className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-primary px-3 text-[12px] font-medium text-primary-foreground disabled:opacity-60">
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
            ? "حالات الاتصال وعمليات الحفظ تأتي من الـBackend. أسرار واتساب وإنستجرام وماسنجر وتيليجرام تُرسل للخادم فقط وتُشفّر قبل تخزينها في قاعدة البيانات. إعداد Webhook لدى مزود القناة يظل مطلوبًا لتلقي الرسائل."
            : "Connection status and saves come from the backend. WhatsApp, Instagram, Messenger, and Telegram secrets are sent only to the server and encrypted before database storage. The channel provider's webhook still needs to be configured to receive messages."}
        </p>
      </SettingCard>
    </SettingsShell>
  );
}
