import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "StockSage AI | Multi-Agent Analysis",
  description: "An AI-powered multi-agent system for analyzing Indian stocks on NSE/BSE. Get deep insights on financials, technicals, sentiment, risk, macro, and governance.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body
        className={`${inter.variable} font-sans antialiased min-h-screen bg-background text-foreground selection:bg-primary/30 selection:text-primary-foreground`}
      >
        <main className="flex min-h-screen flex-col items-center relative overflow-hidden">
          {children}
        </main>
      </body>
    </html>
  );
}
