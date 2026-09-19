"use client";

import * as React from "react";
import Link from "next/link";
import {
  MessageSquare,
  ShoppingBag,
  Phone,
  Mail,
  Calendar,
  DollarSign,
  UserCheck,
  Ban,
  Copy,
  ExternalLink,
} from "lucide-react";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useCustomer, useOrders, type Customer } from "@/lib/queries";
import { formatTime } from "@/lib/utils";
import { toast } from "@/components/ui/toast";

type CustomerDrawerProps = {
  customerId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export function CustomerDrawer({ customerId, open, onOpenChange }: CustomerDrawerProps) {
  const customerQuery = useCustomer(customerId);
  const ordersQuery = useOrders();
  const customer = customerQuery.data;

  const customerOrders = React.useMemo(() => {
    if (!customerId || !ordersQuery.data) return [];
    return ordersQuery.data.filter((o) => o.customer_id === customerId);
  }, [customerId, ordersQuery.data]);

  function copy(text: string, label: string) {
    navigator.clipboard.writeText(text);
    toast({ title: "تم النسخ", description: `تم نسخ ${label} إلى الحافظة.` });
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="end" className="w-full max-w-md p-6 overflow-y-auto">
        <SheetHeader className="text-start pb-4 border-b border-border">
          <div className="flex items-center gap-3">
            <div className="flex size-12 items-center justify-center rounded-full bg-primary/10 text-primary font-bold text-lg">
              {customer?.name?.slice(0, 2) || "عم"}
            </div>
            <div className="flex-1 min-w-0">
              <SheetTitle className="text-lg font-bold truncate">
                {customer?.name || "تفاصيل العميل"}
              </SheetTitle>
              <SheetDescription className="flex items-center gap-2 mt-1">
                {customer?.is_blocked ? (
                  <Badge variant="danger" className="flex items-center gap-1">
                    <Ban className="size-3" />
                    محظور
                  </Badge>
                ) : (
                  <Badge variant="success" className="flex items-center gap-1">
                    <UserCheck className="size-3" />
                    نشط
                  </Badge>
                )}
                <span className="text-xs text-muted-foreground" dir="ltr">
                  #{customerId?.slice(0, 8)}
                </span>
              </SheetDescription>
            </div>
          </div>
        </SheetHeader>

        {customerQuery.isLoading ? (
          <div className="py-8 space-y-4 animate-pulse">
            <div className="h-4 bg-muted rounded w-3/4" />
            <div className="h-4 bg-muted rounded w-1/2" />
            <div className="h-20 bg-muted rounded w-full" />
          </div>
        ) : !customer ? (
          <div className="py-8 text-center text-muted-foreground text-sm">
            لم يتم العثور على بيانات العميل
          </div>
        ) : (
          <div className="space-y-6 pt-4">
            {/* Quick Financial Stats */}
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-xl border border-border bg-muted/40 p-3 text-start">
                <div className="flex items-center gap-1 text-xs text-muted-foreground">
                  <DollarSign className="size-3.5" />
                  إجمالي المشتريات
                </div>
                <div className="mt-1 text-lg font-bold" dir="ltr">
                  {Number(customer.lifetime_value || 0).toLocaleString("en-US", {
                    minimumFractionDigits: 2,
                  })}{" "}
                  <span className="text-xs font-normal">ج.م</span>
                </div>
              </div>
              <div className="rounded-xl border border-border bg-muted/40 p-3 text-start">
                <div className="flex items-center gap-1 text-xs text-muted-foreground">
                  <ShoppingBag className="size-3.5" />
                  عدد الطلبات
                </div>
                <div className="mt-1 text-lg font-bold" dir="ltr">
                  {customerOrders.length}
                </div>
              </div>
            </div>

            {/* Contact Information */}
            <div className="space-y-3">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                بيانات الاتصال
              </h3>
              <div className="space-y-2 text-sm">
                <div className="flex items-center justify-between rounded-lg border border-border p-2.5">
                  <span className="flex items-center gap-2 text-muted-foreground text-xs">
                    <Phone className="size-4" />
                    الهاتف
                  </span>
                  <div className="flex items-center gap-2">
                    <span dir="ltr" className="font-medium text-xs">
                      {customer.phone || "—"}
                    </span>
                    {customer.phone && (
                      <Button
                        size="icon"
                        variant="ghost"
                        className="size-7"
                        onClick={() => copy(customer.phone!, "رقم الهاتف")}
                      >
                        <Copy className="size-3.5" />
                      </Button>
                    )}
                  </div>
                </div>

                <div className="flex items-center justify-between rounded-lg border border-border p-2.5">
                  <span className="flex items-center gap-2 text-muted-foreground text-xs">
                    <Mail className="size-4" />
                    البريد
                  </span>
                  <div className="flex items-center gap-2">
                    <span dir="ltr" className="font-medium text-xs truncate max-w-[180px]">
                      {customer.email || "—"}
                    </span>
                    {customer.email && (
                      <Button
                        size="icon"
                        variant="ghost"
                        className="size-7"
                        onClick={() => copy(customer.email!, "البريد الإلكتروني")}
                      >
                        <Copy className="size-3.5" />
                      </Button>
                    )}
                  </div>
                </div>
              </div>
            </div>

            {/* Quick Actions */}
            <div className="space-y-3">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                إجراءات سريعة
              </h3>
              <div className="grid grid-cols-2 gap-2">
                <Button variant="outline" asChild className="w-full justify-start text-xs">
                  <Link href={`/inbox`}>
                    <MessageSquare className="size-3.5 me-2" />
                    محادثة العميل
                  </Link>
                </Button>
                <Button variant="outline" asChild className="w-full justify-start text-xs">
                  <Link href={`/orders`}>
                    <ShoppingBag className="size-3.5 me-2" />
                    إنشاء طلب جديد
                  </Link>
                </Button>
              </div>
            </div>

            {/* Recent Orders List */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  أحدث الطلبات
                </h3>
                <Link href="/orders" className="text-xs text-primary hover:underline flex items-center gap-1">
                  عرض الكل <ExternalLink className="size-3" />
                </Link>
              </div>

              {customerOrders.length === 0 ? (
                <div className="rounded-lg border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
                  لا توجد طلبات سابقة لهذا العميل بعد
                </div>
              ) : (
                <div className="space-y-2">
                  {customerOrders.slice(0, 4).map((order) => (
                    <div
                      key={order.id}
                      className="flex items-center justify-between rounded-lg border border-border p-2.5 text-xs hover:bg-muted/50 transition-colors"
                    >
                      <div>
                        <div className="font-bold" dir="ltr">
                          {order.number}
                        </div>
                        <div className="text-[11px] text-muted-foreground">
                          {formatTime(order.created_at)}
                        </div>
                      </div>
                      <div className="text-end">
                        <div className="font-bold" dir="ltr">
                          {Number(order.grand_total).toFixed(2)} {order.currency}
                        </div>
                        <Badge
                          variant={
                            order.status === "confirmed" || order.status === "delivered"
                              ? "success"
                              : order.status === "cancelled"
                              ? "danger"
                              : "default"
                          }
                          className="mt-0.5 text-[10px] px-1.5 py-0"
                        >
                          {order.status}
                        </Badge>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
