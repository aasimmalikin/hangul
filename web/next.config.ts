import type { NextConfig } from "next";

// Browser-side defence in depth. Scripts and styles are ours (Next inlines
// some, hence 'unsafe-inline'); network calls only go to our own origin;
// nothing may frame the app; Google avatars are the one external image host.
const csp = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https://*.googleusercontent.com",
  "font-src 'self' data:",
  // spoken answers are played from blob: URLs (lib/voice.ts Speaker)
  "media-src 'self' blob:",
  "connect-src 'self'",
  "frame-ancestors 'none'",
  "form-action 'self' https://accounts.google.com",
  "base-uri 'self'",
  "object-src 'none'",
].join("; ");

const nextConfig: NextConfig = {
  // The Docker image (web/Dockerfile) builds with NEXT_OUTPUT=standalone: a
  // self-contained server.js with only the files it needs. Local `next start`
  // and the e2e tests keep the normal output.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  // trace from web/ itself (the repo root has its own lockfile), so server.js lands at .next/standalone/
  outputFileTracingRoot: process.cwd(),
  async headers() {
    return [
      {
        // the service worker: always revalidated, and only allowed to load our own scripts
        source: "/sw.js",
        headers: [
          { key: "Content-Type", value: "application/javascript; charset=utf-8" },
          { key: "Cache-Control", value: "no-cache, no-store, must-revalidate" },
          { key: "Content-Security-Policy", value: "default-src 'self'; script-src 'self'" },
        ],
      },
      {
        source: "/(.*)",
        headers: [
          { key: "Content-Security-Policy", value: csp },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          // microphone: our own pages only (voice); never embedded third parties
          { key: "Permissions-Policy", value: "camera=(), microphone=(self), geolocation=()" },
          // Browsers ignore HSTS over plain http, so this is harmless in dev
          // and pins the site to TLS wherever it is served over https.
          { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
        ],
      },
      {
        // The admin console and approve-by-link pages (the link is a credential):
        // never cached by a browser or a shared proxy, never indexed, never framed
        // (already), and Referer never leaves them.
        source: "/(admin|api/admin|approve|api/approval-links)(.*)",
        headers: [
          { key: "Cache-Control", value: "private, no-store, max-age=0" },
          { key: "X-Robots-Tag", value: "noindex, nofollow" },
          { key: "Referrer-Policy", value: "no-referrer" },
        ],
      },
    ];
  },
};

export default nextConfig;
