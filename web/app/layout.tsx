import type { Metadata, Viewport } from "next";
import { ServiceWorker } from "@/components/ServiceWorker";
import { Geist, Geist_Mono, Fraunces } from "next/font/google";
import localFont from "next/font/local";
import "./globals.css";
import { Providers } from "@/components/Providers";
import { auth } from "@/auth";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// Body text (design direction A): Mukta, self-hosted from @fontsource (OFL), so no
// Google request at build or run time.
const mukta = localFont({
  variable: "--font-mukta",
  display: "swap",
  src: [
    { path: "../node_modules/@fontsource/mukta/files/mukta-latin-400-normal.woff2", weight: "400", style: "normal" },
    { path: "../node_modules/@fontsource/mukta/files/mukta-latin-600-normal.woff2", weight: "600", style: "normal" },
    { path: "../node_modules/@fontsource/mukta/files/mukta-latin-700-normal.woff2", weight: "700", style: "normal" },
    { path: "../node_modules/@fontsource/mukta/files/mukta-latin-800-normal.woff2", weight: "800", style: "normal" },
  ],
});

const fraunces = Fraunces({
  variable: "--font-fraunces",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: "Hangul",
  description: "Your shop's own assistant: sales, tomorrow's forecast, slow-day offers and customers. It always asks before it acts.",
  // installed on a phone home screen: opens full-screen with its own icon
  appleWebApp: { capable: true, title: "Hangul", statusBarStyle: "default" },
  icons: { apple: "/icons/apple-touch-icon.png" },
};

export const viewport: Viewport = {
  themeColor: [{ media: "(prefers-color-scheme: light)", color: "#FFFFFF" }, { media: "(prefers-color-scheme: dark)", color: "#121413" }],
  viewportFit: "cover",          // lets the bottom bar sit above the phone's home indicator (safe-area insets)
};

// Applies the saved theme before first paint so the page never flashes the
// wrong palette. ThemeProvider takes over once hydrated; `suppressHydrationWarning`
// covers the attribute this script sets on <html>.
const themeScript = `(function(){try{var t=localStorage.getItem("theme");document.documentElement.dataset.theme=(t==="light"||t==="dark")?t:"light"}catch(e){document.documentElement.dataset.theme="light"}})()`;

export default async function RootLayout({ children }: LayoutProps<"/">) {
  // Read the session cookie once on the server; every page starts knowing
  // whether there is a user (see components/Providers.tsx).
  const session = await auth();
  return (
    <html
      lang="en"
      data-theme="light"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} ${mukta.variable} ${fraunces.variable} h-full antialiased`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="min-h-full flex flex-col"><Providers session={session}>{children}<ServiceWorker /></Providers></body>
    </html>
  );
}
