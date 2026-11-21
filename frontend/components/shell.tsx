"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart3, Compass, Layers3, MessageCircleQuestion, Settings2, Sparkles } from "lucide-react";

const links = [
  { href: "/", name: "Overview", icon: BarChart3 },
  { href: "/feedback", name: "Feedback Explorer", icon: Layers3 },
  { href: "/ask-gist", name: "Ask Gist", icon: MessageCircleQuestion },
  { href: "/opportunities", name: "Opportunities", icon: Compass },
  { href: "/settings", name: "Settings", icon: Settings2 },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return <div className="min-h-screen bg-canvas text-ink lg:flex">
    <aside className="border-b border-line bg-white lg:fixed lg:inset-y-0 lg:left-0 lg:w-64 lg:border-b-0 lg:border-r">
      <div className="flex items-center justify-between px-5 py-5 lg:px-6 lg:py-7">
        <Link href="/" className="flex items-center gap-3" aria-label="Gist home">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand text-white"><Sparkles size={18} strokeWidth={2.4}/></span>
          <span className="text-xl font-bold tracking-tight">Gist<span className="text-brand">.</span></span>
        </Link>
        <span className="rounded-full bg-pale px-2.5 py-1 text-[10px] font-bold uppercase tracking-widest text-brand lg:hidden">Demo</span>
      </div>
      <div className="px-3 pb-3 lg:px-4">
        <p className="hidden px-3 pb-3 text-[10px] font-semibold uppercase tracking-[.18em] text-muted lg:block">Workspace</p>
        <nav aria-label="Main navigation" className="flex gap-1 overflow-x-auto lg:flex-col">
          {links.map(({ href, name, icon: Icon }) => {
            const active = pathname === href;
            return <Link key={href} href={href} aria-current={active ? "page" : undefined}
              className={`flex shrink-0 items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${active ? "bg-pale text-brand" : "text-muted hover:bg-canvas hover:text-ink"}`}>
              <Icon size={17}/><span>{name}</span>
            </Link>;
          })}
        </nav>
      </div>
      <div className="hidden border-t border-line p-6 lg:absolute lg:inset-x-0 lg:bottom-0 lg:block">
        <div className="rounded-xl border border-line bg-canvas p-4">
          <div className="mb-2 flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-brand"><span className="h-2 w-2 rounded-full bg-brand"/>Demo workspace</div>
          <p className="text-xs leading-5 text-muted">Pulse is a fictional SaaS company. All data is synthetic.</p>
        </div>
      </div>
    </aside>
    <div className="min-w-0 flex-1 lg:ml-64">
      <header className="flex items-center justify-between border-b border-line bg-white px-5 py-4 sm:px-8 lg:px-10">
        <div className="text-xs font-medium text-muted">Gist <span className="mx-2 text-slate-300">/</span> {links.find(x => x.href === pathname)?.name || "Workspace"}</div>
        <span className="rounded-full border border-line px-3 py-1.5 text-xs font-semibold text-muted">Pulse · Synthetic data</span>
      </header>
      <main className="mx-auto max-w-7xl px-5 py-8 sm:px-8 lg:px-10 lg:py-10">{children}</main>
    </div>
  </div>;
}
