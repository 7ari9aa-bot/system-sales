"use client";

/** Owner decision 2026-09-28: In a sales system, employees work directly
 *  through conversations, orders, and approvals on the Overview dashboard.
 *  There is no generic tasks rail; this route redirects to /dashboard so
 *  any old links or bookmarks safely land on Overview. */
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function TasksPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/dashboard");
  }, [router]);
  return null;
}
