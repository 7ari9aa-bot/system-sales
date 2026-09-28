"use client";

/** Owner decision 2026-09-27: Home + My Work merged into ONE Overview
 *  surface. The section lives on the dashboard now; this route redirects so
 *  old links and saved views do not die. */
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function MyWorkPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/dashboard");
  }, [router]);
  return null;
}
