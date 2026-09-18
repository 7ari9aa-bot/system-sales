"use client";

import * as React from "react";
import { ArrowDownToLine, ArrowUpFromLine, Scale, Warehouse } from "lucide-react";
import { useBalances, useMovements, useRecordMovement, type Balance, type Movement } from "@/lib/queries";
import { t } from "@/lib/t";
import { formatNumber } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input, Label, Select } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyState, PageHeader } from "@/components/ui/states";
import { Skeleton } from "@/components/ui/skeleton";

export default function InventoryPage() {
  const [variantId, setVariantId] = React.useState("");
  const [warehouseId, setWarehouseId] = React.useState("");
  const [direction, setDirection] = React.useState("in");
  const [quantity, setQuantity] = React.useState("1");

  const balancesQuery = useBalances();
  const movementsQuery = useMovements();
  const record = useRecordMovement();

  const balances = balancesQuery.data ?? [];
  const movements = movementsQuery.data ?? [];

  function submit() {
    if (!variantId || !warehouseId) return;
    record.mutate({
      variant_id: variantId,
      warehouse_id: warehouseId,
      direction,
      quantity: Number(quantity),
      reason: direction === "in" ? "purchase" : direction === "out" ? "sale" : "adjustment",
    });
  }

  return (
    <div>
      <PageHeader title={t.inventory} description="أرصدة المخزون وحركات الإضافة والصرف" />

      <Card className="mb-4">
        <CardHeader>
          <CardTitle>{t.recordMovement}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <div>
              <Label htmlFor="iv-variant">Variant ID</Label>
              <Input id="iv-variant" dir="ltr" value={variantId} onChange={(e) => setVariantId(e.target.value)} />
            </div>
            <div>
              <Label htmlFor="iv-wh">{t.warehouse}</Label>
              <Input id="iv-wh" dir="ltr" value={warehouseId} onChange={(e) => setWarehouseId(e.target.value)} />
            </div>
            <div>
              <Label htmlFor="iv-dir">{t.movementType}</Label>
              <Select id="iv-dir" value={direction} onChange={(e) => setDirection(e.target.value)}>
                <option value="in">{t.in}</option>
                <option value="out">{t.out}</option>
                <option value="adjust">{t.adjust}</option>
              </Select>
            </div>
            <div>
              <Label htmlFor="iv-qty">{t.quantity}</Label>
              <Input
                id="iv-qty"
                type="number"
                dir="ltr"
                min="1"
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
              />
            </div>
            <div className="flex items-end">
              <Button
                onClick={submit}
                disabled={record.isPending || !variantId || !warehouseId}
                data-testid="record-movement"
                className="w-full"
              >
                {t.recordMovement}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* balances */}
      <Card className="mb-4">
        <CardHeader>
          <CardTitle>{t.balances}</CardTitle>
        </CardHeader>
        <CardContent className="p-0 pb-2 [&>div]:px-0">
          {balancesQuery.isLoading ? (
            <div className="space-y-2 p-5" aria-busy="true" aria-label={t.loading}>
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-9" />
              ))}
            </div>
          ) : balances.length === 0 ? (
            <EmptyState
              icon={<Warehouse aria-hidden="true" />}
              title={t.noBalances}
              description={t.noBalancesHint}
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Variant</TableHead>
                  <TableHead>{t.warehouse}</TableHead>
                  <TableHead>{t.onHand}</TableHead>
                  <TableHead>{t.reserved}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {balances.map((b: Balance) => (
                  <TableRow key={`${b.variant_id}-${b.warehouse_id}`}>
                    <TableCell dir="ltr" className="text-xs text-muted-foreground">
                      {b.variant_id.slice(0, 8)}…
                    </TableCell>
                    <TableCell dir="ltr" className="text-xs text-muted-foreground">
                      {b.warehouse_id.slice(0, 8)}…
                    </TableCell>
                    <TableCell dir="ltr" className="font-semibold">
                      {b.on_hand}
                    </TableCell>
                    <TableCell dir="ltr">{b.reserved}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* movements log */}
      <Card>
        <CardHeader>
          <CardTitle>{t.movementsLog}</CardTitle>
        </CardHeader>
        <CardContent className="p-0 pb-2">
          {movementsQuery.isLoading ? (
            <div className="space-y-2 p-5" aria-busy="true" aria-label={t.loading}>
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-9" />
              ))}
            </div>
          ) : movements.length === 0 ? (
            <EmptyState
              icon={<Scale aria-hidden="true" />}
              title={t.noMovements}
              description={t.noMovementsHint}
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t.date}</TableHead>
                  <TableHead>Variant</TableHead>
                  <TableHead>{t.movementType}</TableHead>
                  <TableHead>{t.quantity}</TableHead>
                  <TableHead>{t.balanceAfter}</TableHead>
                  <TableHead>{t.reason}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {movements.slice(0, 20).map((m: Movement) => (
                  <TableRow key={m.id}>
                    <TableCell dir="ltr" className="text-xs text-muted-foreground">
                      {new Date(m.created_at).toLocaleString("ar-EG-u-nu-latn")}
                    </TableCell>
                    <TableCell dir="ltr" className="text-xs text-muted-foreground">
                      {m.variant_id.slice(0, 8)}…
                    </TableCell>
                    <TableCell>
                      <Badge variant={m.direction === "in" ? "success" : m.direction === "out" ? "danger" : "default"}>
                        <span className="flex items-center gap-1">
                          {m.direction === "in" ? (
                            <ArrowDownToLine className="size-3" aria-hidden="true" />
                          ) : m.direction === "out" ? (
                            <ArrowUpFromLine className="size-3" aria-hidden="true" />
                          ) : null}
                          {m.direction === "in" ? t.in : m.direction === "out" ? t.out : t.adjust}
                        </span>
                      </Badge>
                    </TableCell>
                    <TableCell dir="ltr">{formatNumber(m.quantity)}</TableCell>
                    <TableCell dir="ltr">{m.balance_after}</TableCell>
                    <TableCell className="text-[13px] text-muted-foreground">{m.reason}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
