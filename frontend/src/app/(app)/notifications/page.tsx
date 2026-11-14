"use client";

/**
 * Notifications (BUILD_PLAN v3.0 §5): what happened to your own work. The server only ever
 * returns the signed-in person's notifications, and a link always stays inside Orrfin.
 */
import Link from "next/link";

import { EmptyState, ErrorNotice, Loading, PageHeader } from "@/components/page";
import { Button } from "@/components/ui/button";
import { post } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useApi } from "@/lib/use-api";

interface Inbox {
  unread: number;
  items: { id: string; kind: string; title: string; body: string; link: string | null; read: boolean; at: string }[];
}

export default function NotificationsPage() {
  const inbox = useApi<Inbox>("/notifications");

  if (inbox.loading) return <Loading />;
  if (inbox.error) return <ErrorNotice message={inbox.error} />;
  const items = inbox.data?.items ?? [];

  async function markAllRead() {
    await post("/notifications/read-all");
    await inbox.reload();
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Notifications"
        description={inbox.data?.unread ? `${inbox.data.unread} unread` : "You are up to date."}
        actions={inbox.data?.unread ? <Button variant="outline" onClick={markAllRead}>Mark all as read</Button> : undefined}
      />
      {items.length === 0 ? <EmptyState>Nothing yet. You will be told here when your requests are approved, rejected or returned.</EmptyState> : (
        <ul className="space-y-2">
          {items.map((n) => (
            <li key={n.id} className={`rounded-xl border border-border bg-white p-4 shadow-raised ${n.read ? "" : "border-l-4 border-l-primary"}`}>
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="font-medium text-heading">
                  {n.link ? <Link href={n.link} className="hover:underline">{n.title}</Link> : n.title}
                  {n.read ? null : <span className="sr-only"> (unread)</span>}
                </p>
                <time className="text-xs text-muted-foreground">{formatDateTime(n.at)}</time>
              </div>
              {n.body ? <p className="mt-1 text-sm text-muted-foreground">{n.body}</p> : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
