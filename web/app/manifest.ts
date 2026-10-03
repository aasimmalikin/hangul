import type { MetadataRoute } from "next"

/** Makes Hangul installable ("Add to Home Screen"): its own icon, opens full-screen like an app. */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Hangul — your personal AI assistant",
    short_name: "Hangul",
    description: "Reminders, email, calendar, documents and more — just ask, or talk.",
    start_url: "/",
    scope: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: "#0F0F10",
    theme_color: "#0F0F10",
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/icons/maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
    shortcuts: [
      { name: "Talk to Hangul", short_name: "Talk", url: "/chat?voice=1", icons: [{ src: "/icons/icon-192.png", sizes: "192x192" }] },
      { name: "My stuff", url: "/lists", icons: [{ src: "/icons/icon-192.png", sizes: "192x192" }] },
    ],
  }
}
