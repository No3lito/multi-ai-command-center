"use client";

import { useId, useState, type FormEvent } from "react";
import { api, isApiError } from "@/lib/api";
import type { Principal } from "@/lib/types";
import { Logo } from "./Logo";

export function LoginScreen({ onSignedIn }: { onSignedIn: (p: Principal) => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inputId = useId();
  const errorId = useId();

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!password || busy) return;
    setBusy(true);
    setError(null);
    try {
      const { principal } = await api.login(password);
      setPassword("");
      onSignedIn(principal);
    } catch (err) {
      if (isApiError(err) && err.status === 401) setError("Incorrect password.");
      else if (isApiError(err) && err.status === 429)
        setError("Too many failed attempts. Wait a few minutes before trying again.");
      else if (isApiError(err)) setError(err.message);
      else setError("Sign in failed. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-full items-center justify-center p-6">
      <form
        onSubmit={submit}
        className="w-full max-w-sm rounded-lg border border-line bg-panel p-6 shadow-sm"
        aria-describedby={error ? errorId : undefined}
        noValidate
      >
        <div className="flex items-center gap-2">
          <Logo />
          <h1 className="text-base font-semibold">Multi-AI Command Center</h1>
        </div>
        <p className="mt-1 text-muted">Sign in as the owner to continue.</p>

        <label htmlFor={inputId} className="mt-5 block text-xs font-medium uppercase tracking-wide text-muted">
          Password
        </label>
        <input
          id={inputId}
          data-testid="login-password"
          type="password"
          autoComplete="current-password"
          autoFocus
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errorId : undefined}
          className="mt-1 w-full rounded-md border border-line bg-bg px-3 py-2 text-fg placeholder:text-muted"
        />

        {error && (
          <p id={errorId} role="alert" className="mt-3 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
            {error}
          </p>
        )}

        <button
          type="submit"
          data-testid="login-submit"
          disabled={!password || busy}
          className="mt-4 w-full rounded-md bg-accent px-3 py-2 font-medium text-accent-fg hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? "Signing in..." : "Sign in"}
        </button>
      </form>
    </main>
  );
}
