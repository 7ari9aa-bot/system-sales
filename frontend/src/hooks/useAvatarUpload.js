import React from "react";
import { api } from "@/lib/api";
import { avatarErrorKey, isAcceptedImage } from "@/lib/avatarUpload";
import { useAuth } from "@/lib/AuthContext";
import { useT } from "@/lib/i18n";

/** One implementation of "change the account's picture".
 *
 * Two screens offer it (the account menu and the profile page), so the upload, the refusal
 * messages, the refresh of the signed-in user and the busy state live here once. The browser's
 * file picker is opened through `inputRef`, which the caller renders because each screen labels
 * it differently.
 */
export default function useAvatarUpload() {
  const t = useT();
  const { refreshUser } = useAuth();
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [notice, setNotice] = React.useState("");
  const inputRef = React.useRef(null);

  const pick = React.useCallback(() => {
    inputRef.current?.click();
  }, []);

  const upload = React.useCallback(
    async (event) => {
      const file = event.target.files?.[0];
      event.target.value = "";
      if (!file || busy) return;
      if (!isAcceptedImage(file)) {
        setError(t("avatar.notImage"));
        return;
      }
      setBusy(true);
      setError("");
      setNotice("");
      try {
        await api("/users/me/avatar", { method: "PUT", rawBody: file, contentType: file.type });
        await refreshUser();
        setNotice(t("avatar.saved"));
      } catch (failure) {
        // the server's own message can carry storage internals, so the screen never shows it
        setError(t(avatarErrorKey(failure)));
      } finally {
        setBusy(false);
      }
    },
    [busy, refreshUser, t],
  );

  const remove = React.useCallback(async () => {
    if (busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api("/users/me/avatar", { method: "DELETE" });
      await refreshUser();
      setNotice(t("avatar.removed"));
    } catch (failure) {
      setError(t(avatarErrorKey(failure)));
    } finally {
      setBusy(false);
    }
  }, [busy, refreshUser, t]);

  return { inputRef, busy, error, notice, pick, upload, remove };
}
