import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { get } from "../api";
import { Card, Loading, Stat, useApi } from "../components/ui";
import { friction, humanize, num, pct } from "../format";

export default function Evaluation() {
  const { data, error } = useApi(() => get("/eval"));
  if (!data) return <Loading error={error} />;
  const clf = data.friction_classifier?.per_friction ?? {};
  const rules = data.rules?.per_friction ?? {};
  const rows = Object.keys(clf).map((k) => ({
    name: friction(k), classifier_f1: clf[k].f1, rules_f1: rules[k]?.f1 ?? 0,
    precision: clf[k].precision, recall: clf[k].recall, support: clf[k].support,
    cause_acc: data.decisions?.cause_accuracy_by_friction?.[k],
  }));
  const risk = data.risk_model ?? {};
  const text = data.text_themes ?? {};
  const dec = data.decisions ?? {};
  const hold = data.holdout ?? {};

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Evaluation vs planted ground truth</h1>
        <p className="text-sm text-slate-500">Held-out test split (20% of sessions by hash). Synthetic data - numbers show the pipeline works end to end, not production accuracy.</p>
      </div>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Stat label="Cause accuracy (primary)" value={pct(dec.cause_accuracy_primary)} hint={`any planted: ${pct(dec.cause_accuracy_any_planted)}`} tone="green" />
        <Stat label="Detection coverage" value={pct(dec.detection_coverage)} hint={`${num(dec.test_friction_sessions)} friction sessions`} />
        <Stat label="False alerts on clean" value={pct(dec.clean_sessions_alerted, 2)} hint="clean sessions alerted" />
        <Stat label="Recovery lift vs holdout" value={`+${hold.lift_pp ?? 0} pp`} hint={`${pct(hold.treated_recovery_rate)} vs ${pct(hold.holdout_recovery_rate)} (simulated)`} tone="green" />
        <Stat label="Risk model PR-AUC" value={risk.pr_auc_all_prefixes?.toFixed(3) ?? "-"} hint={`base rate ${pct(risk.positive_rate)}`} />
        <Stat label="Text theme accuracy" value={pct(text.accuracy)} hint={`EN ${pct(text.accuracy_by_language?.en)} · Hinglish ${pct(text.accuracy_by_language?.hinglish)}`} />
        <Stat label="LLM guardrail pass rate" value={data.llm_outputs?.pass_rate == null ? "n/a" : pct(data.llm_outputs.pass_rate)} hint={`${num(data.llm_outputs?.drafted ?? 0)} LLM drafts`} />
        <Stat label="Alerts at high confidence" value={pct(data.alert_quality?.high_confidence_share)} hint={`${num(data.alert_quality?.alerts)} alerts`} />
      </div>

      <Card title="Per-friction F1: friction classifier vs rules">
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={rows}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
            <XAxis dataKey="name" tick={{ fontSize: 10 }} interval={0} angle={-15} textAnchor="end" height={60} />
            <YAxis domain={[0, 1]} tick={{ fontSize: 11 }} />
            <Tooltip /><Legend />
            <Bar dataKey="classifier_f1" name="Classifier F1" fill="#6366f1" />
            <Bar dataKey="rules_f1" name="Rules F1" fill="#94a3b8" />
          </BarChart>
        </ResponsiveContainer>
        <table className="mt-4 w-full text-sm">
          <thead><tr className="border-b border-slate-100 text-left text-xs text-slate-500">
            <th className="py-1 font-medium">Friction</th><th className="text-right font-medium">Precision</th><th className="text-right font-medium">Recall</th>
            <th className="text-right font-medium">Support</th><th className="text-right font-medium">Decision-layer cause accuracy</th>
          </tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.name} className="border-b border-slate-50"><td className="py-1">{r.name}</td>
              <td className="text-right tabular">{r.precision.toFixed(3)}</td><td className="text-right tabular">{r.recall.toFixed(3)}</td>
              <td className="text-right tabular">{r.support}</td><td className="text-right tabular">{pct(r.cause_acc)}</td></tr>
          ))}</tbody>
        </table>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Planted incidents">
          {Object.entries(data.incidents?.incidents ?? {}).map(([k, v]: any) => (
            <div key={k} className="flex justify-between border-b border-slate-50 py-2 text-sm">
              <span className="font-mono">{k}</span>
              <span className={v.detected ? "text-emerald-700" : "text-red-600"}>{v.detected ? `✓ detected (${v.packets} anomaly packets)` : "missed"}</span>
            </div>
          ))}
          <p className="mt-2 text-xs text-slate-500">Missing-size products flagged: {data.incidents?.missing_size_products_flagged} · other anomalies: {data.incidents?.unmatched_anomalies?.length ?? 0}</p>
        </Card>
        <Card title="Recovery by friction (treated vs holdout, simulated)">
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs text-slate-500"><th className="py-1 font-medium">Friction</th><th className="text-right font-medium">Treated</th><th className="text-right font-medium">Holdout</th></tr></thead>
            <tbody>{Object.entries(hold.by_friction ?? {}).map(([k, v]: any) => (
              <tr key={k} className="border-b border-slate-50"><td className="py-1">{humanize(k)}</td>
                <td className="text-right tabular">{pct(v.treated ? v.treated_recovered / v.treated : 0)} <span className="text-slate-400">({v.treated})</span></td>
                <td className="text-right tabular">{pct(v.holdout ? v.holdout_recovered / v.holdout : 0)} <span className="text-slate-400">({v.holdout})</span></td></tr>
            ))}</tbody>
          </table>
        </Card>
      </div>
    </div>
  );
}
