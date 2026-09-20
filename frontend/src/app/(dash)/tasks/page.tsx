"use client";

import * as React from "react";
import { Check, ListChecks, Plus } from "lucide-react";
import { useCreateTask, useTasks, useUpdateTaskStatus, type Task } from "@/lib/queries";
import { t } from "@/lib/t";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Label, Select, Textarea } from "@/components/ui/input";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui/states";

/* Built at render time so the labels follow the active language. */
function buildStatusLabels(): Record<Task["status"], string> {
  return {
    todo: t.taskTodo,
    in_progress: t.taskInProgress,
    done: t.taskDone,
    cancelled: t.taskCancelled,
  };
}

const STATUS_STYLES: Record<Task["status"], string> = {
  todo: "bg-muted text-muted-foreground",
  in_progress: "bg-primary-soft text-primary",
  done: "bg-success/10 text-success",
  cancelled: "bg-danger/10 text-danger",
};

export default function TasksPage() {
  const [open, setOpen] = React.useState(false);
  const [title, setTitle] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [priority, setPriority] = React.useState("2");
  const [filter, setFilter] = React.useState<"all" | Task["status"]>("all");
  const tasksQuery = useTasks();
  const createTask = useCreateTask();
  const updateStatus = useUpdateTaskStatus();
  const statusLabels = buildStatusLabels();
  const tasks = (tasksQuery.data ?? []).filter((task) => filter === "all" || task.status === filter);

  // Open the form from the top-bar "create" menu (?new=1) or the command palette.
  React.useEffect(() => {
    if (typeof window !== "undefined" && new URLSearchParams(window.location.search).get("new") === "1") {
      setOpen(true);
    }
  }, []);

  function submit() {
    if (!title.trim()) return;
    createTask.mutate(
      { title: title.trim(), description: description.trim() || undefined, priority: Number(priority) },
      {
        onSuccess: () => {
          setOpen(false);
          setTitle("");
          setDescription("");
          setPriority("2");
        },
      },
    );
  }

  if (tasksQuery.error) {
    return <ErrorState message={(tasksQuery.error as Error).message} onRetry={() => tasksQuery.refetch()} />;
  }

  return (
    <div>
      <PageHeader
        title={t.myTasks}
        description="المهام المرتبطة بالعملاء والطلبات"
        actions={<Button onClick={() => setOpen(true)}><Plus aria-hidden="true" />{t.newTask}</Button>}
      />

      <div className="mb-4 flex flex-wrap gap-2" role="group" aria-label={t.actions}>
        {(["all", "todo", "in_progress", "done"] as const).map((value) => (
          <Button key={value} size="sm" variant={filter === value ? "default" : "outline"} onClick={() => setFilter(value)} data-testid={`task-filter-${value}`}>
            {value === "all" ? t.taskAll : statusLabels[value]}
          </Button>
        ))}
      </div>

      {tasksQuery.isLoading ? (
        <Card><CardContent className="space-y-3 p-5"><div className="h-5 w-40 animate-pulse rounded bg-muted" /><div className="h-12 animate-pulse rounded bg-muted" /><div className="h-12 animate-pulse rounded bg-muted" /></CardContent></Card>
      ) : tasks.length === 0 ? (
        <Card><EmptyState icon={<ListChecks aria-hidden="true" />} title={t.tasksEmpty} description={filter === "all" ? t.tasksEmptyHint : t.noTableResults} testid="tasks-empty" action={<Button size="sm" onClick={() => setOpen(true)}><Plus aria-hidden="true" />{t.newTask}</Button>} /></Card>
      ) : (
        <Card>
          <CardContent className="divide-y divide-border p-0">
            {tasks.map((task) => (
              <div key={task.id} className="flex flex-wrap items-center gap-3 p-4">
                <div className="min-w-0 flex-1">
                  <div className="font-semibold">{task.title}</div>
                  <div className="mt-1 text-xs text-muted-foreground">{task.source} · {t.taskPriority}: {task.priority}</div>
                </div>
                <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${STATUS_STYLES[task.status]}`}>{statusLabels[task.status]}</span>
                {task.status !== "done" && task.status !== "cancelled" ? (
                  <Button size="sm" variant="outline" onClick={() => updateStatus.mutate({ taskId: task.id, status: "done" })} disabled={updateStatus.isPending} data-testid={`task-done-${task.id}`}>
                    <Check aria-hidden="true" />{t.taskMarkDone}
                  </Button>
                ) : task.status === "done" ? (
                  <Button size="sm" variant="ghost" onClick={() => updateStatus.mutate({ taskId: task.id, status: "todo" })} disabled={updateStatus.isPending} data-testid={`task-reopen-${task.id}`}>{t.taskReopen}</Button>
                ) : null}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>{t.newTask}</DialogTitle><DialogDescription>{t.tasksEmptyHint}</DialogDescription></DialogHeader>
          <div className="space-y-4 py-2">
            <div><Label htmlFor="task-title">{t.taskTitle}</Label><Input id="task-title" value={title} onChange={(e) => setTitle(e.target.value)} autoFocus /></div>
            <div><Label htmlFor="task-description">{t.taskDescription}</Label><Textarea id="task-description" value={description} onChange={(e) => setDescription(e.target.value)} /></div>
            <div><Label htmlFor="task-priority">{t.taskPriority}</Label><Select id="task-priority" value={priority} onChange={(e) => setPriority(e.target.value)}><option value="1">1</option><option value="2">2</option><option value="3">3</option></Select></div>
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setOpen(false)}>{t.cancel}</Button><Button onClick={submit} disabled={!title.trim() || createTask.isPending} data-testid="task-submit">{t.taskCreate}</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
