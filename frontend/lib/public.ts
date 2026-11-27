"use client";

import { useEffect, useState } from "react";
import { apiGet } from "./api";

/** Public-demo status from the API (Phase 5.1). The access code itself is never returned by the server. */
export interface PublicStatus {
  public_mode: boolean; public_ai: boolean; ai_needs_access_code: boolean; read_only: boolean;
  limits: { ai_per_hour: number; ai_per_day: number; daily_usd: number } | null; spent_today_usd: number | null;
}

let cached: Promise<PublicStatus> | null = null;

export function usePublicStatus(): PublicStatus | null {
  const [status, setStatus] = useState<PublicStatus | null>(null);
  useEffect(() => {
    cached = cached ?? apiGet<PublicStatus>("/api/public/status").catch(() => {
      cached = null;
      return { public_mode: false, public_ai: false, ai_needs_access_code: false, read_only: false, limits: null, spent_today_usd: null };
    });
    cached.then(setStatus);
  }, []);
  return status;
}

const KEY = "gist-access-code";

/** The visitor's access code lives only in this tab's session storage and is sent as a header on AI requests. */
export function getAccessCode(): string {
  try { return window.sessionStorage.getItem(KEY) ?? ""; } catch { return ""; }
}

export function setAccessCode(code: string): void {
  try { if (code) window.sessionStorage.setItem(KEY, code); else window.sessionStorage.removeItem(KEY); } catch { /* storage may be blocked */ }
}
