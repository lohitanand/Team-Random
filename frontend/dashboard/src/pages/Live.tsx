import { useEffect, useState } from "react";
import { API, get } from "../api";
import { Card, ConfidenceBar, FrictionTag, GateBadge, Loading, PriorityBadge, link, useApi } from "../components/ui";
import { TEAM_LABELS, humanize, money, pct, time } from "../format";

type LiveMsg = any;

export default function Live() {
  const [feed, setFeed] = useState<LiveMsg[]>([]);
  const [connected, setConnected] = useState(false);
  const recent = useApi(() => get("/sessions?limit=40"));

  useEffect(() => {
    const es = new EventSource(`${API}/stream/at-risk`);
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      setFeed((f) => [msg, ...f.filter((x) => !(x.session_id === msg.session_id && x.type === msg.type))].slice(0, 50));
    };
    return () => es.close();
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Live at-risk sessions</h1>
          <p className="text-sm text-slate-500">Streamed from the storefront tracker. Each row: risk score, friction, confidence and the recovery chosen from the playbook.</p>
        </div>
        <span className={`rounded-full px-3 py-1 text-xs font-medium ${connected ? "bg-emerald-100 text-emerald-800" : "bg-slate-100 text-slate-500"}`}>
          {connected ? "● Live stream connected" : "○ Connecting…"}
        </span>
      </div>

      <Card title={`Live feed (${feed.length})`}>
        {feed.length === 0 && <p className="text-sm text-slate-500">Waiting for events… open the storefront and use the demo panel to force a friction.</p>}
        <div className="space-y-2">
          {feed.map((m) => m.type === "session_ended" ? (
            <div key={`${m.session_id}-end`} className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm">
              Session <a className="font-mono text-indigo-600" href={link(`sessions/${m.session_id}`)}>{m.session_id}</a> ended · post-session recovery:{" "}
              <b>{humanize(m.recovery?.action_id)}</b> via {m.recovery?.channel} ({humanize(m.recovery?.status)})
              {m.recovery?.message && <div className="mt-1 text-slate-600">“{m.recovery.message}”</div>}
            </div>
          ) : (
            <a key={m.session_id} href={link(`sessions/${m.session_id}`)} className="block rounded-lg border border-slate-200 p-3 hover:border-indigo-300 hover:bg-indigo-50/40">
              <div className="flex flex-wrap items-center gap-3">
                <span className="font-mono text-sm text-indigo-700">{m.session_id}</span>
                <FrictionTag type={m.friction_type} />
                <GateBadge gate={m.gate} />
                <PriorityBadge priority={m.priority} />
                <span className="text-xs text-slate-500">risk {pct(m.risk_score, 0)} · {TEAM_LABELS[m.owner_team]} · {humanize(m.device)} · step {m.step} · cart {money(m.cart_value)}</span>
                {m.investigated && <span className="rounded-full bg-violet-100 px-2 py-0.5 text-xs text-violet-800">investigated</span>}
                <span className="ml-auto text-xs text-slate-400">{time(m.ts)}</span>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-slate-600">
                <ConfidenceBar value={m.confidence} />
                <span>signals: {(m.rule_flags ?? []).map(humanize).join(", ") || "model risk"}</span>
              </div>
              {m.nudge && (
                <div className="mt-2 rounded-md bg-emerald-50 p-2 text-sm text-emerald-900">
                  In-session nudge sent ({humanize(m.nudge.action_id)}): “{m.nudge.message}”
                </div>
              )}
            </a>
          ))}
        </div>
      </Card>

      <Card title="Recent at-risk sessions (live first, then historical)">
        {!recent.data ? <Loading error={recent.error} /> : (
          <table className="w-full text-sm">
            <thead><tr className="border-b border-slate-100 text-left text-xs text-slate-500">
              <th className="py-2 font-medium">Session</th><th className="font-medium">Source</th><th className="font-medium">Friction</th>
              <th className="font-medium">Confidence</th><th className="font-medium">Gate</th><th className="text-right font-medium">Risk</th><th className="text-right font-medium">Cart</th>
            </tr></thead>
            <tbody>
              {recent.data.map((s: any) => (
                <tr key={s.session_id} className="border-b border-slate-50 hover:bg-slate-50">
                  <td className="py-1.5"><a className="font-mono text-indigo-600" href={link(`sessions/${s.session_id}`)}>{s.session_id}</a></td>
                  <td className="text-xs text-slate-500">{s.source}</td>
                  <td><FrictionTag type={s.friction_type} /></td>
                  <td><ConfidenceBar value={s.confidence} /></td>
                  <td><GateBadge gate={s.gate} /></td>
                  <td className="text-right tabular">{pct(s.risk_score, 0)}</td>
                  <td className="text-right tabular">{money(s.cart_value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
