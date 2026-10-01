# CLAUDE.md — Customer Journey Friction Detection & Recovery Assistant

This file is the source of truth for how to build this project. Read it fully before writing code.
The full product spec is in `docs/PRD.md`. If this file and the PRD disagree, this file wins.

---

## 1. What we are building

An AI-powered system for e-commerce teams that:
1. **Detects** customer journey friction (per session and across many sessions).
2. **Infers likely causes**, with explanations that connect customer behavior to business causes.
3. **Recommends practical recovery actions** for customers and for business teams (CS, Marketing, Product, Operations).
4. Surfaces **journey risk indicators, recommended interventions, assisted responses, and workflow triggers** in a dashboard.

This is a hackathon MVP built on **synthetic data with planted, labeled friction** so we can measure detection accuracy.

---

## 2. Core principles (non-negotiable)

1. **The LLM is never the final authority.** Rules + ML detect. Deterministic logic decides. Humans approve. The LLM only drafts language (explanations, messages) and classifies text when the fast classifier is unsure.
2. **Every LLM output is validated** (schema, grounding, consistency, policy). On any failure, use a fallback template. The system must work with the LLM disabled.
3. **Agents investigate, never decide or act.** Agents use read-only tools, have step and time limits, and return an evidence packet that goes back into the deterministic decision layer.
4. **Actions come only from the playbook** (`backend/app/decision/playbooks.yaml`). Nothing — LLM or agent — may invent offers, discounts, refunds or actions.
5. **Privacy:** never capture or store typed card numbers, passwords, OTPs or raw personal data. User IDs are hashed.
6. **Deterministic and reproducible:** fixed random seeds, same input → same friction type and confidence.
7. **Explainability everywhere:** every alert and recovery must carry the evidence that produced it, and every decision is written to the audit log.

---

## 3. Friction taxonomy

Use these exact keys everywhere (code, DB, API, UI).

### Core (from the problem statement — highest priority)
| Key | Friction | Owner team |
|---|---|---|
| `unclear_product_info` | Unclear product information | product |
| `delivery_uncertainty` | Delivery uncertainty | operations |
| `payment_failure` | Payment failures | operations_tech |
| `poor_recommendations` | Poor recommendations | marketing |
| `post_purchase_concern` | Post-purchase concerns | customer_service |

### Extended (MVP bonus)
| Key | Friction | Owner team |
|---|---|---|
| `price_shock` | Hidden costs / price shock | marketing |
| `coupon_failure` | Coupon failure | marketing |
| `login_otp_issue` | Forced login / OTP issues | customer_service |
| `out_of_stock` | Out of stock / size unavailable | product |
| `technical_glitch` | Technical glitches | operations_tech |

Cart abandonment and comparison behavior are **symptoms**, not friction types.

---

## 4. Architecture (data flow)

```
Data sources (clickstream, transactions, feedback, catalog)
  → Ingestion & sessionization (clean, hash IDs, sessionize, funnel map, features, join by IDs)
  → Detection (rules | LightGBM risk + SHAP | LightGBM friction classifier | text themes | anomaly stats)
  → Evidence fusion (session packets + aggregate packets)
  → Decision layer — DETERMINISTIC (classify → confidence → gate → route → priority → playbook)
       └─ medium confidence → Investigation agent (read-only) → enriched evidence → back to decision layer
  → LLM assist (draft explanation + customer message) → Guardrail validation → fallback template on failure
  → Actions (team alert + workflow triggers with human approval | customer recovery)
  → Dashboard (shared overview + team views + live at-risk feed + analyst Q&A)
  → Audit log + outcome tracking (holdout group) → tunes thresholds/playbooks
```

---

## 5. Tech stack

| Area | Choice |
|---|---|
| Backend | Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.0 |
| DB | SQLite for dev (`data/app.db`); Postgres-compatible SQL only |
| Data | pandas, NumPy, Faker |
| ML | LightGBM, SHAP, scikit-learn |
| Text | sentence-transformers (`paraphrase-multilingual-MiniLM-L12-v2`) + LogisticRegression — added in Phase 5 with the **CPU-only** PyTorch build |
| LLM | Groq (primary) with open-weight models: `openai/gpt-oss-20b` (fast), `openai/gpt-oss-120b` (agent). OpenRouter is a **fallback only**. Both are called through one small OpenAI-compatible client built on `httpx` — **no vendor SDKs** |
| Jobs | APScheduler |
| Live feed | Server-Sent Events |
| Frontend | React + Vite + TypeScript + Tailwind + Recharts (`frontend/dashboard`, `frontend/storefront`) |
| Support libs | uvicorn, pydantic-settings, PyYAML, pyarrow, httpx (versions pinned in `backend/requirements.txt`) |
| Tests | pytest, Vitest |

Do not add Kafka, Redis, Celery, LangChain, vendor LLM SDKs or other heavy frameworks. Keep dependencies minimal and ask before adding anything new.

**LLM call rules**
- Request JSON output (`response_format`) where the provider/model supports it, but **always** run the full guardrail validation (§7.7). Never trust the model's JSON.
- Agents use OpenAI-style tool calling. If the provider/model rejects tools, the agent returns the original packet unchanged.
- Order of attempts: primary provider → fallback provider (only if its key and model are set) → deterministic fallback template.

---

## 6. Repository structure

```
E-commerce/                     # repo root
├── CLAUDE.md
├── README.md
├── .env.example                # committed; .env is never committed
├── docs/PRD.md
├── scripts/list_models.py      # prints models available for the configured LLM provider
├── data/                       # generated data, db, model artifacts (gitignored)
├── datagen/
│   ├── config.yaml             # sizes, friction rates, seeds
│   ├── catalog.py              # products, prices, ETAs, stock
│   ├── scenarios.py            # one function per friction type (plants behavior + ground truth)
│   ├── text.py                 # reviews / tickets / chats per theme (incl. Hinglish)
│   └── generate.py             # entrypoint → data/raw/*.parquet + ground_truth.parquet
├── backend/
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py  config.py
│   │   ├── db/            models.py, session.py
│   │   ├── schemas/       events.py, evidence.py, llm.py, alerts.py, recovery.py
│   │   ├── ingestion/     collect.py (tracker endpoint), sessionize.py, features.py, joins.py
│   │   ├── detection/     rules.py, risk_model.py, friction_classifier.py, text_themes.py, anomaly.py
│   │   ├── fusion/        evidence.py
│   │   ├── decision/      classify.py, confidence.py, gating.py, routing.py, priority.py,
│   │   │                  playbook.py, playbooks.yaml
│   │   ├── llm/           client.py, explain.py, messages.py, guardrails.py, fallbacks.py, prompts/
│   │   ├── agents/        tools.py (read-only), investigator.py, cs_copilot.py, analyst.py
│   │   ├── actions/       alerts.py, recovery.py, workflows.py
│   │   ├── audit/         log.py, outcomes.py, holdout.py
│   │   └── api/           routes_events.py, routes_dashboard.py, routes_alerts.py,
│   │                      routes_sessions.py, routes_agents.py, sse.py
│   ├── ml/                train_risk.py, train_friction.py, train_text.py, evaluate.py
│   └── tests/
└── frontend/
    ├── dashboard/          # business-team dashboard
    └── storefront/         # mock store + tracker.js for the live demo
```

---

## 7. Module specifications

### 7.1 Synthetic data generator (`datagen/`)
- ~20,000 sessions over 14 days, ~2,000 users, ~300 products, 3 payment gateways, 6 couriers, 20 cities (tier 1/2/3).
- Funnel: `browse → product → cart → checkout → payment → order → post_purchase`.
- Friction mix: each of the 10 types in ~4–8% of sessions; ~40% clean sessions (many convert); ~10% sessions with **two overlapping frictions**; add noise (random hesitation, rage clicks in clean sessions) so the task isn't trivial.
- Plant **aggregate incidents** too, e.g. Gateway B failure spike for 2 hours on day 9; Courier X delays in 3 cities on days 5–7; 12 products missing size info.
- Output tables: `events`, `payments`, `orders`, `tickets`, `reviews`, `chats`, `products`, `ground_truth` (session_id → friction types, abandoned, incident_id).
- Fixed seed from `config.yaml`.

### 7.2 Event schema (`schemas/events.py`)
```json
{
  "session_id": "s_1042", "user_id": "u_88_hashed", "timestamp": "ISO8601",
  "event": "payment_failed", "page": "checkout_payment",
  "product_id": "p_311", "order_id": null,
  "metadata": { "method": "UPI", "gateway": "B", "error": "timeout", "cart_value": 2499 }
}
```
Event names (extend only if needed): `page_view, product_view, size_chart_open, spec_open, review_open, search, search_zero_results, rec_impression, rec_click, add_to_cart, remove_from_cart, cart_view, checkout_start, pincode_check, delivery_info_view, total_shown, coupon_apply, coupon_failed, login_wall, otp_sent, otp_resend, otp_failed, payment_attempt, payment_failed, payment_success, order_placed, tracking_view, rage_click, dead_click, js_error, slow_load, size_unavailable_click, notify_me, exit`.

### 7.3 Ingestion & features (`ingestion/`)
- Sessionize with a 30-minute inactivity rule; map the furthest funnel step reached and the exit step.
- Features per session (and per session **prefix** for live scoring): step dwell times + z-scores vs step baseline, loop counts (PDP↔PDP, checkout↔cart), retries (payment/coupon/OTP), method switches, info-seeking counts, rage/dead clicks, error counts, slow loads, cart value, device, city tier, new vs returning, time of day.
- Join payments/orders/tickets/reviews by `session_id`, `user_id`, `order_id`, `product_id`.

### 7.4 Detection (`detection/`)
- **rules.py:** explicit, named rules returning `rule_flags` (e.g. `payment_retry_x2`, `coupon_retry_x3`, `otp_resend_x2`, `rage_click_checkout`, `exit_after_total_shown`). Each rule maps to a friction key.
- **risk_model.py:** LightGBM binary (abandoned vs converted), trained on prefixes; isotonic calibration; returns `risk_score` + top-5 SHAP signals.
- **friction_classifier.py:** LightGBM one-vs-rest over the 10 friction keys, trained on ground truth; returns per-type probabilities. It is **one input** to classification, never the final answer.
- **text_themes.py:** multilingual embeddings + LogisticRegression → themes `delivery_delay, size_fit, payment_trust, money_deducted, missing_info, return_refund, login_issue, stock, price_fees, app_bug, other`. If max probability < 0.6, call the LLM zero-shot with the same label set and a strict JSON schema; if the LLM fails, label `other`.
- **anomaly.py:** rolling mean/std and EWMA per segment (gateway, courier, city, device, step, product) over 15–60 minute windows; flag when z > 3 or rate ≥ 2.5× baseline. Output aggregate packets.

### 7.5 Evidence fusion (`fusion/evidence.py`)
Build one packet per at-risk session and one per aggregate anomaly:
```json
{
  "packet_type": "session",
  "session_id": "s_1042",
  "risk_score": 0.82,
  "rule_flags": ["payment_retry_x2"],
  "top_signals": [{"feature": "payment_failures", "shap": 0.31}],
  "friction_probs": {"payment_failure": 0.88},
  "text_themes": ["money_deducted"],
  "aggregate_context": {"gateway": "B", "failure_rate_multiplier": 4.0, "affected_sessions": 2000},
  "cart_value": 2499
}
```

### 7.6 Decision layer (`decision/`) — fully deterministic, no LLM calls
- **classify.py:** primary (and optional secondary) friction type from rule flags → friction mapping, friction_probs, SHAP signal groups, and text themes. Tie-break: rules > classifier > themes.
- **confidence.py:** weighted agreement for the chosen type:
  `0.30 * rule_supports + 0.30 * model_supports (friction_prob ≥ 0.6 and SHAP signals map to the type) + 0.20 * text_supports + 0.20 * aggregate_supports` → 0–1.
- **gating.py:** `≥ 0.80` high → alert with triggers; `0.50–0.79` medium → send to investigation agent, then re-score; if still medium, alert as "needs review" with no auto actions; `< 0.50` low → log and monitor only.
- **routing.py:** friction → owner team (table in §3).
- **priority.py:** `impact = revenue_at_risk * log1p(customers_affected) * trend_factor` → `critical | high | normal` via thresholds in config.
- **playbook.py + playbooks.yaml:** for each friction type, the approved customer actions and team actions, each with id, description, channel, `auto_allowed: true|false`, and message template id. This is the **only** source of actions.

### 7.7 LLM assist + guardrails (`llm/`)
- The LLM receives **only** the evidence packet + the decided friction type + the decided playbook action.
- **explain.py** returns strictly:
  ```json
  {"summary": "", "behavior_observed": "", "likely_business_cause": "", "evidence_used": [""]}
  ```
- **messages.py** fills a playbook template with personalized wording (max 300 characters, no new offers).
- **guardrails.py** checks, in order:
  1. Schema (Pydantic parse).
  2. Grounding: every number in the text appears in the packet; every `evidence_used` key exists in the packet.
  3. Consistency: text does not name a different friction type or a different action.
  4. Policy: no discount/refund/compensation promises unless in the playbook action; no emails/phones/IDs; banned-phrase list.
- **fallbacks.py:** deterministic template per friction type, filled from packet fields. Used on any failure, timeout (`LLM_TIMEOUT_SECONDS`, 8 s), or when `LLM_ENABLED=false`.
- **client.py:** one OpenAI-compatible `httpx` client for Groq and OpenRouter; sends `response_format` for JSON where supported; output still goes through every guardrail.
- Prompts live in `llm/prompts/*.md`; keep them short and include the JSON schema.

### 7.8 Agents (`agents/`) — bounded
- **tools.py:** read-only functions only: `drop_off_by_segment`, `compare_converters_vs_abandoners`, `sample_feedback`, `order_status_for_sessions`, `recent_catalog_changes`, `gateway_health`, `courier_health`, `product_details`, `delivery_eta`, `stock_check`. No tool may write to the DB or send anything.
- **investigator.py:** triggered for medium-confidence packets and unexplained anomalies. Uses OpenAI-style tool calling. Max `AGENT_MAX_TOOL_CALLS` (6) tool calls, `AGENT_TIMEOUT_SECONDS` (25 s) timeout. Must return an enriched evidence packet (same schema + `investigation_findings` list with the tool and numbers used). On failure, timeout, or if the provider/model rejects tools, return the original packet unchanged.
- **cs_copilot.py:** gathers the customer's journey, order/payment/refund status and tickets; drafts a reply; always requires human approval; passes guardrails.
- **analyst.py (stretch):** answers business questions using the same read-only tools; responses cite the numbers returned by tools.
- Every tool call is written to the audit log.

### 7.9 Actions (`actions/`)
- **alerts.py:** create alert records: friction type, confidence, priority, owner team, validated explanation, key evidence, recommended team action, status (`open | needs_review | approved | assigned | dismissed | resolved`).
- **workflows.py:** workflow triggers (`approve`, `assign`, `create_ticket`, `dismiss`). Executing an action only simulates it (writes an execution record); nothing external is called in the MVP.
- **recovery.py:** chooses moment (`in_session | post_session | post_purchase`) and channel; applies frequency cap (max 2 messages per user per 24 h) and consent flag; `auto_allowed` actions run automatically, others go to CS for approval; 10% of eligible sessions go to a **holdout** group with no action.

### 7.10 API (FastAPI)
- `POST /events` (tracker ingest), `GET /stream/at-risk` (SSE)
- `GET /overview` (funnel, drop-off, top frictions by revenue at risk, recovery stats)
- `GET /teams/{team}/insights`
- `GET /alerts`, `GET /alerts/{id}`, `POST /alerts/{id}/actions`
- `GET /sessions/{id}` (journey path, features, packet, explanation, recommended action)
- `POST /sessions/{id}/recover`
- `POST /agents/investigate/{packet_id}`, `POST /agents/cs-draft/{alert_id}`, `POST /agents/ask`
- `GET /eval` (detection accuracy vs ground truth, holdout lift)

### 7.11 Dashboard (`frontend/dashboard`)
- **Overview:** funnel with drop-off heatmap, top frictions ranked by revenue at risk, friction health (normal/rising/critical), recovery performance.
- **Team views:** Customer Service, Marketing, Product, Operations — each item: what's happening → why → recommended action → action buttons.
- **Live at-risk sessions:** SSE feed; click → session detail with journey path, SHAP signals, explanation, recommended recovery, "Trigger recovery".
- **Alert detail:** evidence, investigation findings (if any), workflow buttons, audit trail.
- **Evaluation page:** per-friction precision/recall, holdout lift.
- Clean, minimal design; show confidence and "needs review" clearly.

### 7.12 Storefront (`frontend/storefront`)
Small store (home, product, cart, checkout, payment, order) with `tracker.js` sending the event schema to `POST /events`. Include a **demo panel** to force frictions (fail payment, slow delivery ETA, coupon reject, OTP fail, out-of-stock) so we can act out friction live.

---

## 8. Build order (phases)

Work one phase at a time. At the end of each phase: run tests, summarize what was built, list files created, and **stop for review** before starting the next phase.

| Phase | Deliverable | Done when |
|---|---|---|
| 0 | Repo skeleton, requirements, config, `.env.example`, README | Backend starts; `pytest` runs |
| 1 | Synthetic data generator | Tables written; friction rates match config; ground truth present |
| 2 | Ingestion, sessionization, features, joins | Feature table built for all sessions and prefixes; tests pass |
| 3 | Rules + anomaly detection | Rules fire on planted sessions; planted incidents detected |
| 4 | Risk model + friction classifier + SHAP + evaluation | `ml/evaluate.py` reports PR-AUC and per-friction P/R |
| 5 | Text themes | Theme accuracy reported; LLM fallback path works and is optional |
| 6 | Evidence fusion + decision layer + playbooks | Every packet gets type, confidence, gate, team, priority, action; fully deterministic tests |
| 7 | LLM assist + guardrails + fallbacks | Guardrail tests (including deliberately bad LLM outputs) pass; system works with `LLM_ENABLED=false` |
| 8 | Actions, workflows, recovery, holdout, audit, API | All endpoints return data; audit log complete |
| 9 | Dashboard | All pages working against the API |
| 10 | Storefront + live tracker + SSE | Forced friction appears in the dashboard within seconds |
| 11 | Investigation agent + CS copilot (+ analyst stretch) | Medium-confidence cases get enriched; limits enforced; tests pass |
| 12 | Eval page, demo script, README polish | End-to-end demo runs from a clean setup |

---

## 9. Coding conventions

- Python: type hints everywhere, Pydantic models for all cross-module data, small pure functions in detection/decision, no global state except config.
- Config via `backend/app/config.py` (pydantic-settings) reading `.env`. Never hardcode API keys.
- All thresholds (confidence, gating, anomaly z, priority) live in config, not inline.
- Deterministic: set seeds for NumPy, LightGBM, data generation.
- Tests for every decision/guardrail rule. Guardrail tests must include hallucinated numbers, invented discounts, wrong friction type, and malformed JSON.
- When creating or changing a file, show the **complete file contents**, one file at a time.
- Keep functions short and readable; comments only where the logic isn't obvious.

## 10. Environment & commands

The developer uses **Windows with PowerShell**. All commands in docs and instructions must be PowerShell-compatible.

```powershell
# backend setup
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt

# generate data
python -m datagen.generate

# train models
python -m backend.ml.train_risk
python -m backend.ml.train_friction
python -m backend.ml.train_text
python -m backend.ml.evaluate

# list models available for the configured LLM provider
python -m scripts.list_models
python -m scripts.list_models --provider openrouter --filter free

# run API
uvicorn backend.app.main:app --reload

# tests
pytest backend\tests

# frontend
cd frontend\dashboard; npm install; npm run dev
cd frontend\storefront; npm install; npm run dev
```

`.env.example` (committed with empty keys; copy to `.env`, which is gitignored):
```
LLM_ENABLED=true
LLM_PROVIDER=groq
LLM_FALLBACK_PROVIDER=openrouter
GROQ_API_KEY=
OPENROUTER_API_KEY=
LLM_MODEL_FAST=openai/gpt-oss-20b
LLM_MODEL_AGENT=openai/gpt-oss-120b
OPENROUTER_MODEL_FAST=
OPENROUTER_MODEL_AGENT=
LLM_TIMEOUT_SECONDS=8
AGENT_TIMEOUT_SECONDS=25
AGENT_MAX_TOOL_CALLS=6
DATABASE_URL=sqlite:///data/app.db
```
`LLM_MODEL_FAST` / `LLM_MODEL_AGENT` are the Groq model IDs. OpenRouter model IDs are left empty until verified; the fallback provider is skipped while its key or model is empty.

## 11. Do not

- Let the LLM or an agent choose friction types, confidence, routing, priority or actions.
- Let any agent tool write data or send messages.
- Invent offers, discounts or refunds outside `playbooks.yaml`.
- Capture typed input values from forms (cards, passwords, OTPs, addresses).
- Add heavy infrastructure or frameworks beyond §5.
- Skip tests for decision or guardrail logic.
- Start the next phase without stopping for review.
