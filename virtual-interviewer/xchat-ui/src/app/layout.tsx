import { Providers } from "@/providers";
import type { Metadata } from "next";
import localFont from "next/font/local";
import type React from "react";
import "./globals.css";
import { Toaster } from "react-hot-toast";

// Load Poppins font from local files
const poppins = localFont({
  src: [
    {
      path: "../../public/font/Poppins-Thin.ttf",
      weight: "100",
      style: "normal",
    },
    {
      path: "../../public/font/Poppins-ThinItalic.ttf",
      weight: "100",
      style: "italic",
    },
    {
      path: "../../public/font/Poppins-ExtraLight.ttf",
      weight: "200",
      style: "normal",
    },
    {
      path: "../../public/font/Poppins-ExtraLightItalic.ttf",
      weight: "200",
      style: "italic",
    },
    {
      path: "../../public/font/Poppins-Light.ttf",
      weight: "300",
      style: "normal",
    },
    {
      path: "../../public/font/Poppins-LightItalic.ttf",
      weight: "300",
      style: "italic",
    },
    {
      path: "../../public/font/Poppins-Regular.ttf",
      weight: "400",
      style: "normal",
    },
    {
      path: "../../public/font/Poppins-Italic.ttf",
      weight: "400",
      style: "italic",
    },
    {
      path: "../../public/font/Poppins-Medium.ttf",
      weight: "500",
      style: "normal",
    },
    {
      path: "../../public/font/Poppins-MediumItalic.ttf",
      weight: "500",
      style: "italic",
    },
    {
      path: "../../public/font/Poppins-SemiBold.ttf",
      weight: "600",
      style: "normal",
    },
    {
      path: "../../public/font/Poppins-SemiBoldItalic.ttf",
      weight: "600",
      style: "italic",
    },
    {
      path: "../../public/font/Poppins-Bold.ttf",
      weight: "700",
      style: "normal",
    },
    {
      path: "../../public/font/Poppins-BoldItalic.ttf",
      weight: "700",
      style: "italic",
    },
    {
      path: "../../public/font/Poppins-ExtraBold.ttf",
      weight: "800",
      style: "normal",
    },
    {
      path: "../../public/font/Poppins-ExtraBoldItalic.ttf",
      weight: "800",
      style: "italic",
    },
    {
      path: "../../public/font/Poppins-Black.ttf",
      weight: "900",
      style: "normal",
    },
    {
      path: "../../public/font/Poppins-BlackItalic.ttf",
      weight: "900",
      style: "italic",
    },
  ],
  variable: "--font-poppins", // Optional: for CSS variable usage
});

export const metadata: Metadata = {
  title: "Virtual Interviewer",
  description: "Virtual Interviewer application",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${poppins.className} antialiased`}>
        <Providers>
          <Toaster />
          <main className="flex-1 dark:bg-xGrey400">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
