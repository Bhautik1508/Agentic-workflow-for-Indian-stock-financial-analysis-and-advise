import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: "StockSage AI | Multi-Agent Indian Equity Research",
  description:
    "6 AI analysts decode Indian equities in 30 seconds. Institution-grade fundamental, technical, sentiment, risk, and macro analysis for NSE/BSE stocks.",
};

export const viewport: Viewport = {
  themeColor: "#040812",
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
        <meta name="theme-color" content="#040812" />
        <meta name="color-scheme" content="dark" />
      </head>
      <body
        className={`${inter.variable} ${jetbrainsMono.variable} font-sans antialiased min-h-screen bg-background text-foreground selection:bg-primary/30`}
      >
        <main className="flex min-h-screen flex-col items-center relative overflow-hidden">
          {children}
        </main>
      </body>
    </html>
  );
}
