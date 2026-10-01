import { useState } from "react";
import { get, post } from "../api";
import { Breakdown, Button, Card, ConfidenceBar, FrictionTag, GateBadge, Loading, PriorityBadge, StatusBadge, link, useApi } from "../components/ui";
import { TEAM_LABELS, humanize, money, pct, time } from "../format";

export default function AlertDetail({ id }: { id: string }) {
  const { data, error, reload } = useApi(() => get(`/alerts/${id}`), [id]);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [investigation, setInvestigation] = useState<any>(null);
  const [draft, setDraft] = useState<any>(null);
  if (!data) return <Loading error={error} />;
  const ev = data.key_evidence ?? {};
  const exp = data.explanation ?? {};

  async function act(action: string, extra: Record<string, unknown> = {}) {
    setBusy(action); setMsg(null);
    try {
      const r = await post(`/alerts/${id}/actions`, { action, actor: "demo_user", ...extra });
      setMsg(`${humanize(action)} → ${humanize(r.alert.status)}${r.execution.result.ticket_ref ? ` (${r.execution.result.ticket_ref}, simulated)` : ""}`);
      reload();
    } catch (e) { setMsg(String(e)); } finally { setBusy(null); }
  }
  async function run(name: string, fn: () => Promise<void>) {
    setBusy(name);
    try { await fn(); } catch (e) { setMsg(String(e)); } finally { setBusy(null); }
  }
  const closed = ["dismissed", "resolved"].includes(data.status);

  return (
    <div className="space-y-6">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          {data.alert_type === "aggregate" && <span className="rounded bg-red-600 px-2 py-0.5 text-xs font-semibold text-white">INCIDENT</span>}
          <FrictionTag type={data.friction_type} /><GateBadge gate={data.gate} /><PriorityBadge priority={data.priority} /><StatusBadge status={data.status} />
          <span className="text-xs text-slate-500">→ {TEAM_LABELS[data.owner_team]}</span>
        </div>
        <h1 className="mt-2 text-xl font-semibold">{data.title}</h1>
        <div className="mt-1 text-sm text-slate-500">
          {money(data.revenue_at_risk)} at risk · {data.affected_sessions} customer(s) · created {time(data.created_at)}
          {data.session_id && <> · <a className="text-indigo-600" href={link(`sessions/${data.session_id}`)}>session {data.session_id}</a></>}
        </div>
      </div>

      <Card title="Workflow">
        <div className="flex flex-wrap items-center gap-2">
          <Button tone="primary" disabled={closed || !!busy} onClick={() => act("approve")}>Approve</Button>
          <Button disabled={closed || !!busy} onClick={() => act("assign", { assignee: `${data.owner_team}_oncall` })}>Assign</Button>
          <Button disabled={closed || !!busy} onClick={() => act("create_ticket")}>Create ticket</Button>
          <Button tone="danger" disabled={closed || !!busy} onClick={() => act("dismiss")}>Dismiss</Button>
          <Button disabled={!["approved", "assigned"].includes(data.status) || !!busy} onClick={() => act("resolve")}>Resolve</Button>
          <span className="mx-2 h-6 w-px bg-slate-200" />
          <Button disabled={!!busy} onClick={() => run("investigate", async () => { setInvestigation(await post(`/agents/investigate/${encodeURIComponent(data.packet_id)}`)); reload(); })}>
            🔎 Run investigation agent
          </Button>
          <Button disabled={!!busy} onClick={() => run("draft", async () => { setDraft(await post(`/agents/cs-draft/${id}`)); reload(); })}>✉ Draft CS reply</Button>
          <Button disabled={!!busy} onClick={() => run("explain", async () => { await post(`/alerts/${id}/explain`); reload(); })}>✨ Redraft explanation</Button>
        </div>
        {busy && <p className="mt-2 text-xs text-slate-500">Working: {busy}…</p>}
        {msg && <p className="mt-2 text-sm text-slate-700">{msg}</p>}
        {data.gate === "medium" && <p className="mt-2 text-xs text-amber-700">Needs review: medium confidence - no automatic actions run until a person approves.</p>}
        <p className="mt-2 text-xs text-slate-400">Workflow actions are simulated (an execution record is written; nothing external is called).</p>
      </Card>

      {investigation && (
        <Card title="Investigation result (read-only tools)">
          <div className="text-sm">Confidence {investigation.before.confidence} ({investigation.before.gate}) → <b>{investigation.after.confidence}</b> ({investigation.after.gate})</div>
          <ul className="mt-2 space-y-1 text-sm text-slate-700">
            {investigation.findings.map((f: any, i: number) => <li key={i}>🔎 <b>{f.tool}</b>: {f.summary} {f.supports && <span className="text-emerald-700">✓ supports {humanize(f.supports)}</span>}</li>)}
          </ul>
        </Card>
      )}
      {draft && (
        <Card title={`CS reply draft (${draft.source === "llm" ? "LLM, guardrail-checked" : "template"}) - requires approval`}>
          <textarea className="h-28 w-full rounded-lg border border-slate-300 p-2 text-sm" defaultValue={draft.draft} id="cs-draft-text" />
          <div className="mt-2">
            <Button tone="primary" onClick={() => run("approve draft", async () => {
              const text = (document.getElementById("cs-draft-text") as HTMLTextAreaElement).value;
              const r = await post(`/agents/cs-draft/${draft.id}/approve`, { actor: "cs_agent", edited_text: text });
              setDraft({ ...draft, status: r.status }); setMsg("Reply approved and sent (simulated)."); reload();
            })}>Approve & send</Button>
          </div>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Explanation">
          <div className="space-y-2 text-sm">
            <div className="font-medium">{exp.summary}</div>
            <div><span className="text-slate-400">Behaviour observed: </span>{exp.behavior_observed}</div>
            <div><span className="text-slate-400">Likely business cause: </span>{exp.likely_business_cause}</div>
            <div className="text-xs text-slate-400">Source: {exp.source === "llm" ? "LLM (passed schema, grounding, consistency and policy checks)" : "deterministic template"}
              {exp.guardrail_failures?.length > 0 && <> · LLM draft rejected: {exp.guardrail_failures.join("; ")}</>}</div>
          </div>
          <div className="mt-4 border-t border-slate-100 pt-3 text-sm">
            <div className="text-xs font-semibold uppercase text-slate-400">Recommended team action</div>
            <div className="mt-1 rounded-lg bg-indigo-50 p-2 text-indigo-900">{data.team_action?.description}</div>
            {data.customer_action && <div className="mt-2 text-xs text-slate-600">Customer recovery: <b>{humanize(data.customer_action.id)}</b> - {data.customer_action.description} ({data.customer_action.auto_allowed ? "pre-approved" : "needs CS approval"})</div>}
          </div>
        </Card>
        <Card title="Evidence">
          <div className="space-y-2 text-sm">
            <div className="flex items-center gap-3">Confidence <ConfidenceBar value={data.confidence} /></div>
            <Breakdown b={ev.confidence_breakdown} />
            {ev.segment_type && (
              <div className="rounded-lg bg-red-50 p-2 text-red-900">{humanize(ev.segment_type)} <b>{ev.segment_value}</b>: {humanize(ev.metric)} {pct(ev.observed)} vs {pct(ev.baseline)} baseline ({ev.multiplier}x, z={ev.z_score}) · {time(ev.window_start)} → {time(ev.window_end)}</div>
            )}
            {ev.rule_flags?.length > 0 && <div><span className="text-slate-400">Rules: </span>{ev.rule_flags.map(humanize).join(", ")}</div>}
            {ev.top_signals?.length > 0 && <div><span className="text-slate-400">SHAP signals: </span>{ev.top_signals.map((s: any) => `${humanize(s.feature)} (${s.shap.toFixed(2)})`).join(", ")}</div>}
            {ev.text_themes?.length > 0 && <div><span className="text-slate-400">Customer text themes: </span>{ev.text_themes.map(humanize).join(", ")}</div>}
            {ev.aggregate_context?.segment && !ev.segment_type && <div className="text-red-700">Linked anomaly: {ev.aggregate_context.segment_type} {ev.aggregate_context.segment} ({ev.aggregate_context.multiplier}x)</div>}
            {ev.investigation_findings?.length > 0 && (
              <div><div className="text-slate-400">Investigation findings:</div>
                {ev.investigation_findings.map((f: any, i: number) => <div key={i} className="text-violet-700">🔎 {f.summary}{f.supports ? " ✓" : ""}</div>)}</div>
            )}
            {ev.sample_sessions?.length > 0 && (
              <div className="text-xs"><span className="text-slate-400">Sample sessions: </span>
                {ev.sample_sessions.slice(0, 8).map((s: string) => <a key={s} className="mr-2 font-mono text-indigo-600" href={link(`sessions/${s}`)}>{s}</a>)}</div>
            )}
          </div>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Customer recovery for this alert">
          {data.recoveries.length === 0 ? <p className="text-sm text-slate-500">No recovery actions.</p> : data.recoveries.map((r: any) => (
            <div key={r.id} className="border-b border-slate-50 py-2 text-sm">
              <div className="flex items-center justify-between"><span>{humanize(r.action_id)} · {r.channel} · {humanize(r.moment)}</span><StatusBadge status={r.status} /></div>
              {r.message && <div className="mt-1 text-slate-600">“{r.message}”</div>}
            </div>
          ))}
          {data.cs_drafts.length > 0 && <div className="mt-3 text-xs text-slate-500">CS drafts: {data.cs_drafts.map((d: any) => `#${d.id} ${humanize(d.status)}`).join(", ")}</div>}
        </Card>
        <Card title="Audit trail">
          <div className="max-h-80 space-y-1 overflow-y-auto text-xs">
            {data.audit_trail.map((a: any) => (
              <div key={a.id} className="flex gap-2 border-b border-slate-50 py-1">
                <span className="w-28 shrink-0 text-slate-400">{time(a.ts)}</span>
                <span className="w-40 shrink-0 font-medium">{humanize(a.event_type)}</span>
                <span className="w-20 shrink-0 text-slate-500">{a.actor}</span>
                <span className="truncate font-mono text-slate-500">{JSON.stringify(a.payload)}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
