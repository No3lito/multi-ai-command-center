"use client";

import { useCallback, useEffect, useState } from "react";
import { api, isApiError, setUnauthorizedHandler } from "@/lib/api";
import type { Principal } from "@/lib/types";
import { LoginScreen } from "./LoginScreen";
import { Shell } from "./Shell";
import { FullScreenNotice } from "./FullScreenNotice";

type AuthState =
  | { kind: "checking" }
  | { kind: "anonymous" }
  | { kind: "signed_in"; principal: Principal }
  | { kind: "unreachable"; message: string };

export function App() {
  const [auth, setAuth] = useState<AuthState>({ kind: "checking" });

  const probe = useCallback(async () => {
    setAuth({ kind: "checking" });
    try {
      const principal = await api.me();
      setAuth({ kind: "signed_in", principal });
    } catch (e) {
      if (isApiError(e) && e.status === 401) setAuth({ kind: "anonymous" });
      else
        setAuth({
          kind: "unreachable",
          message: isApiError(e) ? e.message : "Cannot reach the Command Center server.",
        });
    }
  }, []);

  useEffect(() => {
    // Initial session probe: if /api/auth/me is 200, skip login.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void probe();
  }, [probe]);

  useEffect(() => {
    setUnauthorizedHandler(() => setAuth({ kind: "anonymous" }));
    return () => setUnauthorizedHandler(null);
  }, []);

  const signOut = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      // Even if the server is unreachable, drop to the login screen.
    }
    setAuth({ kind: "anonymous" });
  }, []);

  switch (auth.kind) {
    case "checking":
      return <FullScreenNotice title="Connecting" body="Checking your session." busy />;
    case "unreachable":
      return (
        <FullScreenNotice
          title="Server unavailable"
          body={`${auth.message} Make sure the backend is running, then try again.`}
          action={{ label: "Try again", onClick: () => void probe() }}
        />
      );
    case "anonymous":
      return <LoginScreen onSignedIn={(principal) => setAuth({ kind: "signed_in", principal })} />;
    case "signed_in":
      return <Shell principal={auth.principal} onSignOut={signOut} />;
  }
}
