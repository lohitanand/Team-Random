import { useEffect, useState } from "react";
import { get } from "./api";
import { TEAMS, parseRoute } from "./format";
import Overview from "./pages/Overview";
import TeamView from "./pages/TeamView";
import Live from "./pages/Live";
import SessionDetail from "./pages/SessionDetail";
import Alerts from "./pages/Alerts";
import AlertDetail from "./pages/AlertDetail";
import Evaluation from "./pages/Evaluation";
import Ask from "./pages/Ask";

const NAV = [
  { href: "#/overview", label: "Overview", page: "overview" },
  { href: "#/live", label: "Live at-risk", page: "live" },
  { href: "#/alerts", label: "Alerts", page: "alerts" },
  ...TEAMS.map((t) => ({ href: `#/team/${t.key}`, label: t.label, page: `team:${t.key}` })),
  { href: "#/ask", label: "Ask the analyst", page: "ask" },
  { href: "#/eval", label: "Evaluation", page: "eval" },
];

export default function App() {
  const [route, setRoute] = useState(parseRoute(window.location.hash));
  const [health, setHealth] = useState<any>(null);
  useEffect(() => {
    const onHash = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener("hashchange", onHash);
    get("/health").then(setHealth).catch(() => setHealth(null));
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const active = route.page === "team" ? `team:${route.id}` : route.page;

  return (
    <div className="flex h-full">
      <aside className="flex w-60 shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="px-5 py-5">
          <div className="text-xs font-semibold uppercase tracking-widest text-indigo-600">Friction</div>
          <div className="text-lg font-semibold leading-tight">Recovery Console</div>
        </div>
        <nav className="flex-1 space-y-0.5 px-3">
          {NAV.map((n, i) => (
            <div key={n.href}>
              {i === 3 && <div className="px-2 pb-1 pt-4 text-xs font-medium uppercase tracking-wide text-slate-400">Team views</div>}
              {i === 7 && <div className="px-2 pb-1 pt-4 text-xs font-medium uppercase tracking-wide text-slate-400">Insights</div>}
              <a href={n.href} className={`block rounded-lg px-3 py-2 text-sm ${active === n.page ? "bg-indigo-50 font-medium text-indigo-700" : "text-slate-600 hover:bg-slate-50"}`}>
                {n.label}
              </a>
            </div>
          ))}
        </nav>
        <div className="border-t border-slate-100 px-5 py-4 text-xs text-slate-500">
          <div>API: {health ? <span className="text-emerald-600">online</span> : <span className="text-red-600">offline</span>}</div>
          <div>LLM: {health?.llm_active ? `${health.llm_provider} (guardrailed)` : "off - deterministic templates"}</div>
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-7xl p-6">
          {route.page === "overview" && <Overview />}
          {route.page === "live" && <Live />}
          {route.page === "alerts" && !route.id && <Alerts key={window.location.hash} />}
          {route.page === "alerts" && route.id && <AlertDetail id={route.id} />}
          {route.page === "sessions" && route.id && <SessionDetail id={route.id} />}
          {route.page === "team" && route.id && <TeamView team={route.id} />}
          {route.page === "eval" && <Evaluation />}
          {route.page === "ask" && <Ask />}
        </div>
      </main>
    </div>
  );
}
