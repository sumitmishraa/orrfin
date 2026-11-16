"use client";

/**
 * Short confirmations after an action ("Invitation sent", "Member deactivated"). Step 41 design kit.
 * They are announced to screen readers (aria-live) and disappear after a few seconds; anything a
 * person must act on is shown on the page instead, never only in a toast.
 */
import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { CircleAlert, CircleCheck, X } from "lucide-react";

type ToastTone = "success" | "error";
interface ToastItem { id: number; title: string; body?: string; tone: ToastTone }

const ToastContext = createContext<(title: string, options?: { body?: string; tone?: ToastTone }) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: number) => setItems((all) => all.filter((t) => t.id !== id)), []);
  const show = useCallback((title: string, options?: { body?: string; tone?: ToastTone }) => {
    const id = Date.now() + Math.random();
    setItems((all) => [...all.slice(-2), { id, title, body: options?.body, tone: options?.tone ?? "success" }]);
    window.setTimeout(() => dismiss(id), 5000);
  }, [dismiss]);

  return (
    <ToastContext.Provider value={show}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2">
        {items.map((t) => {
          const Icon = t.tone === "success" ? CircleCheck : CircleAlert;
          return (
            <div key={t.id} role="status"
                 className="pointer-events-auto flex items-start gap-3 rounded-lg border border-border bg-white px-4 py-3 shadow-overlay animate-in fade-in slide-in-from-bottom-2">
              <Icon className={`mt-0.5 size-4 shrink-0 ${t.tone === "success" ? "text-success" : "text-error"}`} aria-hidden />
              <div className="min-w-0 flex-1 text-sm">
                <p className="font-medium text-heading">{t.title}</p>
                {t.body ? <p className="mt-0.5 text-muted-foreground">{t.body}</p> : null}
              </div>
              <button type="button" aria-label="Dismiss" onClick={() => dismiss(t.id)}
                      className="rounded p-0.5 text-muted-foreground hover:text-heading">
                <X className="size-3.5" aria-hidden />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
