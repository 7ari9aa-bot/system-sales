import { Link } from "react-router-dom";
import { ArrowUpRight } from "lucide-react";

/**
 * The card a record screen shows inside the Center: where the rows actually live.
 *
 * The Settings Center configures. A page whose job is to list, edit or audit RECORDS (suppliers,
 * purchase orders, customer records, the inbox, reports, run logs) belongs to the module that
 * owns those rows. Keeping a copy here meant two editors for one table, and the copy in Settings
 * was the one that fell behind.
 *
 * The page keeps its address, so a bookmark or a link in a message still lands on an answer:
 * this card, and one button to the real screen.
 */
export function ModuleLinkPage({ to, title, isAr }) {
  return (
    <div className="max-w-xl rounded-xl border border-border bg-card p-6">
      <h2 className="font-display text-[16px] font-semibold">{title}</h2>
      <p className="mt-2 text-[13px] leading-relaxed text-muted-foreground">
        {isAr
          ? "الشاشة دي بتعرض سجلات، مش إعدادات، فمكانها الطبيعي في الموديول اللي بيملك السجلات دي. الإعدادات نفسها لسه هنا في مركز الإعدادات."
          : "This screen shows records, not settings, so it lives in the module that owns those records. The settings that shape it are still here in the Settings Center."}
      </p>
      <Link
        to={to}
        data-testid="module-link"
        className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-[13px] font-medium text-primary-foreground"
      >
        {isAr ? "افتح الشاشة الأصلية" : "Open the real screen"}
        <ArrowUpRight className="h-3.5 w-3.5" />
      </Link>
    </div>
  );
}

/**
 * The one-line version, for a page that keeps its own settings.
 *
 * A page like Transfers owns two real settings (`show_warehouse_transfers`,
 * `quality_check_on_receipt`), so it cannot become a link card — the registry would lose the
 * only editor for those keys. Its RECORD list still belongs to the module, so the list goes and
 * this note takes its place: the settings stay, the rows are one click away.
 */
export function ModuleRecordsNote({ to, isAr }) {
  return (
    <div className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-[12.5px] text-muted-foreground">
      {isAr
        ? "السجلات نفسها (الحركات والعمليات) مكانها الموديول، والإعدادات اللي فوق هي اللي بتتحكم فيها."
        : "The records themselves live in the module; the settings above are what shape them."}{" "}
      <Link to={to} className="font-medium text-primary underline-offset-2 hover:underline" data-testid="module-records-link">
        {isAr ? "افتح السجلات" : "Open the records"}
      </Link>
    </div>
  );
}
