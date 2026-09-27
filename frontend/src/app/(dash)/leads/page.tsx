"use client";

/** Owner IA 2026-09-27: Leads are a Customers VIEW (?filter=lead), not a
 *  second module doing the same job. This route redirects so old links live. */
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function LeadsPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/customers?filter=lead");
  }, [router]);
  return null;
}
