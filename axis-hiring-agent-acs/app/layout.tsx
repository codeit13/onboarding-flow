import type { Metadata } from "next";
import Script from "next/script";
import "./globals.css";
import { PersonaSwitcher } from "@/components/PersonaSwitcher";

export const metadata: Metadata = {
  title: "Axis Hiring · Axis Bank",
  description: "The Axis Bank hiring experience — from application to offer.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const apiBase =
    process.env.ACS_API_BASE ||
    process.env.NEXT_PUBLIC_API_BASE ||
    "http://localhost:8100";

  return (
    <html lang="en">
      <body>
        <Script id="axis-api-base" strategy="beforeInteractive">
          {`window.__API_BASE__=${JSON.stringify(apiBase)};`}
        </Script>
        <PersonaSwitcher />
        {children}
      </body>
    </html>
  );
}
