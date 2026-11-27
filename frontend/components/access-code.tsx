"use client";

import { useEffect, useState } from "react";
import { KeyRound } from "lucide-react";
import { getAccessCode, PublicStatus, setAccessCode } from "@/lib/public";
import { Input } from "./ui";

/** Shown only in the public demo when AI features need an access code. */
export function AccessCodeField({ status }: { status: PublicStatus | null }) {
  const [code, setCode] = useState("");
  useEffect(() => setCode(getAccessCode()), []);
  if (!status?.public_mode) return null;
  if (!status.public_ai) return <p className="text-xs text-ink-3">AI features are turned off in this public demo. Rule-based mode and the stored AI runs still work.</p>;
  return <div className="flex flex-wrap items-center gap-2 text-xs text-ink-2">
    <KeyRound size={14} className="text-accent" aria-hidden="true"/>
    <label htmlFor="access-code">AI access code</label>
    <Input id="access-code" type="password" autoComplete="off" value={code} maxLength={80} className="h-8 w-48"
      onChange={e => { setCode(e.target.value); setAccessCode(e.target.value.trim()); }}/>
    {status.limits && <span className="text-ink-3">Limits: {status.limits.ai_per_hour} AI requests per hour, {status.limits.ai_per_day} per day, ${status.limits.daily_usd.toFixed(2)} shared daily budget.</span>}
  </div>;
}
