"use client";

/**
 * NotificationsBell — dropdown bell icon in the top-bar.
 *
 * - Shows unread count badge (live-updated via useUnreadCount + realtime SSE)
 * - Dropdown lists the 20 most recent notifications
 * - Click on item: marks as read + navigates to action_url
 * - "Mark all read" button
 * - Updates in realtime when the SSE gateway delivers notification.events
 */

import * as React from "react";
import { useCallback } from "react";
import { useRouter } from "next/navigation";
import { Bell, Check, CheckCheck, Info, ShoppingCart, MessageCircle, AlertCircle } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import {
  useNotifications,
  useUnreadCount,
  useMarkRead,
  useMarkAllRead,
  type Notification,
} from "@/lib/queries";
import { useRealtimeEvents, type RealtimeEvent } from "@/lib/use-realtime";
import { cn } from "@/lib/utils";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

/* ------------------------------------------------------------------- icons */

const KIND_ICON: Record<string, React.ReactNode> = {
  new_message: <MessageCircle className="h-4 w-4 text-primary" aria-hidden />,
  assignment: <Info className="h-4 w-4 text-blue-500" aria-hidden />,
  mention: <Info className="h-4 w-4 text-indigo-500" aria-hidden />,
  order_update: <ShoppingCart className="h-4 w-4 text-amber-500" aria-hidden />,
  task_due: <AlertCircle className="h-4 w-4 text-danger" aria-hidden />,
  system: <Info className="h-4 w-4 text-muted-foreground" aria-hidden />,
};

/** ثابت على مستوى الوحدة — مصفوفة جديدة كل render كانت تعيد توصيل SSE كل مرة */
const BELL_STREAMS: string[] = ["notification.events"];

/* -------------------------------------------------------------- component */

export function NotificationsBell() {
  const router = useRouter();
  const qc = useQueryClient();

  const { data: countData } = useUnreadCount();
  const { data: rawNotifications } = useNotifications({ limit: 20 });
  const notifications: Notification[] = Array.isArray(rawNotifications)
    ? rawNotifications
    : Array.isArray((rawNotifications as unknown as { items?: Notification[] })?.items)
      ? ((rawNotifications as unknown as { items: Notification[] }).items)
      : [];
  const markRead = useMarkRead();
  const markAll = useMarkAllRead();

  const unread = countData?.count ?? 0;

  // §111 — Live-update when the SSE gateway delivers a notification event.
  // الـpayload يحمل notification_id فقط (لا شكل Notification كامل)، فلا يمكن
  // تطبيقه محليًا — الحد الأدنى إذًا: تحديث الكاشات الثلاثة المتأثرة فقط
  // (العدّاد، القائمة، الملخص) ولا شيء آخر، مع بوابة على شكل الـpayload.
  const onEvent = useCallback(
    (event: RealtimeEvent) => {
      if (event.stream !== "notification.events") return;
      const notificationId = event.payload.notification_id;
      if (typeof notificationId !== "string" || !notificationId) return;
      qc.invalidateQueries({ queryKey: ["notifications", "unread-count"] });
      qc.invalidateQueries({ queryKey: ["notifications", "list"] });
      qc.invalidateQueries({ queryKey: ["notifications", "summary"] });
    },
    [qc]
  );
  useRealtimeEvents({ streams: BELL_STREAMS, onEvent });

  function handleClick(notif: Notification) {
    if (!notif.read_at) markRead.mutate(notif.id);
    if (notif.action_url) router.push(notif.action_url);
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="relative"
          aria-label={`الإشعارات${unread ? ` — ${unread} غير مقروءة` : ""}`}
          id="notifications-bell-btn"
        >
          <Bell className="h-5 w-5" />
          {unread > 0 && (
            <Badge
              variant="danger"
              className="absolute -top-1 -end-1 h-4 min-w-4 px-1 text-[10px] leading-none"
              aria-hidden
            >
              {unread > 99 ? "99+" : unread}
            </Badge>
          )}
        </Button>
      </DropdownMenuTrigger>

      <DropdownMenuContent
        align="end"
        className="w-80 max-h-[480px] overflow-y-auto"
        id="notifications-dropdown"
        aria-label="الإشعارات"
      >
        <div className="flex items-center justify-between px-3 py-2">
          <DropdownMenuLabel className="p-0 text-sm font-semibold">
            الإشعارات
          </DropdownMenuLabel>
          {unread > 0 && (
            <DropdownMenuItem
              onSelect={() => markAll.mutate()}
              className="text-xs text-primary hover:underline px-1 py-0"
              aria-label="قراءة الكل"
            >
              <CheckCheck className="h-3.5 w-3.5" />
              قراءة الكل
            </DropdownMenuItem>
          )}
        </div>
        <DropdownMenuSeparator />

        {notifications.length === 0 && (
          <p className="px-3 py-6 text-center text-sm text-muted-foreground">
            لا توجد إشعارات
          </p>
        )}

        {notifications.map((n) => (
          <DropdownMenuItem
            key={n.id}
            aria-label={[n.title, n.body].filter(Boolean).join(" — ")}
            className={cn(
              "w-full flex items-start gap-3 px-3 py-2.5 text-start",
              !n.read_at && "bg-primary-soft/40"
            )}
            onSelect={() => handleClick(n)}
          >
            <span className="mt-0.5 shrink-0">
              {KIND_ICON[n.kind] ?? KIND_ICON.system}
            </span>
            <div className="min-w-0 flex-1">
              {n.title && (
                <p className="truncate text-sm font-medium">{n.title}</p>
              )}
              <p className="text-sm text-muted-foreground line-clamp-2">{n.body}</p>
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                {new Date(n.created_at).toLocaleString("ar-EG", {
                  dateStyle: "short",
                  timeStyle: "short",
                })}
              </p>
            </div>
            {!n.read_at && (
              <span
                className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-primary"
                aria-hidden
              />
            )}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
