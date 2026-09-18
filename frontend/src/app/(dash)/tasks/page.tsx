"use client";

import Link from "next/link";
import { ListChecks } from "lucide-react";
import { t } from "@/lib/t";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, PageHeader } from "@/components/ui/states";

/** مهامي — صفحة هيكلية: المهام تُبنى تلقائيًا من المحادثات والطلبات لاحقًا. */
export default function TasksPage() {
  return (
    <div>
      <PageHeader title={t.myTasks} description="المهام المرتبطة بالعملاء والطلبات" />
      <Card>
        <EmptyState
          icon={<ListChecks aria-hidden="true" />}
          title={t.tasksEmpty}
          description={t.tasksEmptyHint}
          action={
            <Button size="sm" asChild>
              <Link href="/inbox">{t.inbox}</Link>
            </Button>
          }
        />
      </Card>
    </div>
  );
}
