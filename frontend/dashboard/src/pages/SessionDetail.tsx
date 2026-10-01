import { useState } from "react";
import { get, post } from "../api";
import { Breakdown, Button, Card, ConfidenceBar, FrictionTag, GateBadge, Loading, PriorityBadge, StatusBadge, link, useApi } from "../components/ui";
import { TEAM_LABELS, friction, humanize, money, pct, time } from "../format";

const STEP_COLORS: Record<string, string> = {
  browse: "bg-slate-300", product: "bg-indigo-400", cart: "bg-sky-400", checkout: "bg-amber-400",
  payment: "bg-orange-500", order: "bg-emerald-500", post_purchase: "bg-violet-400",
};
const BAD = new Set(["payment_failed", "coupon_failed", "otp_failed", "otp_resend", "rage_click", "dead_click", "js_error",
  "slow_load", "size_unavailable_click", "search_zero_results", "notify_me", "exit", "order_cancelled"]);

export default function SessionDetail({ id }: { id: string }) {
  const { data, error, reload } = useApi(() => get(`/sessions/${encodeURIComponent(id)}`), [id]);
  const [recovery, setRecovery] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  if (!data) return <Loading error={error} />;
  const d = data.decision;
  const p = data.packet;
  const exp = data.explanation;

  async function trigger() {
    setBusy(true);
    try { setRecovery(await post(`/sessions/${encodeURIComponent(id)}/recover`, {})); reload(); }
    catch (e) { setRecovery({ error: String(e) }); }
    finally { setBusy(false); }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="font-mono text-xl font-semibold">{id}</h1>
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">{data.source}</span>
        {d && <><FrictionTag type={d.friction_type} /><GateBadge gate={d.gate} /><PriorityBadge priority={d.priority} /></>}
        {data.alert_id && <a className="text-sm text-indigo-600" href={link(`alerts/${data.alert_id}`)}>Open alert #{data.alert_id} →</a>}
      </div>

      {!p && <Card><p className="text-sm text-slate-600">This session is not at risk - no evidence packet was created (logged and monitored only).</p></Card>}

      {p && d && (
        <div className="grid gap-6 lg:grid-cols-3">
          <Card title="Why this session was flagged" className="lg:col-span-2">
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-4 text-sm">
                <span>Risk score <b className="tabular">{pct(p.risk_score, 0)}</b></span>
                <span className="flex items-center gap-2">Confidence <ConfidenceBar value={d.confidence} /></span>
                <span>Owner: <b>{TEAM_LABELS[d.owner_team]}</b></span>
                {d.secondary_friction && <span className="text-slate-500">secondary: {friction(d.secondary_friction)}</span>}
              </div>
              <Breakdown b={d.breakdown} />
              {exp && (
                <div className="rounded-lg bg-slate-50 p-3 text-sm">
                  <div className="font-medium">{exp.summary}</div>
                  <div className="mt-1 text-slate-700"><span className="text-slate-400">Behaviour: </span>{exp.behavior_observed}</div>
                  <div className="mt-1 text-slate-700"><span className="text-slate-400">Likely cause: </span>{exp.likely_business_cause}</div>
                  <div className="mt-2 text-xs text-slate-400">Explanation source: {exp.source === "llm" ? "LLM (passed guardrails)" : "deterministic template"} · evidence: {(exp.evidence_used ?? []).join(", ")}</div>
                </div>
              )}
              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <div className="mb-1 text-xs font-semibold uppercase text-slate-400">Top SHAP signals (risk)</div>
                  {(p.top_signals ?? []).map((s: any) => (
                    <div key={s.feature} className="flex items-center gap-2 text-xs">
                      <span className="w-40 truncate text-slate-600">{humanize(s.feature)}</span>
                      <div className="h-1.5 flex-1 rounded bg-slate-100"><div className="h-full rounded bg-red-400" style={{ width: `${Math.min(s.shap * 100, 100)}%` }} /></div>
                      <span className="w-10 text-right tabular text-slate-500">{s.shap.toFixed(2)}</span>
                    </div>
                  ))}
                </div>
                <div className="space-y-1 text-xs text-slate-600">
                  <div className="mb-1 font-semibold uppercase text-slate-400">Rule flags</div>
                  {(p.rule_flags ?? []).map((f: string) => <div key={f}>• {humanize(f)}</div>)}
                  {p.text_themes?.length > 0 && <div className="pt-1">Customer text: {p.text_themes.map(humanize).join(", ")}</div>}
                  {p.aggregate_context?.segment && <div className="pt-1 text-red-700">Linked anomaly: {p.aggregate_context.segment_type} {p.aggregate_context.segment} ({p.aggregate_context.multiplier}x)</div>}
                  {(p.investigation_findings ?? []).map((f: any, i: number) => (
                    <div key={i} className="text-violet-700">🔎 {f.summary}{f.supports ? " ✓" : ""}</div>
                  ))}
                </div>
              </div>
            </div>
          </Card>
          <Card title="Recommended recovery">
            {data.recommended ? (
              <div className="space-y-3 text-sm">
                <div><b>{humanize(data.recommended.action.id)}</b> · {data.recommended.action.channel} · {humanize(data.recommended.action.moment)}</div>
                <p className="text-slate-600">{data.recommended.action.description}</p>
                <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-emerald-900">“{data.recommended.message_preview}”</div>
                <div className="text-xs text-slate-500">
                  {data.recommended.action.auto_allowed ? "Pre-approved low-risk action (runs automatically at high confidence)." : "Requires customer-service approval."}
                </div>
                <Button tone="primary" disabled={busy || d.gate === "low"} onClick={trigger}>Trigger recovery</Button>
                {recovery && (
                  <div className="rounded-lg bg-slate-50 p-2 text-xs">
                    {recovery.error ? <span className="text-red-600">{recovery.error}</span> :
                      <>Result: <StatusBadge status={recovery.status} /> {recovery.holdout && "(holdout group - no message sent)"}</>}
                  </div>
                )}
              </div>
            ) : <p className="text-sm text-slate-500">No playbook action for this moment.</p>}
            {data.recoveries.length > 0 && (
              <div className="mt-4 border-t border-slate-100 pt-3">
                <div className="mb-1 text-xs font-semibold uppercase text-slate-400">Recovery history</div>
                {data.recoveries.map((r: any) => (
                  <div key={r.id} className="flex items-center justify-between py-1 text-xs">
                    <span>{humanize(r.action_id)} · {r.channel}</span><StatusBadge status={r.status} />
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      )}

      <Card title={`Journey path (${data.journey.length} events)`}>
        <div className="max-h-[480px] space-y-1 overflow-y-auto">
          {data.journey.map((e: any, i: number) => (
            <div key={i} className="flex items-start gap-3 text-sm">
              <span className="w-28 shrink-0 text-xs tabular text-slate-400">{time(e.ts)}</span>
              <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${STEP_COLORS[e.step] ?? "bg-slate-300"}`} />
              <span className={`w-44 shrink-0 ${BAD.has(e.event) ? "font-medium text-red-600" : ""}`}>{humanize(e.event)}</span>
              <span className="w-32 shrink-0 text-xs text-slate-500">{humanize(e.page)}</span>
              <span className="truncate font-mono text-xs text-slate-500">{e.product_id ?? ""} {Object.keys(e.metadata).length ? JSON.stringify(e.metadata) : ""}</span>
            </div>
          ))}
        </div>
      </Card>

      {data.synthetic_ground_truth && (
        <p className="text-xs text-slate-400">Planted label (synthetic data, for evaluation only): {data.synthetic_ground_truth.friction_types || "clean"} · {data.synthetic_ground_truth.primary_variant ?? ""} {data.synthetic_ground_truth.incident_id ?? ""} · cart {money(data.info?.cart_value)}</p>
      )}
    </div>
  );
}
