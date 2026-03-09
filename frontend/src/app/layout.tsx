import type { Metadata, Viewport } from "next";
import { DM_Sans, DM_Mono } from "next/font/google";
import "./globals.css";

const dmSans = DM_Sans({
  variable: "--font-dm-sans",
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
});

const dmMono = DM_Mono({
  variable: "--font-dm-mono",
  subsets: ["latin"],
  weight: ["300", "400", "500"],
});

export const metadata: Metadata = {
  title: "StockSage AI | Multi-Agent Indian Equity Research",
  description:
    "6 AI analysts decode Indian equities in 30 seconds. Institution-grade fundamental, technical, sentiment, risk, and macro analysis for NSE/BSE stocks.",
};

export const viewport: Viewport = {
  themeColor: "#07090f",
  colorScheme: "dark",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <head>
        <meta name="theme-color" content="#07090f" />
        <meta name="color-scheme" content="dark" />
      </head>
      <body
        className={`${dmSans.variable} ${dmMono.variable} font-sans antialiased min-h-screen bg-background text-foreground selection:bg-accent/20`}
      >
        <main className="flex min-h-screen flex-col items-center relative overflow-hidden">
          {children}
        </main>
      </body>
    </html>
  );
}
