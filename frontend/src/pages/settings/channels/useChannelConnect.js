/**
 * Channel connect orchestration: Meta's Embedded Signup for WhatsApp, the popup OAuth for
 * Instagram/Messenger/Facebook, and the page-choice hand-off.
 *
 * Extracted from ChannelsSettings unchanged so the screen keeps rendering and this hook keeps
 * the provider handshake. It owns the popup timers, so unmounting closes them.
 */
import React from "react";
import { api } from "@/lib/api";
import {
  META_OAUTH_CHANNELS,
  META_OAUTH_RESULT,
  SIGNUP_REPORT_WAIT_MS,
  SIGNUP_WINDOW_MS,
  WA_SIGNUP_EVENT,
  extractWhatsAppSignupIds,
  friendlyMetaError,
  isMetaOAuthPopupMessage,
  isMetaSignupMessage,
  loadFacebookSdk,
  metaOauthProvider,
  openCenteredPopup,
  signupCodeExpiredError,
  whatsappConnectedNotice,
  whatsappLoginOutcome,
  whatsappSignupInterruption,
  withTimeout,
} from "@/pages/settings/channels/channelHelpers";

export function useChannelConnect({ isAr, reload }) {
  const [metaConnecting, setMetaConnecting] = React.useState("");
  // How the merchant links Instagram: "login" (Instagram Login) or "facebook" (via a Page).
  const [instagramMethod, setInstagramMethod] = React.useState("login");
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

  /** Connect WhatsApp via Embedded Signup (JS SDK popup).
   *
   * The channel's journey is the merchant's EXISTING WhatsApp Business app number, so the popup
   * always asks Meta for the Business App onboarding flow (`whatsapp_business_app_onboarding`).
   * Under Embedded Signup v5 that feature is ON unless we switch it off, and switching it off was
   * how a Business App number silently became a Cloud-API-only channel.
   *
   * What the number really is gets decided by Meta and comes back in `coexistence_status`:
   * `verified` means the app and FIHRIST both work on the number, `not_on_business_app` means the
   * number is Cloud API only. The notice says which one happened instead of implying that replies
   * typed in the app are mirrored when they are not.
   */
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
            // Same success event as FINISH, on a number that already runs the WhatsApp Business
            // app: Meta has just put it in coexistence mode. Treating this as a rejection was the
            // old behaviour and it threw away a connection Meta had already made.
            signupReported = true;
            cleanupSignup();
            resolve({ ...(payload.data || {}), coexistence: true });
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
              features: [{ name: "whatsapp_business_app_onboarding", enabled: true }],
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
      // This product connects an existing WhatsApp Business app number only. The server
      // independently verifies the number with Meta; this value never overrides that proof.
      const result = await api("/integrations/whatsapp/embedded-signup/complete", {
        method: "POST",
        body: {
          code: authCode,
          waba_id: wabaId,
          phone_number_id: phoneNumberId,
          onboarding_mode: "coexistence",
        },
      });
      setNotice(whatsappConnectedNotice(result, isAr));
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
        api(`/integrations/meta/oauth/start?provider=${encodeURIComponent(metaOauthProvider(channel.id, instagramMethod))}`),
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

  return {
    metaConnecting,
    setMetaConnecting,
    instagramMethod,
    setInstagramMethod,
    connectingMs,
    whatsappSdkLoading,
    whatsappSdkError,
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
  };
}
