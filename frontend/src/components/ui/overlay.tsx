"use client";

/**
 * Dialog (centred, for a decision or a short form) and Sheet (right-hand panel, for a record's
 * details) on Base UI, so focus is trapped, Escape closes, and focus returns to the opener.
 * Step 41 design kit; one overlay style for the whole app (shadow-overlay, navy backdrop).
 */
import type { ReactNode } from "react";
import { Dialog as Base } from "@base-ui/react/dialog";
import { X } from "lucide-react";
import { cn } from "cn";

const backdrop =
  "fixed inset-0 z-50 bg-navy/40 transition-opacity duration-150 data-ending-style:opacity-0 data-starting-style:opacity-0";

interface OverlayProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  /** Buttons at the bottom; the panel keeps them in view while the body scrolls. */
  footer?: ReactNode;
}

function CloseButton() {
  return (
    <Base.Close aria-label="Close" className="rounded-md p-1.5 text-muted-foreground hover:bg-ice hover:text-heading">
      <X className="size-4" aria-hidden />
    </Base.Close>
  );
}

export function Dialog({ open, onOpenChange, title, description, children, footer, size = "md" }: OverlayProps & {
  size?: "sm" | "md" | "lg";
}) {
  const width = { sm: "max-w-sm", md: "max-w-lg", lg: "max-w-2xl" }[size];
  return (
    <Base.Root open={open} onOpenChange={onOpenChange}>
      <Base.Portal>
        <Base.Backdrop className={backdrop} />
        <Base.Popup className={cn(
          "fixed left-1/2 top-[8vh] z-50 flex max-h-[84vh] w-[calc(100vw-2rem)] -translate-x-1/2 flex-col rounded-xl border border-border bg-white shadow-overlay outline-none",
          "transition-[opacity,scale] duration-150 data-ending-style:scale-[0.98] data-ending-style:opacity-0 data-starting-style:scale-[0.98] data-starting-style:opacity-0",
          width)}>
          <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
            <div className="min-w-0">
              <Base.Title className="text-base font-semibold text-heading">{title}</Base.Title>
              {description ? <Base.Description className="mt-1 text-sm text-muted-foreground">{description}</Base.Description> : null}
            </div>
            <CloseButton />
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
          {footer ? <div className="flex flex-wrap justify-end gap-2 border-t border-border bg-ice-light/60 px-5 py-3">{footer}</div> : null}
        </Base.Popup>
      </Base.Portal>
    </Base.Root>
  );
}

export function Sheet({ open, onOpenChange, title, description, children, footer, header }: OverlayProps & {
  /** Extra content under the title, e.g. tabs. */
  header?: ReactNode;
}) {
  return (
    <Base.Root open={open} onOpenChange={onOpenChange}>
      <Base.Portal>
        <Base.Backdrop className={backdrop} />
        <Base.Popup className={cn(
          "fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col border-l border-border bg-white shadow-overlay outline-none",
          "transition-transform duration-200 ease-out data-ending-style:translate-x-full data-starting-style:translate-x-full")}>
          <div className="border-b border-border px-5 pt-4">
            <div className="flex items-start justify-between gap-4 pb-4">
              <div className="min-w-0">
                <Base.Title className="text-base font-semibold text-heading">{title}</Base.Title>
                {description ? <Base.Description className="mt-0.5 text-sm text-muted-foreground">{description}</Base.Description> : null}
              </div>
              <CloseButton />
            </div>
            {header}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
          {footer ? <div className="flex flex-wrap justify-end gap-2 border-t border-border px-5 py-3">{footer}</div> : null}
        </Base.Popup>
      </Base.Portal>
    </Base.Root>
  );
}
