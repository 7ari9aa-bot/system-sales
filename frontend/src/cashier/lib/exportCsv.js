// تصدير أي جدول إلى ملف CSV يفتح مباشرة في Excel (بترميز يدعم العربية).
// تنزيل أي بيانات كملف JSON (يُستخدم في النسخ الاحتياطي).
export function exportJson(filename, data) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

export function exportCsv(filename, columns, rows) {
  const header = columns.map((c) => `"${c.header}"`).join(",");
  const body = rows
    .map((row) =>
      columns
        .map((c) => {
          const value = c.value ? c.value(row) : row[c.key];
          const text = value === null || value === undefined ? "" : String(value).replace(/"/g, '""');
          return `"${text}"`;
        })
        .join(","),
    )
    .join("\n");

  const csv = `\ufeff${header}\n${body}`;
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}