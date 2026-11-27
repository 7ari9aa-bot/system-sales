/**
 * The channels screen's markup: one row per channel, its connect state and the manual
 * credential form. Extracted from ChannelsSettings unchanged — the page owns state and
 * handlers, this file owns what the owner sees.
 */
import React from "react";
import { Copy, LinkIcon, Loader2, ShieldCheck, Unplug } from "lucide-react";
import { Link } from "react-router-dom";
import ChannelDiagnostics from "@/pages/settings/ChannelDiagnostics";
import FacebookRelinkNotice, { facebookNeedsRelink } from "@/pages/settings/FacebookRelinkNotice";
import MetaPageChoiceDialog from "@/pages/settings/MetaPageChoiceDialog";
import SettingsShell, { SettingCard } from "@/components/settings/SettingsShell";
import ChannelIcon from "@/components/dashboard/ChannelIcon";
import WhatsAppSyncCard from "@/components/settings/WhatsAppSyncCard";
import { Badge } from "@/components/dashboard/ui";
import {
  ATTENTION_STATES,
  CONNECTION_FIELDS,
  connectingHint,
} from "@/pages/settings/channels/channelHelpers";

export default function ChannelsView({ s }) {
  const {
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
  } = s;

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
                <div key={channel.id} data-testid={`channel-${channel.id}`} className="py-3.5 first:pt-1 last:pb-1">
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
