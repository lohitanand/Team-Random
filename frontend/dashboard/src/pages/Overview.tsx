import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { get } from "../api";
import { Card, FrictionTag, HealthBadge, Loading, Stat, link, useApi } from "../components/ui";
import { FRICTION_COLORS, TEAM_LABELS, friction, humanize, money, num, pct } from "../format";

function heatColor(rate: number): string {
  const a = Math.min(rate / 0.5, 1);
  return `rgba(239, 68, 68, ${0.08 + a * 0.75})`;
}

export default function Overview() {
  const { data, error } = useApi(() => get("/overview"));
  if (!data) return <Loading error={error} />;
  const { kpis, funnel, top_frictions, daily, recovery } = data;
  const devices: string[] = Array.from(new Set(funnel.heatmap.map((h: any) => h.segment)));
  const steps: string[] = funnel.steps.filter((s: any) => s.step !== "order").map((s: any) => s.step);
  const cell = (step: string, dev: string) => funnel.heatmap.find((h: any) => h.step === step && h.segment === dev);
  const frictionKeys = top_frictions.map((f: any) => f.friction_type);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Journey overview</h1>
        <p className="text-sm text-slate-500">Where customers drop off, why, and what it costs - one shared view for every team.</p>
      </div>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="Sessions" value={num(kpis.sessions)} hint={`${num(kpis.live_sessions)} live`} />
        <Stat label="Conversion" value={pct(kpis.conversion_rate)} hint="shopping sessions" />
        <Stat label="Cart abandonment" value={pct(kpis.cart_abandonment_rate)} tone="amber" />
        <Stat label="At-risk sessions" value={num(kpis.at_risk_sessions)} hint="medium + high confidence" />
        <Stat label="Revenue at risk" value={money(kpis.revenue_at_risk)} tone="red" />
        <Stat label="Open alerts" value={num(kpis.open_alerts)} hint={`${num(kpis.needs_review)} need review`} />
      </div>

      <div className="grid gap-6 lg:grid-cols-5">
        <Card title="Funnel" className="lg:col-span-2">
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={funnel.steps} layout="vertical" margin={{ left: 10 }}>
              <XAxis type="number" hide />
              <YAxis type="category" dataKey="step" width={70} tick={{ fontSize: 12 }} />
              <Tooltip formatter={(v: any) => num(v)} />
              <Bar dataKey="sessions" fill="#6366f1" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>
        <Card title="Drop-off heatmap (journey risk indicator)" className="lg:col-span-3">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-slate-500">
                <th className="py-1 text-left font-medium">Device</th>
                {steps.map((s) => <th key={s} className="py-1 font-medium">{s}</th>)}
              </tr>
            </thead>
            <tbody>
              {devices.map((d) => (
                <tr key={d}>
                  <td className="py-1 pr-2 text-slate-600">{humanize(d)}</td>
                  {steps.map((s) => {
                    const c = cell(s, d);
                    return (
                      <td key={s} className="p-0.5">
                        <div className="rounded-md py-2 text-center text-xs font-medium tabular" style={{ background: heatColor(c?.drop_rate ?? 0) }}>
                          {pct(c?.drop_rate ?? 0, 0)}
                        </div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-slate-500">Share of sessions that reached a step and left there without buying.</p>
        </Card>
      </div>

      <Card title="Top frictions by revenue at risk">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-100 text-left text-xs text-slate-500">
              <th className="py-2 font-medium">Friction</th><th className="font-medium">Owner</th>
              <th className="text-right font-medium">Sessions</th><th className="text-right font-medium">High conf.</th>
              <th className="text-right font-medium">Needs review</th><th className="text-right font-medium">Revenue at risk</th>
              <th className="pl-4 font-medium">Health</th>
            </tr>
          </thead>
          <tbody>
            {top_frictions.map((f: any) => (
              <tr key={f.friction_type} className="border-b border-slate-50 hover:bg-slate-50">
                <td className="py-2"><a href={link(`alerts?friction=${f.friction_type}`)}><FrictionTag type={f.friction_type} /></a></td>
                <td className="text-slate-600">{TEAM_LABELS[f.owner_team]}</td>
                <td className="text-right tabular">{num(f.sessions)}</td>
                <td className="text-right tabular text-emerald-700">{num(f.high)}</td>
                <td className="text-right tabular text-amber-700">{num(f.needs_review)}</td>
                <td className="text-right font-medium tabular">{money(f.revenue_at_risk)}</td>
                <td className="pl-4"><HealthBadge status={f.health?.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="At-risk sessions per day by friction" className="lg:col-span-2">
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={daily}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis dataKey="day" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v: any, name: any) => [v, friction(name)]} />
              {frictionKeys.map((k: string) => (
                <Area key={k} type="monotone" dataKey={k} stackId="1" stroke={FRICTION_COLORS[k]} fill={FRICTION_COLORS[k]} fillOpacity={0.5} />
              ))}
            </AreaChart>
          </ResponsiveContainer>
        </Card>
        <Card title="Recovery performance">
          <div className="grid grid-cols-2 gap-3">
            <Stat label="Recovered (treated)" value={pct(recovery.treated_recovery_rate)} tone="green" hint={`${num(recovery.treated)} customers`} />
            <Stat label="Holdout baseline" value={pct(recovery.holdout_recovery_rate)} hint={`${num(recovery.holdout)} customers`} />
          </div>
          <div className="mt-4 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">
            Lift vs holdout: <b>+{recovery.lift_pp} pp</b> · recovered value <b>{money(recovery.recovered_revenue)}</b>
          </div>
          <div className="mt-3 space-y-1 text-xs text-slate-600">
            {Object.entries(recovery.by_status ?? {}).map(([k, v]) => (
              <div key={k} className="flex justify-between"><span>{humanize(k)}</span><span className="tabular">{num(v as number)}</span></div>
            ))}
          </div>
          <p className="mt-3 text-xs text-slate-400">Outcomes on historical data are simulated (synthetic world).</p>
        </Card>
      </div>
    </div>
  );
}
