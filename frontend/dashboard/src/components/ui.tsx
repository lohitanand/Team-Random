import { ReactNode, useEffect, useState } from "react";
import { FRICTION_COLORS, friction } from "../format";

export function useApi<T = any>(loader: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    setError(null);
    loader().then((d) => alive && setData(d)).catch((e) => alive && setError(String(e)));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { data, error, reload: () => setTick((t) => t + 1) };
}

export function Card({ title, action, children, className = "" }: { title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-xl border border-slate-200 bg-white shadow-sm ${className}`}>
      {title && (
        <header className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-800">{title}</h2>
          {action}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Stat({ label, value, hint, tone = "slate" }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "slate" | "red" | "amber" | "green" }) {
  const tones = { slate: "text-slate-900", red: "text-red-600", amber: "text-amber-600", green: "text-emerald-600" };
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold tabular ${tones[tone]}`}>{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

const pill = "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap";

export function GateBadge({ gate }: { gate?: string | null }) {
  if (gate === "high") return <span className={`${pill} bg-emerald-100 text-emerald-800`}>High confidence</span>;
  if (gate === "medium") return <span className={`${pill} bg-amber-100 text-amber-800`}>⚠ Needs review</span>;
  return <span className={`${pill} bg-slate-100 text-slate-600`}>Low - monitor</span>;
}

export function PriorityBadge({ priority }: { priority?: string | null }) {
  const c = priority === "critical" ? "bg-red-600 text-white" : priority === "high" ? "bg-orange-100 text-orange-800" : "bg-slate-100 text-slate-600";
  return <span className={`${pill} ${c}`}>{priority ?? "normal"}</span>;
}

export function HealthBadge({ status }: { status?: string }) {
  const c = status === "critical" ? "bg-red-100 text-red-700" : status === "rising" ? "bg-amber-100 text-amber-800" : "bg-emerald-50 text-emerald-700";
  return <span className={`${pill} ${c}`}>{status ?? "normal"}</span>;
}

export function StatusBadge({ status }: { status?: string | null }) {
  const map: Record<string, string> = {
    open: "bg-blue-100 text-blue-800", needs_review: "bg-amber-100 text-amber-800", approved: "bg-emerald-100 text-emerald-800",
    assigned: "bg-violet-100 text-violet-800", dismissed: "bg-slate-100 text-slate-500", resolved: "bg-emerald-600 text-white",
    sent: "bg-emerald-100 text-emerald-800", pending_approval: "bg-amber-100 text-amber-800", holdout: "bg-slate-200 text-slate-700",
    suppressed_cap: "bg-slate-100 text-slate-500", suppressed_consent: "bg-slate-100 text-slate-500",
  };
  return <span className={`${pill} ${map[status ?? ""] ?? "bg-slate-100 text-slate-600"}`}>{(status ?? "-").replace(/_/g, " ")}</span>;
}

export function FrictionTag({ type }: { type?: string | null }) {
  const color = FRICTION_COLORS[type ?? ""] ?? "#64748b";
  return (
    <span className={`${pill} bg-slate-50 text-slate-700 ring-1 ring-slate-200`}>
      <span className="h-2 w-2 rounded-full" style={{ background: color }} />
      {friction(type)}
    </span>
  );
}

export function ConfidenceBar({ value }: { value: number }) {
  const color = value >= 0.8 ? "bg-emerald-500" : value >= 0.5 ? "bg-amber-400" : "bg-slate-300";
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-20 overflow-hidden rounded-full bg-slate-100"><div className={`h-full ${color}`} style={{ width: `${Math.round(value * 100)}%` }} /></div>
      <span className="text-xs tabular text-slate-600">{value.toFixed(2)}</span>
    </div>
  );
}

export function Breakdown({ b }: { b?: any }) {
  if (!b) return null;
  const items: [string, boolean, string][] = [
    ["Rules", b.rule_supports, "0.30"], ["Model + SHAP", b.model_supports, "0.30"],
    ["Customer text", b.text_supports, "0.20"], ["Aggregate", b.aggregate_supports, "0.20"],
  ];
  return (
    <div className="flex flex-wrap gap-2">
      {items.map(([label, ok, w]) => (
        <span key={label} className={`${pill} ${ok ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200" : "bg-slate-50 text-slate-400 ring-1 ring-slate-200"}`}>
          {ok ? "✓" : "○"} {label} <span className="opacity-60">{w}</span>
        </span>
      ))}
    </div>
  );
}

export function Loading({ error }: { error?: string | null }) {
  return <div className="p-8 text-sm text-slate-500">{error ? <span className="text-red-600">Failed to load: {error}</span> : "Loading…"}</div>;
}

export function Button({ children, onClick, tone = "default", disabled }: { children: ReactNode; onClick?: () => void; tone?: "default" | "primary" | "danger"; disabled?: boolean }) {
  const tones = {
    default: "bg-white text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50",
    primary: "bg-indigo-600 text-white hover:bg-indigo-700",
    danger: "bg-white text-red-600 ring-1 ring-red-200 hover:bg-red-50",
  };
  return (
    <button disabled={disabled} onClick={onClick} className={`rounded-lg px-3 py-1.5 text-sm font-medium transition disabled:opacity-40 ${tones[tone]}`}>
      {children}
    </button>
  );
}

export const link = (path: string) => `#/${path}`;
