"use client";

import { useState } from "react";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { apiPost } from "@/lib/api";
import { cx } from "./ui";

/** Helpful / not helpful on an AI-written result, with an optional comment. Stored locally for the Evaluation page. */
export function FeedbackButtons({ targetType, targetId }: { targetType: "investigation" | "ask"; targetId: string }) {
  const [rating, setRating] = useState<"up" | "down" | null>(null);
  const [comment, setComment] = useState("");
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");

  const send = async (r: "up" | "down", text?: string) => {
    setRating(r); setState("saving");
    try { await apiPost("/api/feedback", { target_type: targetType, target_id: targetId, rating: r, comment: text || null }); setState("saved"); }
    catch { setState("error"); }
  };

  return <div className="flex flex-wrap items-center gap-2 text-xs text-ink-2">
    <span>Was this helpful?</span>
    {(["up", "down"] as const).map(r => <button key={r} type="button" aria-pressed={rating === r} aria-label={r === "up" ? "Helpful" : "Not helpful"}
      onClick={() => send(r)} disabled={state === "saving"}
      className={cx("inline-flex h-7 w-7 items-center justify-center rounded border border-line-strong transition-colors duration-fast hover:border-control",
        rating === r ? "bg-accent-soft text-accent" : "bg-surface text-ink-3")}>
      {r === "up" ? <ThumbsUp size={13}/> : <ThumbsDown size={13}/>}</button>)}
    {rating && state !== "error" && <form className="flex min-w-[12rem] flex-1 items-center gap-1.5" onSubmit={e => { e.preventDefault(); send(rating, comment.trim()); }}>
      <label htmlFor={`fb-${targetId}`} className="sr-only">Optional comment</label>
      <input id={`fb-${targetId}`} value={comment} onChange={e => setComment(e.target.value)} maxLength={500} placeholder="Optional: what was off?"
        className="h-7 min-w-0 flex-1 rounded border border-line-strong bg-surface px-2 text-xs text-ink"/>
      <button type="submit" className="h-7 rounded border border-line-strong bg-surface px-2 text-xs text-ink hover:border-control">Send</button>
    </form>}
    <span role="status" className="text-ink-3">{state === "saved" ? "Thanks, recorded." : state === "error" ? "Could not record feedback." : ""}</span>
  </div>;
}

/** Short stable id for an asked question (the question text itself is not stored with feedback). */
export function askId(question: string, mode: string): string {
  let h = 5381;
  for (const c of `${mode}:${question}`) h = ((h << 5) + h + c.charCodeAt(0)) >>> 0;
  return `ask-${h.toString(36)}`;
}
