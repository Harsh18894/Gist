"use client";

import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { cx } from "./ui";

const FOCUSABLE = 'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Modal surface. "drawer" slides in from the right on wide screens so the page
 * behind stays visible for context; both variants become a bottom sheet on phones.
 * Traps focus, closes on Escape or backdrop, restores focus, locks page scroll.
 */
export function Dialog({ open, onClose, title, kicker, children, variant = "drawer", size = "md", footer }: {
  open: boolean; onClose: () => void; title: React.ReactNode; kicker?: React.ReactNode; children: React.ReactNode;
  variant?: "drawer" | "center"; size?: "sm" | "md" | "lg"; footer?: React.ReactNode;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const [mounted, setMounted] = useState(false);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const { overflow } = document.body.style;
    document.body.style.overflow = "hidden";
    const frame = requestAnimationFrame(() => {
      const first = panel.current?.querySelector<HTMLElement>("[data-autofocus]") ?? panel.current;
      first?.focus();
    });
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); closeRef.current(); return; }
      if (e.key !== "Tab" || !panel.current) return;
      const items = Array.from(panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(el => el.offsetParent !== null);
      if (!items.length) { e.preventDefault(); return; }
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey, true);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("keydown", onKey, true);
      document.body.style.overflow = overflow;
      previous?.focus?.();
    };
  }, [open]);

  if (!open || !mounted) return null;
  const width = size === "sm" ? "sm:max-w-lg" : size === "lg" ? "sm:max-w-3xl" : "sm:max-w-2xl";
  return createPortal(<div className={cx("fixed inset-0 z-50 flex items-end", variant === "drawer" ? "sm:items-stretch sm:justify-end" : "sm:items-center sm:justify-center sm:p-6")}>
    <div className="absolute inset-0 bg-[rgb(20_18_14/.42)] animate-fade-in" onMouseDown={onClose} aria-hidden="true"/>
    <div ref={panel} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}
      className={cx("relative flex max-h-[92dvh] w-full flex-col overflow-hidden rounded-t-lg border border-line bg-surface shadow-overlay outline-none animate-sheet-in",
        variant === "drawer" ? cx("sm:max-h-none sm:rounded-none sm:border-y-0 sm:border-r-0 sm:animate-slide-in", width) : cx("sm:max-h-[88vh] sm:rounded-lg", width))}>
      <div className="mx-auto mt-2 h-1 w-9 shrink-0 rounded-full bg-line-strong sm:hidden" aria-hidden="true"/>
      <div className="flex shrink-0 items-start justify-between gap-4 border-b border-line px-5 pb-4 pt-3 sm:px-7 sm:pt-6">
        <div className="min-w-0">
          {kicker && <div className="mb-1 text-xs text-ink-3">{kicker}</div>}
          <h2 id={titleId} className="font-serif text-lg leading-snug text-ink" style={{ fontVariationSettings: '"opsz" 36' }}>{title}</h2>
        </div>
        <button type="button" onClick={onClose} aria-label="Close" className="-mr-2 -mt-1 flex h-10 w-10 shrink-0 items-center justify-center rounded text-ink-3 transition-colors hover:bg-sunken hover:text-ink"><X size={18}/></button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-5 sm:px-7 sm:py-6">{children}</div>
      {footer && <div className="safe-b shrink-0 border-t border-line px-5 py-3 sm:px-7">{footer}</div>}
    </div>
  </div>, document.body);
}
