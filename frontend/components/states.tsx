import { AlertCircle, LoaderCircle } from "lucide-react";

export function Loading({ label = "Loading Gist data…" }: { label?: string }) {
  return <div role="status" className="flex min-h-52 items-center justify-center gap-3 rounded-2xl border border-line bg-white text-sm text-muted"><LoaderCircle className="animate-spin" size={18}/>{label}</div>;
}
export function ErrorState({ message, retry }: { message: string; retry: () => void }) {
  return <div role="alert" className="rounded-2xl border border-rose-200 bg-rose-50 p-7 text-center">
    <AlertCircle className="mx-auto mb-3 text-rose-600"/><p className="text-sm text-rose-900">{message}</p>
    <button onClick={retry} className="mt-4 rounded-lg bg-ink px-4 py-2 text-sm font-semibold text-white hover:bg-slate-700">Try again</button>
  </div>;
}
