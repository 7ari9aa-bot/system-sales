"use client";

/** Shell مشترك لكل صفحات الموقع العام — Provider + Navbar + Footer + التوهج. */

import { FihristProvider, FihristRoot } from "@/components/public/i18n";
import { PublicNavbar } from "@/components/public/navbar";
import { PublicFooter } from "@/components/public/footer";
import { AmbientGlow } from "@/components/public/ambient-glow";

export function PublicShell({ children }: { children: React.ReactNode }) {
  return (
    <FihristProvider>
      <FihristRoot>
        <AmbientGlow />
        <div className="fh-page">
          <PublicNavbar />
          {children}
          <PublicFooter />
        </div>
      </FihristRoot>
    </FihristProvider>
  );
}
