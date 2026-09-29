/**
 * Plain form controls in the brand theme (docs/BRAND.md): white fields, blue focus ring.
 * Native elements keep keyboard and screen-reader behaviour for free.
 */
import type { ComponentProps, ReactNode } from "react";
import { cn } from "cn";

const control =
  "w-full rounded-lg border border-input bg-white px-3 py-2 text-sm text-foreground shadow-xs outline-none " +
  "placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/30 " +
  "disabled:cursor-not-allowed disabled:bg-muted disabled:opacity-70 aria-invalid:border-destructive";

export function Input({ className, ...props }: ComponentProps<"input">) {
  return <input className={cn(control, "h-9", className)} {...props} />;
}

export function Textarea({ className, ...props }: ComponentProps<"textarea">) {
  return <textarea className={cn(control, "min-h-20", className)} {...props} />;
}

export function Select({ className, ...props }: ComponentProps<"select">) {
  return <select className={cn(control, "h-9 pr-8", className)} {...props} />;
}

export function Field({
  label,
  htmlFor,
  hint,
  children,
  className,
}: {
  label: string;
  htmlFor: string;
  hint?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={htmlFor} className="text-sm font-medium text-heading">
        {label}
      </label>
      {children}
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}
