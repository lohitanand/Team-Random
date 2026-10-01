import { useState } from "react";
import { get } from "../api";
import { Card, ConfidenceBar, FrictionTag, GateBadge, Loading, PriorityBadge, StatusBadge, link, useApi } from "../components/ui";
import { FRICTION_LABELS, TEAMS, TEAM_LABELS, money, parseRoute, time } from "../format";

export default function Alerts() {
  const q = parseRoute(window.location.hash).query;
  const [filters, setFilters] = useState({
    alert_type: q.get("alert_type") ?? "", team: q.get("team") ?? "", friction: q.get("friction") ?? "",
    status: q.get("status") ?? "open,needs_review,approved,assigned", gate: "", source: "",
  });
  const [offset, setOffset] = useState(0);
  const params = new URLSearchParams(Object.entries({ ...filters, limit: "50", offset: String(offset) }).filter(([, v]) => v));
  const { data, error } = useApi(() => get(`/alerts?${params}`), [params.toString()]);
  const set = (k: string, v: string) => { setOffset(0); setFilters((f) => ({ ...f, [k]: v })); };
  const select = "rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Alerts</h1>
        <p className="text-sm text-slate-500">Incidents (aggregate) first, then session alerts by impact. Medium confidence is marked "needs review" and never triggers automatic actions.</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <select className={select} value={filters.alert_type} onChange={(e) => set("alert_type", e.target.value)}>
          <option value="">All types</option><option value="aggregate">Incidents (aggregate)</option><option value="session">Sessions</option>
        </select>
        <select className={select} value={filters.team} onChange={(e) => set("team", e.target.value)}>
          <option value="">All teams</option>{TEAMS.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
        </select>
        <select className={select} value={filters.friction} onChange={(e) => set("friction", e.target.value)}>
          <option value="">All frictions</option>{Object.entries(FRICTION_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select className={select} value={filters.gate} onChange={(e) => set("gate", e.target.value)}>
          <option value="">All confidence</option><option value="high">High</option><option value="medium">Needs review</option>
        </select>
        <select className={select} value={filters.status} onChange={(e) => set("status", e.target.value)}>
          <option value="open,needs_review,approved,assigned">Active</option><option value="">Any status</option>
          <option value="open">Open</option><option value="needs_review">Needs review</option><option value="resolved,dismissed">Closed</option>
        </select>
        <select className={select} value={filters.source} onChange={(e) => set("source", e.target.value)}>
          <option value="">Batch + live</option><option value="live">Live only</option>
        </select>
      </div>
      <Card title={data ? `${data.total.toLocaleString("en-IN")} alerts` : "Alerts"}>
        {!data ? <Loading error={error} /> : (
          <>
            <table className="w-full text-sm">
              <thead><tr className="border-b border-slate-100 text-left text-xs text-slate-500">
                <th className="py-2 font-medium">Alert</th><th className="font-medium">Friction</th><th className="font-medium">Team</th>
                <th className="font-medium">Confidence</th><th className="font-medium">Priority</th><th className="font-medium">Status</th>
                <th className="text-right font-medium">At risk</th><th className="text-right font-medium">When</th>
              </tr></thead>
              <tbody>
                {data.items.map((a: any) => (
                  <tr key={a.id} className="border-b border-slate-50 hover:bg-slate-50">
                    <td className="max-w-md py-2">
                      <a href={link(`alerts/${a.id}`)} className="line-clamp-1 text-indigo-700 hover:underline">
                        {a.alert_type === "aggregate" && <b className="mr-1 text-red-600">INCIDENT</b>}{a.title}
                      </a>
                    </td>
                    <td><FrictionTag type={a.friction_type} /></td>
                    <td className="text-xs text-slate-600">{TEAM_LABELS[a.owner_team]}</td>
                    <td><div className="flex flex-col gap-1"><ConfidenceBar value={a.confidence} /><GateBadge gate={a.gate} /></div></td>
                    <td><PriorityBadge priority={a.priority} /></td>
                    <td><StatusBadge status={a.status} /></td>
                    <td className="text-right tabular">{money(a.revenue_at_risk)}</td>
                    <td className="text-right text-xs text-slate-500">{time(a.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="mt-3 flex justify-between text-sm">
              <button disabled={offset === 0} className="text-indigo-600 disabled:text-slate-300" onClick={() => setOffset(Math.max(0, offset - 50))}>← Previous</button>
              <button disabled={offset + 50 >= data.total} className="text-indigo-600 disabled:text-slate-300" onClick={() => setOffset(offset + 50)}>Next →</button>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
