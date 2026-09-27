"use client";

import * as React from "react";
import { useState } from "react";
import {
  Receipt,
  RotateCcw,
  CheckCircle2,
  AlertCircle,
  Check,
} from "lucide-react";
import {
  useFinancialAccounts,
  useFinancialTransactions,
  useTrialBalance,
  type FinancialAccount,
  type FinancialTransactionItem,
} from "@/lib/queries";
import { getLang } from "@/lib/i18n";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState, ErrorState, PageHeader, TableSkeleton } from "@/components/ui/states";
import { cn } from "@/lib/utils";

type ActiveTab = "TRIAL_BALANCE" | "TRANSACTIONS" | "ACCOUNTS";

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const locale = getLang() === "en" ? "en-GB" : "ar-EG";
  return new Date(value).toLocaleString(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function accountTypeBadge(type: string): "primary" | "success" | "warning" | "default" | "danger" {
  switch (type) {
    case "ASSET":
      return "primary";
    case "LIABILITY":
      return "warning";
    case "EQUITY":
      return "default";
    case "REVENUE":
      return "success";
    case "EXPENSE":
      return "danger";
    default:
      return "default";
  }
}

export default function FinancialPage() {
  const [activeTab, setActiveTab] = useState<ActiveTab>("TRIAL_BALANCE");
  const isAr = getLang() === "ar";

  const {
    data: trialBalance,
    isLoading: isLoadingTB,
    error: errorTB,
    refetch: refetchTB,
  } = useTrialBalance();

  const {
    data: transactionsData,
    isLoading: isLoadingTx,
    error: errorTx,
    refetch: refetchTx,
  } = useFinancialTransactions(50, 0);

  const {
    data: accountsData,
    isLoading: isLoadingAcc,
    error: errorAcc,
    refetch: refetchAcc,
  } = useFinancialAccounts();

  function handleRefreshAll() {
    refetchTB();
    refetchTx();
    refetchAcc();
  }

  const isLoading = isLoadingTB || isLoadingTx || isLoadingAcc;
  const isBalanced = trialBalance?.is_balanced ?? true;

  return (
    <div className="space-y-6" data-testid="financial-page">
      <PageHeader
        title={isAr ? "الدفتر المالي وميزان المراجعة" : "Financial Ledger & Trial Balance"}
        description={
          isAr
            ? "نظام القيد المزدوج المحاسبي الصارم (Double-Entry Bookkeeping Ledger) وتحقق توازن القيود في كل عملية."
            : "Deterministic double-entry bookkeeping ledger, strict debit-credit balancing, and trial balance reports."
        }
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={handleRefreshAll}
            className="gap-2"
            data-testid="refresh-financial"
          >
            <RotateCcw aria-hidden="true" className="size-4" />
            <span>{isAr ? "تحديث" : "Refresh"}</span>
          </Button>
        }
      />

      {/* Trial Balance Health / Balance Status Card */}
      {trialBalance && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <Card className="border-border/70">
            <CardContent className="p-4 space-y-1">
              <span className="text-xs text-muted-foreground block">
                {isAr ? "إجمالي المدين (Total Debits)" : "Total Debits"}
              </span>
              <div className="flex items-baseline gap-2">
                <span className="font-mono text-xl font-bold tracking-tight text-foreground">
                  {trialBalance.total_debits}
                </span>
                <span className="text-xs text-muted-foreground font-mono">
                  {trialBalance.currency}
                </span>
              </div>
            </CardContent>
          </Card>

          <Card className="border-border/70">
            <CardContent className="p-4 space-y-1">
              <span className="text-xs text-muted-foreground block">
                {isAr ? "إجمالي الدائن (Total Credits)" : "Total Credits"}
              </span>
              <div className="flex items-baseline gap-2">
                <span className="font-mono text-xl font-bold tracking-tight text-foreground">
                  {trialBalance.total_credits}
                </span>
                <span className="text-xs text-muted-foreground font-mono">
                  {trialBalance.currency}
                </span>
              </div>
            </CardContent>
          </Card>

          <Card
            className={cn(
              "border",
              isBalanced
                ? "border-success/30 bg-success/[0.03]"
                : "border-danger/30 bg-danger/[0.03]"
            )}
          >
            <CardContent className="p-4 space-y-1">
              <span className="text-xs text-muted-foreground block">
                {isAr ? "حالة اتزان الدفتر (Double-Entry Invariant)" : "Ledger Invariant Status"}
              </span>
              <div className="flex items-center gap-2 pt-1">
                {isBalanced ? (
                  <>
                    <CheckCircle2 className="size-5 text-success" />
                    <span className="font-bold text-sm text-success">
                      {isAr ? "متزن وموثق (Balanced)" : "Strictly Balanced"}
                    </span>
                  </>
                ) : (
                  <>
                    <AlertCircle className="size-5 text-danger" />
                    <span className="font-bold text-sm text-danger">
                      {isAr ? "غير متزن (Out of Balance!)" : "Out of Balance!"}
                    </span>
                  </>
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Tabs */}
      <div className="flex flex-wrap items-center gap-2 border-b border-border pb-3">
        {(["TRIAL_BALANCE", "TRANSACTIONS", "ACCOUNTS"] as ActiveTab[]).map((tab) => {
          const labels: Record<ActiveTab, string> = {
            TRIAL_BALANCE: isAr ? "ميزان المراجعة (Trial Balance)" : "Trial Balance",
            TRANSACTIONS: isAr ? "قيود اليومية (Transactions)" : "Posted Transactions",
            ACCOUNTS: isAr ? "دليل الحسابات (Chart of Accounts)" : "Chart of Accounts",
          };
          const active = activeTab === tab;
          return (
            <button
              key={tab}
              type="button"
              onClick={() => setActiveTab(tab)}
              data-testid={`tab-${tab.toLowerCase()}`}
              className={cn(
                "rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors duration-150",
                active
                  ? "bg-primary text-white"
                  : "bg-muted text-muted-foreground hover:bg-muted/80 hover:text-foreground"
              )}
            >
              {labels[tab]}
            </button>
          );
        })}
      </div>

      {isLoading && <TableSkeleton rows={5} cols={5} />}

      {/* Tab 1: Trial Balance */}
      {!isLoading && activeTab === "TRIAL_BALANCE" && (
        errorTB && !(errorTB.message?.includes("404") || errorTB.message?.toLowerCase().includes("not found")) ? (
          <ErrorState
            message={errorTB.message || (isAr ? "فشل تحميل ميزان المراجعة" : "Failed to load trial balance")}
            onRetry={refetchTB}
          />
        ) : (
          <Card className="border-border/70 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-start text-xs">
                <thead className="border-b border-border bg-muted/50 font-bold text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3 text-start">{isAr ? "كود الحساب" : "Account Code"}</th>
                    <th className="px-4 py-3 text-start">{isAr ? "اسم الحساب" : "Account Name"}</th>
                    <th className="px-4 py-3 text-start">{isAr ? "النوع" : "Type"}</th>
                    <th className="px-4 py-3 text-end">{isAr ? "إجمالي المدين" : "Debits"}</th>
                    <th className="px-4 py-3 text-end">{isAr ? "إجمالي الدائن" : "Credits"}</th>
                    <th className="px-4 py-3 text-end">{isAr ? "صافي الرصيد" : "Net Balance"}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {trialBalance?.items && trialBalance.items.length > 0 ? (
                    trialBalance.items.map((acc) => (
                      <tr
                        key={acc.account_id}
                        className="hover:bg-muted/30 transition-colors"
                        data-testid={`tb-row-${acc.code}`}
                      >
                        <td className="px-4 py-3 font-mono font-bold text-primary">
                          {acc.code}
                        </td>
                        <td className="px-4 py-3 font-medium text-foreground">
                          {acc.name}
                        </td>
                        <td className="px-4 py-3">
                          <Badge variant={accountTypeBadge(acc.account_type)}>
                            {acc.account_type}
                          </Badge>
                        </td>
                        <td className="px-4 py-3 text-end font-mono text-foreground" dir="ltr">
                          {acc.total_debit}
                        </td>
                        <td className="px-4 py-3 text-end font-mono text-foreground" dir="ltr">
                          {acc.total_credit}
                        </td>
                        <td className="px-4 py-3 text-end font-mono font-bold text-foreground" dir="ltr">
                          {acc.net_balance}
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">
                        {isAr ? "لا توجد حسابات أو قيود بعد" : "No accounts or balances yet."}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>
        )
      )}

      {/* Tab 2: Transactions / Journal Entries */}
      {!isLoading && activeTab === "TRANSACTIONS" && (
        errorTx && !(errorTx.message?.includes("404") || errorTx.message?.toLowerCase().includes("not found")) ? (
          <ErrorState
            message={errorTx.message || (isAr ? "فشل تحميل قيود اليومية" : "Failed to load transactions")}
            onRetry={refetchTx}
          />
        ) : (
          <div className="grid gap-3">
            {transactionsData?.items && transactionsData.items.length > 0 ? (
              transactionsData.items.map((tx: FinancialTransactionItem) => (
                <Card
                  key={tx.transaction_id}
                  data-testid={`tx-card-${tx.transaction_id}`}
                  className="border-border/70 hover:border-primary/40 transition-colors"
                >
                  <CardContent className="p-4 space-y-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs font-bold text-muted-foreground">
                          #{tx.transaction_id.slice(0, 8)}
                        </span>
                        <Badge variant="outline" className="font-mono text-[11px]">
                          {tx.reference_type}
                        </Badge>
                        {tx.reference_id && (
                          <span className="text-xs text-muted-foreground font-mono">
                            ref: {tx.reference_id.slice(0, 8)}…
                          </span>
                        )}
                        <Badge variant="success" className="text-[11px]">
                          {tx.status}
                        </Badge>
                      </div>
                      <span className="text-xs text-muted-foreground">
                        {formatDateTime(tx.posted_at)}
                      </span>
                    </div>

                    {tx.description && (
                      <p className="text-xs text-foreground font-medium">{tx.description}</p>
                    )}

                    <div className="flex items-center justify-between pt-2 border-t border-border/40 text-xs">
                      <div className="flex items-center gap-4 font-mono">
                        <span>
                          <span className="text-muted-foreground font-sans">{isAr ? "مدين:" : "DR:"} </span>
                          <strong>{tx.total_debits}</strong> {tx.currency}
                        </span>
                        <span>
                          <span className="text-muted-foreground font-sans">{isAr ? "دائن:" : "CR:"} </span>
                          <strong>{tx.total_credits}</strong> {tx.currency}
                        </span>
                      </div>
                      <span className="flex items-center gap-1 text-[11px] text-success">
                        <Check className="size-3" />
                        <span>{isAr ? "قيد متزن" : "Balanced"}</span>
                      </span>
                    </div>
                  </CardContent>
                </Card>
              ))
            ) : (
              <EmptyState
                icon={<Receipt aria-hidden="true" />}
                title={isAr ? "لا توجد قيود يومية مسجلة" : "No transactions posted yet"}
                description={
                  isAr
                    ? "حركات المبيعات والمدفوعات والمصروفات تُسجل كقيود مزدوجة تظهر هنا فور ترحيلها."
                    : "Sales revenue, invoices, and payment settle operations will appear here as double-entry journal entries."
                }
              />
            )}
          </div>
        )
      )}

      {/* Tab 3: Chart of Accounts */}
      {!isLoading && activeTab === "ACCOUNTS" && (
        errorAcc && !(errorAcc.message?.includes("404") || errorAcc.message?.toLowerCase().includes("not found")) ? (
          <ErrorState
            message={errorAcc.message || (isAr ? "فشل تحميل دليل الحسابات" : "Failed to load chart of accounts")}
            onRetry={refetchAcc}
          />
        ) : (
          <Card className="border-border/70 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-start text-xs">
                <thead className="border-b border-border bg-muted/50 font-bold text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3 text-start">{isAr ? "رمز الحساب" : "Code"}</th>
                    <th className="px-4 py-3 text-start">{isAr ? "اسم الحساب" : "Account Name"}</th>
                    <th className="px-4 py-3 text-start">{isAr ? "تصنيف الحساب" : "Type"}</th>
                    <th className="px-4 py-3 text-start">{isAr ? "العملة" : "Currency"}</th>
                    <th className="px-4 py-3 text-end">{isAr ? "الحالة" : "Status"}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {accountsData?.items && accountsData.items.length > 0 ? (
                    accountsData.items.map((acc: FinancialAccount) => (
                      <tr
                        key={acc.account_id}
                        className="hover:bg-muted/30 transition-colors"
                        data-testid={`acc-row-${acc.code}`}
                      >
                        <td className="px-4 py-3 font-mono font-bold text-primary">
                          {acc.code}
                        </td>
                        <td className="px-4 py-3 font-semibold text-foreground">
                          {acc.name}
                        </td>
                        <td className="px-4 py-3">
                          <Badge variant={accountTypeBadge(acc.account_type)}>
                            {acc.account_type}
                          </Badge>
                        </td>
                        <td className="px-4 py-3 font-mono text-muted-foreground">
                          {acc.currency}
                        </td>
                        <td className="px-4 py-3 text-end">
                          <Badge variant={acc.is_active ? "success" : "default"}>
                            {acc.is_active
                              ? isAr
                                ? "نشط"
                                : "Active"
                              : isAr
                              ? "معطل"
                              : "Inactive"}
                          </Badge>
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">
                        {isAr ? "لا توجد حسابات مسجلة" : "No accounts found"}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>
        )
      )}
    </div>
  );
}
