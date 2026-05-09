import type { Metadata, Viewport } from "next";
import { Inter, DM_Mono } from "next/font/google";
import "./globals.css";

const inter = Inter({
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
    "Six AI analysts, one verdict. Institution-grade fundamental, technical, sentiment, risk, and macro analysis for NSE/BSE stocks.",
};

export const viewport: Viewport = {
  themeColor: "#FAFAF7",
  colorScheme: "light",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <meta name="theme-color" content="#FAFAF7" />
        <meta name="color-scheme" content="light" />
      </head>
      <body
        className={`${inter.variable} ${dmMono.variable} font-sans antialiased min-h-screen`}
      >
        <main className="flex min-h-screen flex-col items-center relative">
          {children}
        </main>
      </body>
    </html>
  );
}
