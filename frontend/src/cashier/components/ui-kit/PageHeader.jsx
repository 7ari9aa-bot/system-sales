// رأس صفحة موحّد: العنوان، وصف مختصر، وأزرار الإجراءات.
export default function PageHeader({ title, description, children }) {
  return (
    <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
      <div>
        <h1 className="font-heading text-base font-bold tracking-tight sm:text-lg">{title}</h1>
        {description && <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}