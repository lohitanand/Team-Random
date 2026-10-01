import { useState } from "react";
import { post } from "../api";
import { Button, Card } from "../components/ui";
import { humanize } from "../format";

const EXAMPLES = [
  "What are the biggest frictions by revenue at risk?",
  "Which payment gateway is failing?",
  "Are couriers delaying deliveries?",
  "Where do customers drop off and why?",
];

export default function Ask() {
  const [question, setQuestion] = useState(EXAMPLES[0]);
  const [answer, setAnswer] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  async function ask(q: string) {
    setQuestion(q); setBusy(true); setAnswer(null);
    try { setAnswer(await post("/agents/ask", { question: q })); } catch (e) { setAnswer({ answer: String(e), tool_calls: [] }); }
    finally { setBusy(false); }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Ask the analyst</h1>
        <p className="text-sm text-slate-500">Answers come only from read-only tools; every number is checked against the tool results.</p>
      </div>
      <Card>
        <div className="flex gap-2">
          <input className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm" value={question}
            onChange={(e) => setQuestion(e.target.value)} onKeyDown={(e) => e.key === "Enter" && ask(question)} />
          <Button tone="primary" disabled={busy} onClick={() => ask(question)}>{busy ? "Thinking…" : "Ask"}</Button>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {EXAMPLES.map((e) => <button key={e} onClick={() => ask(e)} className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-700 hover:bg-slate-200">{e}</button>)}
        </div>
      </Card>
      {answer && (
        <Card title={`Answer (${answer.source === "llm" ? "LLM, grounded in tool results" : "deterministic"})`}>
          <p className="text-sm leading-relaxed">{answer.answer}</p>
          <div className="mt-4 border-t border-slate-100 pt-3">
            <div className="mb-1 text-xs font-semibold uppercase text-slate-400">Tools called ({answer.tool_calls.length})</div>
            {answer.tool_calls.map((c: any, i: number) => (
              <details key={i} className="border-b border-slate-50 py-1 text-xs">
                <summary className="cursor-pointer"><b>{humanize(c.tool)}</b> <span className="font-mono text-slate-500">{JSON.stringify(c.args)}</span></summary>
                <pre className="mt-1 max-h-48 overflow-auto rounded bg-slate-50 p-2 text-[11px]">{JSON.stringify(c.result, null, 2)}</pre>
              </details>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
