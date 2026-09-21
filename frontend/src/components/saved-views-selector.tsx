"use client";

import * as React from "react";
import { Bookmark, Plus, Trash2, ChevronDown } from "lucide-react";
import { useSavedViews, useCreateSavedView, useDeleteSavedView } from "@/lib/queries";
import { t } from "@/lib/t";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { cn } from "@/lib/utils";

/** §95 — reusable saved-views dropdown with save dialog and per-view delete. */
export function SavedViewsSelector({
  entity = "customers",
  currentFilters,
  currentSort,
  currentColumns,
  onSelect,
  activeViewId,
  className,
}: {
  entity?: string;
  currentFilters?: Record<string, unknown>;
  currentSort?: Record<string, unknown> | null;
  currentColumns?: string[] | null;
  onSelect?: (view: {
    id: string;
    filters: Record<string, unknown>;
    sort: Record<string, unknown> | null;
    columns: string[] | null;
  }) => void;
  activeViewId?: string | null;
  className?: string;
}) {
  const [saveDialogOpen, setSaveDialogOpen] = React.useState(false);
  const [viewName, setViewName] = React.useState("");
  // §104 — حذف عرض محفوظ إجراء خطر: نافذة تأكيد قبل الـDELETE
  const [deleteTarget, setDeleteTarget] = React.useState<{ id: string; name: string } | null>(
    null,
  );

  const viewsQuery = useSavedViews(entity);
  const createMutation = useCreateSavedView();
  const deleteMutation = useDeleteSavedView();

  const views = viewsQuery.data ?? [];

  function handleSave() {
    const name = viewName.trim();
    if (!name) return;
    createMutation.mutate(
      {
        entity,
        name,
        filters: currentFilters ?? {},
        sort: currentSort ?? null,
        columns: currentColumns ?? null,
      },
      {
        onSuccess: () => {
          setViewName("");
          setSaveDialogOpen(false);
        },
      },
    );
  }

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="secondary" size="sm" className="gap-1.5" data-testid="saved-views-trigger">
            <Bookmark aria-hidden="true" className="size-4" />
            <span className="hidden sm:inline">العروض المحفوظة</span>
            <ChevronDown aria-hidden="true" className="size-3.5" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="min-w-56">
          <DropdownMenuLabel>العروض المحفوظة</DropdownMenuLabel>
          <DropdownMenuSeparator />
          {views.length === 0 && (
            <div className="px-2.5 py-3 text-[13px] text-muted-foreground">مفيش عروض محفوظة بعد</div>
          )}
          {views.map((view) => (
            <div key={view.id} className="flex items-center">
              <DropdownMenuItem
                className="flex-1"
                onSelect={() =>
                  onSelect?.({
                    id: view.id,
                    filters: view.filters,
                    sort: view.sort,
                    columns: view.columns,
                  })
                }
              >
                <Bookmark aria-hidden="true" className="size-4" />
                <span className={cn("flex-1 truncate", activeViewId === view.id && "font-bold text-primary")}>
                  {view.name}
                </span>
              </DropdownMenuItem>
              <button
                type="button"
                aria-label={`حذف العرض ${view.name}`}
                onClick={(e) => {
                  e.stopPropagation();
                  setDeleteTarget({ id: view.id, name: view.name });
                }}
                disabled={deleteMutation.isPending}
                className="rounded-md p-1.5 text-muted-foreground transition-colors duration-150 hover:bg-danger-soft hover:text-danger disabled:opacity-50"
              >
                <Trash2 aria-hidden="true" className="size-3.5" />
              </button>
            </div>
          ))}
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={() => setSaveDialogOpen(true)} data-testid="save-current-view">
            <Plus aria-hidden="true" className="size-4" />
            حفظ العرض الحالي
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <Dialog open={saveDialogOpen} onOpenChange={setSaveDialogOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>حفظ العرض الحالي</DialogTitle>
            <DialogDescription>اكتب اسم للعرض وسيتم حفظ الفلاتر والترتيب الحالي.</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="saved-view-name">اسم العرض</Label>
            <Input
              id="saved-view-name"
              value={viewName}
              onChange={(e) => setViewName(e.target.value)}
              placeholder="مثال: عملاء نشطون"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  handleSave();
                }
              }}
            />
          </div>
          <DialogFooter>
            <Button variant="ghost" size="sm" onClick={() => setSaveDialogOpen(false)} disabled={createMutation.isPending}>
              إلغاء
            </Button>
            <Button size="sm" onClick={handleSave} disabled={!viewName.trim() || createMutation.isPending} data-testid="confirm-save-view">
              {createMutation.isPending ? "جارٍ الحفظ…" : "حفظ"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* §104 — تأكيد حذف العرض */}
      <ConfirmDialog
        open={Boolean(deleteTarget)}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
        title={t.deleteViewConfirmTitle}
        description={deleteTarget ? t.deleteViewConfirmBody(deleteTarget.name) : ""}
        confirmLabel={t.deleteViewConfirmAction}
        pending={deleteMutation.isPending}
        onConfirm={() => {
          if (!deleteTarget) return;
          deleteMutation.mutate(
            { id: deleteTarget.id, entity },
            { onSettled: () => setDeleteTarget(null) },
          );
        }}
      />
    </div>
  );
}
