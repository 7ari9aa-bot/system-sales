import { useState } from "react";
import { CalendarDays, Coins, DatabaseBackup, Download, HardDriveDownload, History } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/cashier/components/ui/button";
import { Label } from "@/cashier/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import DataTable from "@/cashier/components/ui-kit/DataTable";
import SectionCard from "@/cashier/components/ui-kit/SectionCard";
import StatCard from "@/cashier/components/ui-kit/StatCard";
import StatusBadge from "@/cashier/components/ui-kit/StatusBadge";
import ConfirmDialog from "@/cashier/components/ui-kit/ConfirmDialog";
import {
  BACKUP_SCHEDULES,
  BACKUP_SIZE_LABEL,
  BACKUP_TOTAL_RECORDS,
  backupRecords,
  backupTableCounts,
  buildBackupPayload,
} from "@/cashier/lib/backupData";
import { fmtDateTime, fmtInt } from "@/cashier/lib/format";
import { exportJson } from "@/cashier/lib/exportCsv";

// تبويب النسخ الاحتياطي داخل الإعدادات: إنشاء وتنزيل واستعادة وحذف النسخ + جدولة النسخ التلقائي.
export default function BackupTab() {
  const [records, setRecords] = useState(backupRecords);
  const [schedule, setSchedule] = useState("daily");
  const [deleting, setDeleting] = useState(null);
  const [restoring, setRestoring] = useState(null);

  const last = records[0] ?? null;
  const scheduleLabel = BACKUP_SCHEDULES.find((s) => s.key === schedule)?.label ?? "";

  function nextNumber() {
    const max = records.reduce((m, r) => Math.max(m, Number(String(r.number).replace(/\D/g, "")) || 0), 0);
    return `BK-2026-${String(max + 1).padStart(4, "0")}`;
  }

  function createBackup() {
    const number = nextNumber();
    exportJson(`${number}.json`, buildBackupPayload());
    setRecords((prev) => [
      {
        id: `bk-new-${prev.length + 1}`,
        number,
        date: new Date().toISOString(),
        type: "manual",
        size: BACKUP_SIZE_LABEL,
        records: BACKUP_TOTAL_RECORDS,
        status: "completed",
        createdBy: "منى عبد الله",
        note: "نسخة يدوية من شاشة الإعدادات",
        restoredAt: null,
      },
      ...prev,
    ]);
    toast.success(`تم إنشاء النسخة ${number} وتنزيلها على الجهاز`);
  }

  function restoreBackup(record) {
    setRecords((prev) => prev.map((r) => (r.id === record.id ? { ...r, restoredAt: new Date().toISOString() } : r)));
    toast.success(`تمت استعادة النسخة ${record.number} (${fmtInt(record.records)} سجلًا)`);
  }

  function deleteBackup(record) {
    setRecords((prev) => prev.filter((r) => r.id !== record.id));
    toast.success(`تم حذف النسخة ${record.number}`);
  }

  const columns = [
    {
      key: "number",
      header: "النسخة",
      render: (r) => (
        <span>
          <span className="num block font-medium">{r.number}</span>
          <span className="block text-[11px] text-muted-foreground">{r.note}</span>
        </span>
      ),
    },
    { key: "date", header: "تاريخ الإنشاء", render: (r) => <span className="num text-xs">{fmtDateTime(r.date)}</span> },
    { key: "type", header: "النوع", render: (r) => <StatusBadge kind="backup_type" value={r.type} /> },
    { key: "size", header: "الحجم", align: "center", render: (r) => <span className="num text-xs">{r.size}</span> },
    { key: "records", header: "عدد السجلات", align: "center", render: (r) => <span className="num">{fmtInt(r.records)}</span> },
    { key: "createdBy", header: "أنشأها", render: (r) => <span className="text-xs text-muted-foreground">{r.createdBy}</span> },
    { key: "status", header: "الحالة", render: (r) => <StatusBadge kind="backup" value={r.status} /> },
    { key: "restoredAt", header: "آخر استعادة", render: (r) => <span className="num text-xs">{r.restoredAt ? fmtDateTime(r.restoredAt) : "—"}</span> },
    {
      key: "actions",
      header: "إجراءات",
      sortable: false,
      align: "center",
      render: (r) => (
        <span className="flex items-center justify-center gap-1.5">
          <Button
            variant="outline"
            size="sm"
            className="h-8 gap-1.5 text-xs"
            onClick={() => {
              exportJson(`${r.number}.json`, buildBackupPayload());
              toast.success(`تم تنزيل النسخة ${r.number}`);
            }}
          >
            <Download className="h-3.5 w-3.5" />
            تنزيل
          </Button>
          <Button variant="outline" size="sm" className="h-8 gap-1.5 text-xs" onClick={() => setRestoring(r)}>
            <History className="h-3.5 w-3.5" />
            استعادة
          </Button>
          <Button variant="ghost" size="sm" className="h-8 text-xs text-destructive hover:text-destructive" onClick={() => setDeleting(r)}>
            حذف
          </Button>
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-end gap-2">
        <Button
          variant="outline"
          className="gap-2"
          onClick={() => {
            exportJson("بوتيك-النخبة-بيانات-كاملة.json", buildBackupPayload());
            toast.success("تم تصدير بيانات النظام كاملة");
          }}
        >
          <HardDriveDownload className="h-4 w-4" />
          تصدير بيانات النظام
        </Button>
        <Button className="gap-2 font-bold" onClick={createBackup}>
          <DatabaseBackup className="h-4 w-4" />
          إنشاء نسخة احتياطية الآن
        </Button>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="آخر نسخة احتياطية" value={last ? fmtDateTime(last.date) : "—"} hint={last?.number ?? ""} icon={History} tone="primary" />
        <StatCard label="حجم النسخة" value={BACKUP_SIZE_LABEL} hint="ملف واحد يشمل كل الجداول" icon={HardDriveDownload} tone="info" />
        <StatCard label="سجلات مشمولة" value={fmtInt(BACKUP_TOTAL_RECORDS)} hint={`موزّعة على ${fmtInt(backupTableCounts.length)} جدولًا`} icon={Coins} tone="violet" />
        <StatCard label="نسخ محفوظة" value={fmtInt(records.length)} hint={scheduleLabel} icon={DatabaseBackup} tone="success" />
      </div>

      <SectionCard
        title="النسخ التلقائي"
        description="يتم إنشاء النسخة تلقائيًا في الموعد المحدد دون إيقاف العمل"
        action={
          <div className="w-[220px]">
            <Select value={schedule} onValueChange={setSchedule}>
              <SelectTrigger className="h-9">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {BACKUP_SCHEDULES.map((s) => (
                  <SelectItem key={s.key} value={s.key}>
                    {s.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        }
      >
        <div className="flex flex-wrap items-center gap-2">
          <Label className="text-xs text-muted-foreground">الجداول المشمولة في النسخة:</Label>
          {backupTableCounts.map((t) => (
            <span key={t.key} className="rounded-lg border border-border px-2.5 py-1 text-[11px]">
              {t.label}: <span className="num font-bold">{fmtInt(t.count)}</span>
            </span>
          ))}
        </div>
      </SectionCard>

      <DataTable
        columns={columns}
        rows={records}
        pageSize={8}
        emptyTitle="لا توجد نسخ محفوظة"
        emptyDescription="أنشئ نسخة احتياطية الآن لحفظ بيانات المحل."
        toolbar={
          <p className="num flex items-center gap-1.5 text-xs text-muted-foreground">
            <CalendarDays className="h-3.5 w-3.5" />
            {fmtInt(records.length)} نسخة محفوظة • آخر نسخة {last ? fmtDateTime(last.date) : "—"}
          </p>
        }
      />

      <ConfirmDialog
        open={Boolean(restoring)}
        onOpenChange={(open) => !open && setRestoring(null)}
        title={`استعادة النسخة ${restoring?.number ?? ""}؟`}
        description={`سيتم إرجاع بيانات المحل إلى حالة ${restoring ? fmtDateTime(restoring.date) : ""} (${fmtInt(restoring?.records ?? 0)} سجلًا).`}
        confirmLabel="استعادة النسخة"
        tone="primary"
        onConfirm={() => {
          restoreBackup(restoring);
          setRestoring(null);
        }}
      />
      <ConfirmDialog
        open={Boolean(deleting)}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={`حذف النسخة ${deleting?.number ?? ""}؟`}
        description="سيتم حذف ملف النسخة من السجل ولا يمكن استعادته بعد الحذف."
        confirmLabel="حذف النسخة"
        onConfirm={() => {
          deleteBackup(deleting);
          setDeleting(null);
        }}
      />
    </div>
  );
}