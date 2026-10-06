import type { Metadata, Viewport } from "next";
import { ServiceWorker } from "@/components/ServiceWorker";
import { Geist, Geist_Mono, Fraunces } from "next/font/google";
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

const fraunces = Fraunces({
  variable: "--font-fraunces",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: "Hangul",
  description: "Your personal AI assistant: reminders, email, calendar, documents and more — just ask, or talk.",
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
      className={`${geistSans.variable} ${geistMono.variable} ${fraunces.variable} h-full antialiased`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="min-h-full flex flex-col"><Providers session={session}>{children}<ServiceWorker /></Providers></body>
    </html>
  );
}
