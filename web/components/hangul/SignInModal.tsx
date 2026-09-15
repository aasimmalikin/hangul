"use client";

import { useState } from "react";
import { signIn } from "next-auth/react";
import { HangulSigil } from "@/components/HangulSigil";

/**
 * The one sign-in dialog for the whole app. Any page that needs the user to
 * be authenticated (sending a message, uploading a document, …) renders this
 * and flips `open`; the copy under the title says why.
 *
 * `callbackUrl` is where Auth.js returns the user after Google / the email
 * link — pass the page they were on so they land back in context.
 */
export type AuthMode = "signin" | "signup";

const COPY: Record<
  AuthMode,
  { title: string; reason: string; google: string; email: string }
> = {
  signin: {
    title: "Sign in to continue",
    reason: "Your conversation is saved once you are in.",
    google: "Continue with Google",
    email: "Continue with email",
  },
  signup: {
    title: "Create your account",
    reason: "Free to start. Your documents and conversations stay yours.",
    google: "Sign up with Google",
    email: "Sign up with email",
  },
};

export function SignInModal({
  open,
  onClose,
  mode = "signin",
  title,
  reason,
  callbackUrl,
}: {
  open: boolean;
  onClose: () => void;
  /**
   * "signup" changes the copy and asks Google to show its account chooser,
   * so a new user picks which account to register. Both modes run the same
   * Auth.js flow — the Postgres adapter creates the user on first sign-in.
   */
  mode?: AuthMode;
  title?: string;
  reason?: string;
  callbackUrl?: string;
}) {
  const copy = COPY[mode];
  const heading = title ?? copy.title;
  const sub = reason ?? copy.reason;
  const [email, setEmail] = useState("");
  const [sending, setSending] = useState(false);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [emailError, setEmailError] = useState<string | null>(null);
  if (!open) return null;

  const redirectTo =
    callbackUrl ?? (typeof window !== "undefined" ? window.location.href : "/");

  // Email sign-in is handled in place (`redirect: false`) so a failure to
  // send the link shows here instead of bouncing the user to Auth.js's bare
  // /api/auth/error page. On success Auth.js hands back its verify-request
  // URL; we render our own "check your inbox" state instead of visiting it.
  const sendEmail = async () => {
    const addr = email.trim().toLowerCase();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(addr)) {
      setEmailError("Enter a valid email address.");
      return;
    }
    setSending(true);
    setEmailError(null);
    try {
      const res = await signIn("resend", {
        email: addr,
        redirectTo,
        redirect: false,
      });
      if (!res || res.error) {
        setEmailError(
          res?.error === "Configuration"
            ? "We couldn't send a sign-in link to that address. Email sign-in isn't fully set up on this deployment yet — please continue with Google."
            : "We couldn't send the sign-in link. Please try again.",
        );
        return;
      }
      setSentTo(addr);
    } catch {
      setEmailError("We couldn't send the sign-in link. Please try again.");
    } finally {
      setSending(false);
    }
  };

  const close = () => {
    setSentTo(null);
    setEmailError(null);
    onClose();
  };

  return (
    <div className="h-scrim" onClick={close} role="presentation">
      <div
        className="h-dialog"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="signin-title"
      >
        <HangulSigil size={40} />
        {sentTo ? (
          <>
            <p
              id="signin-title"
              className="h-display"
              style={{ fontSize: 19, margin: "14px 0 4px" }}
            >
              Check your inbox
            </p>
            <p className="h-muted" style={{ fontSize: 13, margin: "0 0 20px" }}>
              We sent a sign-in link to{" "}
              <b style={{ color: "var(--fg)" }}>{sentTo}</b>. Open it on this
              device to continue.
            </p>
            <button
              className="h-btn-outline"
              style={{ width: "100%", padding: 10, fontSize: 14 }}
              onClick={() => setSentTo(null)}
            >
              Use a different email
            </button>
          </>
        ) : (
          <>
            <p
              id="signin-title"
              className="h-display"
              style={{ fontSize: 19, margin: "14px 0 4px" }}
            >
              {heading}
            </p>
            <p className="h-muted" style={{ fontSize: 13, margin: "0 0 20px" }}>
              {sub}
            </p>
            <button
              className="h-btn-solid"
              style={{
                width: "100%",
                padding: 10,
                fontSize: 14,
                marginBottom: 12,
              }}
              onClick={() =>
                signIn(
                  "google",
                  { redirectTo },
                  // A new user should get to choose the account, not be
                  // silently signed up with whichever one Google has cached.
                  mode === "signup" ? { prompt: "select_account" } : undefined,
                )
              }
            >
              <i className="ti ti-brand-google" />
              {copy.google}
            </button>
            <input
              className="h-input"
              style={{
                marginBottom: 8,
                ...(emailError ? { borderColor: "var(--err)" } : {}),
              }}
              type="email"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                if (emailError) setEmailError(null);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") sendEmail();
              }}
              placeholder="you@email.com"
              aria-invalid={Boolean(emailError)}
              aria-describedby={emailError ? "signin-email-error" : undefined}
            />
            {emailError && (
              <p
                id="signin-email-error"
                role="alert"
                style={{
                  fontSize: 12,
                  color: "var(--err)",
                  margin: "0 0 10px",
                  textAlign: "left",
                }}
              >
                {emailError}
              </p>
            )}
            <button
              className="h-btn-outline"
              style={{ width: "100%", padding: 10, fontSize: 14 }}
              onClick={sendEmail}
              disabled={sending}
            >
              {sending ? "Sending link…" : copy.email}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
