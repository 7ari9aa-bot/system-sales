"use client";

import * as React from "react";
import * as ToastPrimitive from "@radix-ui/react-toast";
import { CheckCircle2, Info, TriangleAlert } from "lucide-react";
import { cn } from "@/lib/utils";

/** Toast system — imperative `toast()` + Radix viewport. RTL-native. */

type ToastVariant = "default" | "success" | "danger" | "warning";

export type ToastOptions = {
  title: string;
  description?: string;
  variant?: ToastVariant;
  duration?: number;
};

type ToastItem = ToastOptions & { id: number };

type Listener = (items: ToastItem[]) => void;

let items: ToastItem[] = [];
let nextId = 1;
const listeners = new Set<Listener>();

function emit() {
  listeners.forEach((l) => l([...items]));
}

/** استدعاء مباشر من أي مكان: toast({ title, variant: "success" }) */
export function toast(options: ToastOptions) {
  const item: ToastItem = { id: nextId++, variant: "default", duration: 4000, ...options };
  items = [...items, item];
  emit();
}

function dismiss(id: number) {
  items = items.filter((i) => i.id !== id);
  emit();
}

const variantIcon: Record<ToastVariant, React.ReactNode> = {
  default: <Info className="size-4 text-primary" aria-hidden="true" />,
  success: <CheckCircle2 className="size-4 text-success" aria-hidden="true" />,
  danger: <TriangleAlert className="size-4 text-danger" aria-hidden="true" />,
  warning: <TriangleAlert className="size-4 text-warning" aria-hidden="true" />,
};

function Toaster() {
  const [current, setCurrent] = React.useState<ToastItem[]>([]);

  React.useEffect(() => {
    const listener: Listener = (next) => setCurrent(next);
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);

  return (
    <ToastPrimitive.Provider swipeDirection="left" duration={4000}>
      {current.map((item) => (
        <ToastPrimitive.Root
          key={item.id}
          duration={item.duration}
          onOpenChange={(open) => {
            if (!open) dismiss(item.id);
          }}
          className={cn(
            "pointer-events-auto flex items-start gap-3 rounded-xl border border-border bg-card p-4 shadow-lg",
            "data-[state=open]:animate-[dialog-in_200ms_var(--ease-smooth)]",
            "data-[swipe=end]:animate-[dialog-out_150ms_var(--ease-smooth)]",
          )}
        >
          <span className="mt-0.5">{variantIcon[item.variant ?? "default"]}</span>
          <div className="flex-1">
            <ToastPrimitive.Title className="text-sm font-bold">{item.title}</ToastPrimitive.Title>
            {item.description && (
              <ToastPrimitive.Description className="mt-0.5 text-[13px] text-muted-foreground">
                {item.description}
              </ToastPrimitive.Description>
            )}
          </div>
          <ToastPrimitive.Close
            aria-label="إغلاق"
            className="rounded-md p-1 text-muted-foreground transition-colors duration-150 hover:bg-muted"
          >
            ×
          </ToastPrimitive.Close>
        </ToastPrimitive.Root>
      ))}
      <ToastPrimitive.Viewport className="fixed bottom-4 end-4 z-[100] flex w-full max-w-sm flex-col gap-2 outline-none" />
    </ToastPrimitive.Provider>
  );
}

export { Toaster };
