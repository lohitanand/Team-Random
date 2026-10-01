# Customer Journey Friction Detection & Recovery Assistant

Detects friction in e-commerce journeys, infers the likely business cause, and recommends approved
recovery actions to Customer Service, Marketing, Product and Operations.

**Rules and ML detect → deterministic logic decides → the LLM only drafts wording (always
validated, with deterministic fallbacks) → humans approve.** Everything works with `LLM_ENABLED=false`.

- Build rules / architecture: [CLAUDE.md](CLAUDE.md) · Product spec: [docs/PRD.md](docs/PRD.md) · Pitch script: [docs/DEMO.md](docs/DEMO.md)

## Quick start (Windows PowerShell, repo root)

```powershell
# one-time build: venv, deps, data, models, batch pipeline, evaluation, frontends (~5-10 min)
powershell -ExecutionPolicy Bypass -File scripts\build_all.ps1

# start API + dashboard + storefront (opens the browser)
powershell -ExecutionPolicy Bypass -File scripts\run_demo.ps1
```

| App | URL |
|---|---|
| Dashboard (business teams) | http://localhost:5173 |
| Storefront (acts out friction, demo panel on the right) | http://localhost:5174 |
| API docs | http://127.0.0.1:8000/docs |

### Manual start (three windows)

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --port 8000
cd frontend\dashboard; npm run dev
cd frontend\storefront; npm run dev
```

### LLM (optional)

Edit `.env`: set `GROQ_API_KEY` and `LLM_ENABLED=true` (models `openai/gpt-oss-20b` / `openai/gpt-oss-120b`).
OpenRouter is a fallback only (`OPENROUTER_API_KEY` + verified model IDs). Check models with
`python -m scripts.list_models`. Without keys, deterministic templates are used everywhere.

## Pipeline commands

```powershell
python -m datagen.generate                  # 20k synthetic sessions, 10 planted frictions, 3 incidents
python -m backend.app.ingestion.pipeline    # clean, sessionize (30 min), features, prefixes, joins
python -m backend.ml.train_risk             # LightGBM risk (prefixes) + isotonic + SHAP
python -m backend.ml.train_friction         # LightGBM one-vs-rest friction classifier
python -m backend.ml.train_text             # multilingual embeddings + LogisticRegression themes
python -m backend.app.pipeline              # packets -> decisions -> investigation -> alerts/recovery/audit (DB)
python -m backend.ml.evaluate               # data\reports\eval.json
python -m backend.app.detection.anomaly     # print aggregate anomalies + planted incident matches
pytest backend\tests
```

## What is where

| Layer | Code |
|---|---|
| Synthetic data (10 frictions x 4-7 variants, Hinglish text, incidents) | `datagen/` |
| Ingestion, sessionization, features, joins, tracker ingest | `backend/app/ingestion/` |
| Rules, anomaly detection, risk model, friction classifier, text themes | `backend/app/detection/` |
| Evidence packets | `backend/app/fusion/evidence.py` |
| Deterministic decision layer + playbooks (only source of actions) | `backend/app/decision/` |
| LLM client (Groq/OpenRouter via httpx), guardrails, fallbacks | `backend/app/llm/` |
| Read-only agent tools, investigator, CS copilot, analyst | `backend/app/agents/` |
| Alerts, workflows, recovery (holdout, cap, consent) | `backend/app/actions/` |
| Audit log, holdout, outcomes | `backend/app/audit/` |
| API + SSE live feed | `backend/app/api/`, `backend/app/live.py` |
| Dashboard / storefront + `tracker.js` | `frontend/dashboard`, `frontend/storefront` |

## Results (held-out 20% test split, synthetic data)

| Metric | Value |
|---|---|
| Friction sessions detected (evidence packet) | 99.1% |
| Cause classification accuracy (primary / any planted) | 95.9% / 99.5% |
| Clean sessions alerted (false alerts) | 0.19% |
| Risk model PR-AUC (prefixes, base rate 0.55) | 0.83 |
| Text theme accuracy (EN / Hinglish) | 94.9% (96.8% / 90.5%) |
| Planted incidents detected | 3 / 3 (Gateway B spike, CourierX delays, missing size charts) |

The friction classifier scores ~0.99 F1 because synthetic variants are very separable - treat as a
pipeline check, not production accuracy. Recovery outcomes / holdout lift on history are **simulated**.
