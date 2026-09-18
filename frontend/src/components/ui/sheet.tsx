"use client";

import * as React from "react";
import * as SheetPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

/** Sheet = dialog جانبي. RTL-native: `side="end"` يفتح من الجهة المقابلة للبداية. */
const Sheet = SheetPrimitive.Root;
const SheetTrigger = SheetPrimitive.Trigger;
const SheetClose = SheetPrimitive.Close;
const SheetPortal = SheetPrimitive.Portal;

function SheetOverlay({ className, ...props }: React.ComponentProps<typeof SheetPrimitive.Overlay>) {
  return (
    <SheetPrimitive.Overlay
      className={cn(
        "fixed inset-0 z-50 bg-foreground/30 backdrop-blur-[2px]",
        "data-[state=open]:animate-[overlay-in_200ms_var(--ease-smooth)]",
        className,
      )}
      {...props}
    />
  );
}

const sideClasses = {
  start: "inset-y-0 start-0",
  end: "inset-y-0 end-0",
  top: "inset-x-0 top-0",
  bottom: "inset-x-0 bottom-0",
} as const;

function SheetContent({
  className,
  children,
  side = "end",
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Content> & { side?: keyof typeof sideClasses }) {
  return (
    <SheetPortal>
      <SheetOverlay />
      <SheetPrimitive.Content
        dir="rtl"
        className={cn(
          "fixed z-50 flex flex-col gap-4 border-border bg-card shadow-lg",
          sideClasses[side],
          side === "start" && "border-e",
          side === "end" && "border-s",
          "data-[state=open]:animate-[slide-in-end_300ms_var(--ease-smooth)] data-[state=closed]:animate-[slide-out-end_200ms_var(--ease-smooth)]",
          className,
        )}
        {...props}
      >
        {children}
        <SheetPrimitive.Close className="absolute end-4 top-4 rounded-md p-1 text-muted-foreground opacity-70 transition-all duration-150 ease-smooth hover:bg-muted hover:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30">
          <X className="size-4" aria-hidden="true" />
          <span className="sr-only">إغلاق</span>
        </SheetPrimitive.Close>
      </SheetPrimitive.Content>
    </SheetPortal>
  );
}

function SheetHeader({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("flex flex-col gap-1.5 p-5 pb-0 text-start", className)} {...props} />;
}

function SheetTitle({ className, ...props }: React.ComponentProps<typeof SheetPrimitive.Title>) {
  return <SheetPrimitive.Title className={cn("text-lg font-bold", className)} {...props} />;
}

function SheetDescription({
  className,
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Description>) {
  return (
    <SheetPrimitive.Description className={cn("text-[13px] text-muted-foreground", className)} {...props} />
  );
}

export { Sheet, SheetTrigger, SheetClose, SheetContent, SheetHeader, SheetTitle, SheetDescription };
