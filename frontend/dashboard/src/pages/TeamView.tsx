import { get } from "../api";
import { Card, FrictionTag, GateBadge, HealthBadge, Loading, PriorityBadge, StatusBadge, link, useApi } from "../components/ui";
import { TEAM_LABELS, humanize, money, num } from "../format";

function Segments({ label, values }: { label: string; values: { value: string; sessions: number }[] }) {
  if (!values?.length) return null;
  return (
    <div className="text-xs text-slate-600">
      <span className="text-slate-400">{label}: </span>
      {values.map((v) => `${humanize(v.value)} (${v.sessions})`).join(", ")}
    </div>
  );
}

export default function TeamView({ team }: { team: string }) {
  const { data, error } = useApi(() => get(`/teams/${team}/insights`), [team]);
  if (!data) return <Loading error={error} />;
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">{TEAM_LABELS[team]} view</h1>
        <p className="text-sm text-slate-500">Only the friction this team owns - what's happening → why → recommended action → act.</p>
      </div>
      {data.items.map((item: any) => (
        <Card key={item.friction_type} title={<span className="flex items-center gap-2"><FrictionTag type={item.friction_type} /><HealthBadge status={item.health?.status} /></span>}
          action={<span className="text-sm font-semibold text-red-600">{money(item.what.revenue_at_risk)} at risk</span>}>
          <div className="grid gap-5 lg:grid-cols-3">
            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">What's happening</div>
              <div className="text-sm">
                <b>{num(item.what.sessions)}</b> at-risk sessions · <span className="text-emerald-700">{num(item.what.high_confidence)} high</span> ·{" "}
                <span className="text-amber-700">{num(item.what.needs_review)} need review</span>
                {item.what.aggregate_anomalies > 0 && <> · <b className="text-red-600">{item.what.aggregate_anomalies} incident(s)</b></>}
              </div>
              <div className="mt-2 space-y-0.5">
                <Segments label="Devices" values={item.what.top_devices} />
                <Segments label="Cities" values={item.what.top_cities} />
                <Segments label="Products" values={item.what.top_products} />
                <Segments label="Gateways" values={item.what.top_gateways} />
                <Segments label="Couriers" values={item.what.top_couriers} />
              </div>
            </div>
            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Why</div>
              <p className="text-sm text-slate-700">{item.why.likely_cause}</p>
              <ul className="mt-2 space-y-0.5 text-xs text-slate-600">
                {item.why.rule_flags.map((r: any) => <li key={r.flag}>• {r.description} <span className="text-slate-400">({num(r.sessions)})</span></li>)}
              </ul>
              {item.why.themes.length > 0 && (
                <div className="mt-2 text-xs text-slate-600"><span className="text-slate-400">Customers say: </span>
                  {item.why.themes.map((t: any) => `${humanize(t.theme)} (${t.texts})`).join(", ")}</div>
              )}
            </div>
            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Recommended action</div>
              {item.recommended_action.incident && item.what.aggregate_anomalies > 0 && (
                <div className="mb-2 rounded-lg bg-red-50 p-2 text-sm text-red-800">Incident: {item.recommended_action.incident.description}</div>
              )}
              <div className="rounded-lg bg-indigo-50 p-2 text-sm text-indigo-900">{item.recommended_action.team.description}</div>
              <div className="mt-2 text-xs text-slate-500">Customer recovery: {item.recommended_action.customer.map((c: any) => humanize(c.id)).join(" · ")}</div>
            </div>
          </div>
          {item.alerts.length > 0 && (
            <div className="mt-4 border-t border-slate-100 pt-3">
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Act on alerts</div>
              <div className="space-y-1">
                {item.alerts.map((a: any) => (
                  <a key={a.id} href={link(`alerts/${a.id}`)} className="flex items-center justify-between gap-3 rounded-lg px-2 py-1.5 text-sm hover:bg-slate-50">
                    <span className="truncate">{a.alert_type === "aggregate" && <b className="mr-1 text-red-600">INCIDENT</b>}{a.title}</span>
                    <span className="flex shrink-0 items-center gap-2"><PriorityBadge priority={a.priority} /><GateBadge gate={a.gate} /><StatusBadge status={a.status} /></span>
                  </a>
                ))}
              </div>
              <a href={link(`alerts?team=${team}&friction=${item.friction_type}`)} className="mt-2 inline-block text-xs text-indigo-600">All {humanize(item.friction_type)} alerts →</a>
            </div>
          )}
        </Card>
      ))}
    </div>
  );
}
