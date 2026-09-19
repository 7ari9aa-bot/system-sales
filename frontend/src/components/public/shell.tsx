"use client";

/** Shell مشترك لكل صفحات الموقع العام — Provider + Navbar + Footer + التوهج. */

import { FihristProvider, FihristRoot } from "@/components/public/i18n";

/** Provider + root فقط — الـchrome (navbar/footer/توهج) بيقدمه (public)/layout.tsx */
export function PublicShell({ children }: { children: React.ReactNode }) {
  return (
    <FihristProvider>
      <FihristRoot>{children}</FihristRoot>
    </FihristProvider>
  );
}
