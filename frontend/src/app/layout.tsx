/**
 * Root layout: fonts, brand theme and page metadata (BUILD_PLAN §4, docs/BRAND.md).
 * Hanken Grotesk is the working typeface; Newsreader is used only for page titles and area names.
 */
import type { Metadata } from "next";
import { Hanken_Grotesk, Newsreader } from "next/font/google";
import "./globals.css";

const sans = Hanken_Grotesk({
  variable: "--font-hanken",
  subsets: ["latin"],
});

const display = Newsreader({
  variable: "--font-newsreader",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Orrfin",
  description: "Procurement and invoice control around your ERP: requests, approvals, matching and a full audit trail.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${sans.variable} ${display.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
