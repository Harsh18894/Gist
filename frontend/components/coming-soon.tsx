import { LockKeyhole } from "lucide-react";
import Link from "next/link";

export function ComingSoon({ title, description, phase }: { title: string; description: string; phase: string }) {
  return <><p className="mb-2 text-xs font-bold uppercase tracking-[.2em] text-brand">Gist / Roadmap</p><h1 className="text-3xl font-bold tracking-tight sm:text-4xl">{title}</h1><div className="mt-8 max-w-2xl rounded-2xl border border-line bg-white p-8 shadow-panel sm:p-10"><span className="inline-flex rounded-xl bg-pale p-3 text-brand"><LockKeyhole size={24}/></span><p className="mt-6 text-xs font-bold uppercase tracking-widest text-brand">Coming in {phase}</p><h2 className="mt-2 text-xl font-bold">{title} is coming soon</h2><p className="mt-3 text-sm leading-6 text-muted">{description}</p><Link href="/feedback" className="mt-6 inline-block text-sm font-bold text-brand hover:underline">Explore feedback instead →</Link></div></>;
}
