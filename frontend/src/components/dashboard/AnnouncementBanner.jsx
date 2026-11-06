import React, { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { Info, Megaphone, TriangleAlert, Wrench, X } from "lucide-react";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

// Supabase-style slim notice: one live platform announcement at a time, tinted
// by kind, dismissible per user when the console allows it. Hidden on the
// full-height work surfaces (inbox, till screens) where a shifting banner
// would move a fixed-height table mid-session.
const KINDS = {
  info: { icon: Info, wrap: "border-s-4 border-s-blue-500 bg-blue-500/5" },
  update: { icon: Megaphone, wrap: "border-s-4 border-s-teal-600 bg-teal-600/5" },
  warning: { icon: TriangleAlert, wrap: "border-s-4 border-s-amber-500 bg-amber-500/5" },
  maintenance: { icon: Wrench, wrap: "border-s-4 border-s-violet-500 bg-violet-500/5" },
};

export default function AnnouncementBanner() {
  const { t } = useI18n();
  // The banner stays mounted across navigation inside DashboardLayout, so a
  // fetch-on-mount only ever saw what existed at load time. The route path is
  // the dependency: a notice published mid-session appears on the next
  // navigation without a full reload.
  const { pathname } = useLocation();
  const [announcement, setAnnouncement] = useState(null);
  // The dismissed id, not a boolean: a route-change re-fetch must keep the
  // dismissed notice hidden while letting a NEW announcement through.
  const [dismissedId, setDismissedId] = useState(null);
  const [dismissing, setDismissing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api("/platform/announcements/active")
      .then((data) => {
        if (!cancelled) setAnnouncement(data?.announcement ?? null);
      })
      .catch(() => {
        // A banner is never worth an error surface — stay quiet.
      });
    return () => {
      cancelled = true;
    };
  }, [pathname]);

  if (!announcement || announcement.id === dismissedId) return null;

  const kind = KINDS[announcement.kind] ?? KINDS.info;
  const Icon = kind.icon;

  const dismiss = async () => {
    setDismissing(true);
    try {
      await api(`/platform/announcements/${announcement.id}/dismiss`, { method: "POST" });
    } catch {
      // Optimistic hide regardless: the server re-shows it only if the
      // tombstone never landed, which is the honest failure direction.
    }
    setDismissedId(announcement.id);
  };

  return (
    <div
      dir="auto"
      className={cn(
        "mx-4 mt-3 flex items-start gap-3 rounded-xl border border-border px-4 py-3 text-sm sm:mx-6 lg:mx-8",
        kind.wrap,
        dismissing && "opacity-60"
      )}
      role="status"
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="font-medium leading-snug">{announcement.title}</p>
        {announcement.body ? (
          <p className="mt-0.5 leading-snug text-muted-foreground">{announcement.body}</p>
        ) : null}
        {announcement.cta_label && announcement.cta_url ? (
          <a
            href={announcement.cta_url}
            className="mt-1.5 inline-block text-xs font-medium underline underline-offset-2 hover:opacity-80"
          >
            {announcement.cta_label}
          </a>
        ) : null}
      </div>
      {announcement.dismissible ? (
        <button
          type="button"
          onClick={dismiss}
          aria-label={t("announcement.dismiss")}
          className="grid h-6 w-6 shrink-0 place-items-center rounded-md text-muted-foreground hover:bg-surface hover:text-foreground"
        >
          <X className="h-4 w-4" />
        </button>
      ) : null}
    </div>
  );
}
