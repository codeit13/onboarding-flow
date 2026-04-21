import type { Metadata } from "next";
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
  return (
    <html lang="en">
      <body>
        <PersonaSwitcher />
        {children}
      </body>
    </html>
  );
}
