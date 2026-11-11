import React from "react";
import { ExternalLink, Globe } from "lucide-react";
import { PageHeader, SectionCard } from "@/components/dashboard/ui";
import { useI18n } from "@/lib/i18n";

/**
 * «My Website»: Fihrist no longer hosts or builds websites. They are sold and run by the standalone
 * Fihrist Sites platform, so this page only points the merchant there. The links are the platform's
 * real public pages; nothing here talks to the Fihrist backend.
 */
const SITES = "https://sites.fihrist.world";

export default function Websites() {
  const { lang } = useI18n();
  const L = (ar, en) => (lang === "ar" ? ar : en);

  const links = [
    {
      href: `${SITES}/designs`,
      title: L("تصفح التصاميم", "Browse designs"),
      body: L("شوف التصاميم المتاحة وعاين أي تصميم قبل ما تشتري.", "See the available designs and preview any of them before you buy."),
    },
    {
      href: `${SITES}/dashboard`,
      title: L("لوحة تحكم موقعي", "My site dashboard"),
      body: L("لو اشتريت موقع، أدر المنتجات والطلبات والمحتوى من هنا.", "If you already bought a site, manage its products, orders and content here."),
    },
  ];

  return (
    <div className="mx-auto max-w-[900px]">
      <PageHeader
        title={L("موقعي", "My Website")}
        subtitle={L(
          "المواقع بتتباع وتتدار من منصة Fihrist Sites، وتقدر تربط منتجاتك من فهرست بعد الشراء.",
          "Websites are sold and run on the Fihrist Sites platform, and you can connect your Fihrist products after you buy."
        )}
      />
      <SectionCard title={L("منصة Fihrist Sites", "Fihrist Sites")}>
        <div className="grid gap-3 sm:grid-cols-2">
          {links.map((link) => (
            <a
              key={link.href}
              href={link.href}
              target="_blank"
              rel="noreferrer noopener"
              className="group rounded-xl border border-border p-4 transition-colors hover:bg-surface"
            >
              <div className="flex items-center gap-2 font-medium">
                <Globe className="h-4 w-4 text-primary" />
                {link.title}
                <ExternalLink className="ms-auto h-3.5 w-3.5 text-muted-foreground group-hover:text-foreground" />
              </div>
              <p className="mt-1.5 text-[12.5px] leading-5 text-muted-foreground">{link.body}</p>
            </a>
          ))}
        </div>
      </SectionCard>
    </div>
  );
}
