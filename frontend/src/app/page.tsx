/**
 * Home: the Inbox is the landing page for every role (proxy.ts sends signed-out visitors to /login).
 */
import { redirect } from "next/navigation";

export default function Home() {
  redirect("/inbox");
}
