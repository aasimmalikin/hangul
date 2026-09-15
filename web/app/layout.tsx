import type { Metadata } from "next";
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
  description: "An agentic assistant.",
};

// Applies the saved theme before first paint so the page never flashes the
// wrong palette. ThemeProvider takes over once hydrated; `suppressHydrationWarning`
// covers the attribute this script sets on <html>.
const themeScript = `(function(){try{var t=localStorage.getItem("theme");document.documentElement.dataset.theme=(t==="light"||t==="dark")?t:"dark"}catch(e){document.documentElement.dataset.theme="dark"}})()`;

export default async function RootLayout({ children }: LayoutProps<"/">) {
  // Read the session cookie once on the server; every page starts knowing
  // whether there is a user (see components/Providers.tsx).
  const session = await auth();
  return (
    <html
      lang="en"
      data-theme="dark"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} ${fraunces.variable} h-full antialiased`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="min-h-full flex flex-col"><Providers session={session}>{children}</Providers></body>
    </html>
  );
}
