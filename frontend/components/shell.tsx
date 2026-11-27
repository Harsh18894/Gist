"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, Boxes, Gauge, ChartColumn, Compass, Database, FileSearch, FlaskConical, LifeBuoy, ListOrdered, Menu, Microscope, MessageSquareText, Monitor, Moon, Search, SearchCheck, Sun } from "lucide-react";
import { apiGet, RagStatus } from "@/lib/api";
import { Dialog } from "./dialog";
import { cx, Kbd } from "./ui";

type NavItem = { href: string; name: string; short?: string; icon: typeof Boxes; hint: string };
const PRIMARY: NavItem[] = [
  { href: "/", name: "Overview", icon: ChartColumn, hint: "Volumes, trends and breakdowns" },
  { href: "/ask-gist", name: "Ask Gist", short: "Ask", icon: SearchCheck, hint: "Question the evidence, with sources" },
  { href: "/investigate", name: "Investigate", icon: Microscope, hint: "Bounded multi-step analysis of a metric change" },
];
const EVIDENCE: NavItem[] = [
  { href: "/feedback", name: "Feedback", icon: MessageSquareText, hint: "Every customer record" },
  { href: "/tickets", name: "Support tickets", short: "Tickets", icon: LifeBuoy, hint: "Support conversations" },
  { href: "/evidence", name: "All sources", short: "Sources", icon: FileSearch, hint: "Search everything; see where it's used" },
];
const PIPELINE: NavItem[] = [
  { href: "/issues", name: "Issues", icon: Boxes, hint: "Recurring problems, grouped" },
  { href: "/opportunities", name: "Opportunities", icon: Compass, hint: "Evidence for each problem" },
  { href: "/priorities", name: "Priorities", icon: ListOrdered, hint: "Transparent, editable scoring" },
  { href: "/experiments", name: "Experiments", icon: FlaskConical, hint: "Draft tests to run" },
];
const SETTINGS: NavItem = { href: "/settings", name: "Data & usage", icon: Database, hint: "Dataset, index and API spend" };
const EVALUATION: NavItem = { href: "/evaluation", name: "Evaluation", icon: Gauge, hint: "Benchmarks, cost, traces and regressions" };
const ALL = [...PRIMARY, ...EVIDENCE, ...PIPELINE, EVALUATION, SETTINGS];
const MOBILE_TABS = [PRIMARY[0], PRIMARY[1], EVIDENCE[0], PIPELINE[0]];

const isActive = (pathname: string, href: string) => href === "/" ? pathname === "/" : pathname.startsWith(href);

/* ---------- Brand ---------- */

/** The wordmark closes on a quotation mark: Gist is built around what customers actually said. */
function Wordmark() {
  return <Link href="/" aria-label="Gist overview" className="flex items-baseline rounded-sm">
    <span className="font-serif text-[1.5rem] leading-none tracking-tight text-ink" style={{ fontVariationSettings: '"opsz" 48' }}>Gist</span>
    <span aria-hidden="true" className="ml-px font-serif text-[1.75rem] leading-none text-accent" style={{ fontVariationSettings: '"opsz" 72' }}>&rdquo;</span>
  </Link>;
}

/* ---------- Theme ---------- */

type Theme = "system" | "light" | "dark";
function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setTheme] = useState<Theme>("system");
  useEffect(() => { try { const t = localStorage.getItem("gist-theme"); if (t === "light" || t === "dark") setTheme(t); } catch { /* storage unavailable */ } }, []);
  const apply = useCallback((t: Theme) => {
    setTheme(t);
    if (t === "system") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t;
    try { if (t === "system") localStorage.removeItem("gist-theme"); else localStorage.setItem("gist-theme", t); } catch { /* storage unavailable */ }
  }, []);
  return [theme, apply];
}
const THEMES: { value: Theme; label: string; icon: typeof Sun }[] = [
  { value: "system", label: "System", icon: Monitor }, { value: "light", label: "Light", icon: Sun }, { value: "dark", label: "Dark", icon: Moon },
];
function ThemeSwitch({ theme, onChange }: { theme: Theme; onChange: (t: Theme) => void }) {
  return <div role="radiogroup" aria-label="Colour theme" className="flex rounded border border-line p-0.5">
    {THEMES.map(({ value, label, icon: Icon }) => <button key={value} type="button" role="radio" aria-checked={theme === value} aria-label={`${label} theme`} title={`${label} theme`}
      onClick={() => onChange(value)} className={cx("flex h-7 flex-1 items-center justify-center rounded-[3px] transition-colors duration-fast", theme === value ? "bg-sunken text-ink" : "text-ink-3 hover:text-ink")}>
      <Icon size={14}/></button>)}
  </div>;
}

/* ---------- Navigation ---------- */

function NavLink({ item, pathname, index, onNavigate }: { item: NavItem; pathname: string; index?: number; onNavigate?: () => void }) {
  const active = isActive(pathname, item.href);
  const Icon = item.icon;
  return <Link href={item.href} onClick={onNavigate} aria-current={active ? "page" : undefined}
    className={cx("group relative flex h-9 items-center gap-2.5 rounded px-2.5 text-sm transition-colors duration-fast",
      active ? "bg-surface font-medium text-ink shadow-[0_0_0_1px_rgb(var(--line))]" : "text-ink-2 hover:bg-sunken/70 hover:text-ink")}>
    {index !== undefined
      ? <span aria-hidden="true" className={cx("flex h-[18px] w-[18px] items-center justify-center rounded-full border font-mono text-[10px]", active ? "border-accent bg-accent text-accent-ink" : "border-line-strong text-ink-3 group-hover:border-control")}>{index}</span>
      : <Icon size={17} aria-hidden="true" className={active ? "text-accent" : "text-ink-3 group-hover:text-ink-2"}/>}
    <span>{item.name}</span>
  </Link>;
}

function NavGroups({ pathname, onNavigate }: { pathname: string; onNavigate?: () => void }) {
  return <div className="space-y-6">
    <ul className="space-y-0.5">{PRIMARY.map(i => <li key={i.href}><NavLink item={i} pathname={pathname} onNavigate={onNavigate}/></li>)}</ul>
    <div>
      <p className="eyebrow mb-1.5 px-2.5">Evidence</p>
      <ul className="space-y-0.5">{EVIDENCE.map(i => <li key={i.href}><NavLink item={i} pathname={pathname} onNavigate={onNavigate}/></li>)}</ul>
    </div>
    <div>
      <p className="eyebrow mb-1.5 px-2.5">Signal to decision</p>
      <ol className="relative space-y-0.5">
        <span aria-hidden="true" className="absolute bottom-[18px] left-[19px] top-[18px] w-px bg-line-strong"/>
        {PIPELINE.map((i, n) => <li key={i.href} className="relative"><NavLink item={i} pathname={pathname} index={n + 1} onNavigate={onNavigate}/></li>)}
      </ol>
    </div>
  </div>;
}

function DatasetBadge({ status }: { status: RagStatus | null }) {
  const version = status && status.dataset_version !== "unseeded" ? ` ${status.dataset_version}` : "";
  return <span className="inline-flex items-center gap-1.5 text-2xs text-ink-3" title="Pulse is a fictional SaaS company. All data in Gist is synthetic.">
    <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-caution"/>Pulse{version} · synthetic data
  </span>;
}

/* ---------- Command palette ---------- */

type Command = { id: string; label: string; hint?: string; icon: typeof Boxes; run: () => void; group: string };

function CommandPalette({ open, onClose, setTheme }: { open: boolean; onClose: () => void; setTheme: (t: Theme) => void }) {
  const router = useRouter();
  const pathname = usePathname();
  const [text, setText] = useState("");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const listId = "command-list";

  useEffect(() => { if (open) { setText(""); setActive(0); requestAnimationFrame(() => input.current?.focus()); } }, [open]);

  const go = useCallback((url: string) => {
    onClose();
    // Pages read their URL once on load, so a same-page jump with new parameters reloads.
    if (url.split("?")[0] === pathname && url.includes("?")) window.location.assign(url); else router.push(url);
  }, [onClose, pathname, router]);

  const commands = useMemo<Command[]>(() => {
    const q = text.trim();
    const actions: Command[] = q ? [
      { id: "ask", group: "Actions", label: `Ask Gist: “${q}”`, hint: "Retrieve sources", icon: SearchCheck, run: () => go(`/ask-gist?q=${encodeURIComponent(q)}`) },
      { id: "fb", group: "Actions", label: `Search feedback for “${q}”`, icon: MessageSquareText, run: () => go(`/feedback?query=${encodeURIComponent(q)}`) },
    ] : [];
    const pages: Command[] = ALL.map(i => ({ id: i.href, group: "Go to", label: i.name, hint: i.hint, icon: i.icon, run: () => go(i.href) }));
    const themes: Command[] = THEMES.map(t => ({ id: `theme-${t.value}`, group: "Theme", label: `${t.label} theme`, icon: t.icon, run: () => { setTheme(t.value); onClose(); } }));
    const needle = q.toLowerCase();
    const match = (c: Command) => !needle || `${c.label} ${c.hint ?? ""}`.toLowerCase().includes(needle);
    return [...actions, ...pages.filter(match), ...themes.filter(match)];
  }, [text, go, setTheme, onClose]);

  useEffect(() => { setActive(0); }, [text]);
  useEffect(() => { document.getElementById(`cmd-${active}`)?.scrollIntoView({ block: "nearest" }); }, [active]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { e.preventDefault(); onClose(); } };
    document.addEventListener("keydown", onKey);
    const { overflow } = document.body.style; document.body.style.overflow = "hidden";
    return () => { document.removeEventListener("keydown", onKey); document.body.style.overflow = overflow; };
  }, [open, onClose]);

  if (!open) return null;
  let lastGroup = "";
  return <div className="fixed inset-0 z-[70] flex items-start justify-center px-3 pt-[12vh]">
    <div className="absolute inset-0 bg-[rgb(20_18_14/.42)] animate-fade-in" onMouseDown={onClose} aria-hidden="true"/>
    <div role="dialog" aria-modal="true" aria-label="Command menu" className="relative w-full max-w-xl overflow-hidden rounded-lg border border-line bg-surface shadow-overlay animate-rise-in">
      <div className="flex items-center gap-3 border-b border-line px-4">
        <Search size={17} className="shrink-0 text-ink-3" aria-hidden="true"/>
        <input ref={input} value={text} onChange={e => setText(e.target.value)} placeholder="Jump to a page, or type a question…"
          role="combobox" aria-expanded="true" aria-controls={listId} aria-activedescendant={commands.length ? `cmd-${active}` : undefined} aria-autocomplete="list"
          onKeyDown={e => {
            if (e.key === "ArrowDown") { e.preventDefault(); setActive(a => Math.min(commands.length - 1, a + 1)); }
            if (e.key === "ArrowUp") { e.preventDefault(); setActive(a => Math.max(0, a - 1)); }
            if (e.key === "Enter") { e.preventDefault(); commands[active]?.run(); }
            if (e.key === "Tab") e.preventDefault();
          }}
          className="h-14 min-w-0 flex-1 bg-transparent text-base text-ink outline-none placeholder:text-ink-3"/>
        <Kbd>esc</Kbd>
      </div>
      <ul id={listId} role="listbox" aria-label="Commands" className="max-h-[50vh] overflow-y-auto p-1.5">
        {commands.length === 0 && <li className="px-3 py-8 text-center text-sm text-ink-3">Nothing matches “{text}”.</li>}
        {commands.map((c, i) => {
          const heading = c.group !== lastGroup ? (lastGroup = c.group) : null;
          const Icon = c.icon;
          return <li key={c.id} role="presentation">
            {heading && <p className="eyebrow px-2.5 pb-1 pt-2.5">{heading}</p>}
            <div id={`cmd-${i}`} role="option" aria-selected={i === active} onMouseMove={() => setActive(i)} onClick={c.run}
              className={cx("flex h-11 cursor-pointer items-center gap-3 rounded px-2.5 text-sm", i === active ? "bg-sunken text-ink" : "text-ink-2")}>
              <Icon size={16} className={i === active ? "text-accent" : "text-ink-3"} aria-hidden="true"/>
              <span className="min-w-0 flex-1 truncate">{c.label}</span>
              {c.hint && <span className="hidden truncate text-xs text-ink-3 sm:block">{c.hint}</span>}
              {i === active && <ArrowRight size={14} className="text-ink-3" aria-hidden="true"/>}
            </div>
          </li>;
        })}
      </ul>
    </div>
  </div>;
}

/* ---------- Shell ---------- */

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [theme, setTheme] = useTheme();
  const [palette, setPalette] = useState(false);
  const [menu, setMenu] = useState(false);
  const [status, setStatus] = useState<RagStatus | null>(null);
  const closePalette = useCallback(() => setPalette(false), []);
  const closeMenu = useCallback(() => setMenu(false), []);
  const current = ALL.find(i => isActive(pathname, i.href));

  useEffect(() => { document.title = current && current.href !== "/" ? `${current.name} · Gist` : "Gist · Product intelligence"; }, [current]);
  useEffect(() => {
    const controller = new AbortController();
    apiGet<RagStatus>("/api/rag/status", controller.signal).then(setStatus).catch(() => { /* the badge falls back to a generic label */ });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette(p => !p); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return <div className="min-h-dvh">
    <a href="#main" className="sr-only z-[80] rounded bg-ink px-3 py-2 text-paper focus:not-sr-only focus:fixed focus:left-3 focus:top-3">Skip to content</a>

    {/* Desktop sidebar */}
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col border-r border-line bg-paper lg:flex" aria-label="Sidebar">
      <div className="flex h-16 items-center px-5"><Wordmark/></div>
      <div className="px-3">
        <button type="button" onClick={() => setPalette(true)} className="flex h-9 w-full items-center gap-2 rounded border border-line bg-surface px-2.5 text-sm text-ink-3 transition-colors hover:border-line-strong hover:text-ink-2">
          <Search size={15} aria-hidden="true"/><span className="flex-1 text-left">Search or jump…</span><Kbd>⌘K</Kbd>
        </button>
      </div>
      <nav aria-label="Main" className="mt-5 flex-1 overflow-y-auto px-3 pb-4"><NavGroups pathname={pathname}/></nav>
      <div className="space-y-3 border-t border-line px-3 py-3">
        <NavLink item={EVALUATION} pathname={pathname}/>
        <NavLink item={SETTINGS} pathname={pathname}/>
        <div className="flex items-center justify-between gap-2 px-2.5"><DatasetBadge status={status}/></div>
        <ThemeSwitch theme={theme} onChange={setTheme}/>
      </div>
    </aside>

    {/* Mobile and tablet top bar */}
    <header className="sticky top-0 z-30 flex h-14 items-center justify-between gap-3 border-b border-line bg-paper/95 px-4 backdrop-blur-sm supports-[backdrop-filter]:bg-paper/85 lg:hidden" style={{ paddingTop: "env(safe-area-inset-top)" }}>
      <Wordmark/>
      <div className="flex min-w-0 items-center gap-1">
        <span className="mr-1 hidden min-w-0 truncate sm:block"><DatasetBadge status={status}/></span>
        <button type="button" onClick={() => setPalette(true)} aria-label="Search or jump" className="flex h-10 w-10 items-center justify-center rounded text-ink-2 hover:bg-sunken"><Search size={19}/></button>
        <button type="button" onClick={() => setMenu(true)} aria-label="Open menu" className="hidden h-10 w-10 items-center justify-center rounded text-ink-2 hover:bg-sunken sm:flex"><Menu size={20}/></button>
      </div>
    </header>

    <div className="lg:pl-60">
      <main id="main" tabIndex={-1} className="mx-auto w-full max-w-[1320px] px-4 pb-28 pt-6 outline-none sm:px-6 sm:pt-8 lg:px-10 lg:pb-16 lg:pt-12 2xl:px-14">
        <p className="mb-5 sm:hidden"><DatasetBadge status={status}/></p>
        {children}
      </main>
    </div>

    {/* Phone bottom bar: the four most-used destinations plus everything else */}
    <nav aria-label="Primary" className="safe-b fixed inset-x-0 bottom-0 z-30 border-t border-line bg-paper/95 backdrop-blur-sm supports-[backdrop-filter]:bg-paper/85 sm:hidden">
      <ul className="grid grid-cols-5">
        {MOBILE_TABS.map(item => {
          const active = isActive(pathname, item.href); const Icon = item.icon;
          return <li key={item.href}><Link href={item.href} aria-current={active ? "page" : undefined}
            className={cx("flex h-14 flex-col items-center justify-center gap-0.5 text-[11px]", active ? "font-medium text-accent" : "text-ink-3")}>
            <Icon size={20} aria-hidden="true"/>{item.short ?? item.name}</Link></li>;
        })}
        <li><button type="button" onClick={() => setMenu(true)} aria-haspopup="dialog"
          className={cx("flex h-14 w-full flex-col items-center justify-center gap-0.5 text-[11px]", MOBILE_TABS.some(t => isActive(pathname, t.href)) ? "text-ink-3" : "font-medium text-accent")}>
          <Menu size={20} aria-hidden="true"/>More</button></li>
      </ul>
    </nav>

    <Dialog open={menu} onClose={closeMenu} title="Gist" variant="drawer" size="sm"
      footer={<div className="flex items-center justify-between gap-4"><DatasetBadge status={status}/><div className="w-32"><ThemeSwitch theme={theme} onChange={setTheme}/></div></div>}>
      <nav aria-label="All pages"><NavGroups pathname={pathname} onNavigate={closeMenu}/>
        <div className="mt-6 border-t border-line pt-4"><NavLink item={EVALUATION} pathname={pathname} onNavigate={closeMenu}/><NavLink item={SETTINGS} pathname={pathname} onNavigate={closeMenu}/></div></nav>
    </Dialog>
    <CommandPalette open={palette} onClose={closePalette} setTheme={setTheme}/>
  </div>;
}
