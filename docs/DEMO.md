# Pitch demo script (~6 minutes)

Before starting: API, dashboard (http://localhost:5173) and storefront (http://localhost:5174) running.
Open the dashboard on **Live at-risk** and the storefront side by side.

## 1. The problem (30 s) - Dashboard → Overview
"Businesses know *where* customers drop off, not *why* - evidence is split across teams."
- KPIs: conversion, cart abandonment, revenue at risk.
- Drop-off heatmap by device and step (journey risk indicators).
- Top frictions ranked by revenue at risk, with health (normal / rising / critical).

## 2. Live friction (90 s) - Storefront
1. Demo panel: tick **Fail payment**.
2. Open a product → pick a size → Add to cart → Checkout → (login: Send OTP → Verify) → Continue → Continue to payment.
3. Click **Pay** twice (both fail with UPI timeout on gateway B).
4. Dashboard **Live at-risk**: the session appears within seconds - *Payment failures*, risk score, confidence.
5. Demo panel → **New customer session**, repeat. The second customer: the investigation agent checks gateway B
   health (read-only), finds other failing customers → confidence rises to **high** → the storefront shows the
   in-session nudge *"Payment by UPI is not going through right now. You can pay another way - your cart is saved."*

Other frictions to act out: Slow delivery ETA, Reject coupon (apply twice), OTP fails (Verify twice / Resend twice),
Out of stock (click sizes), Hidden fees (reach the summary, then leave), JS error on payment.

## 3. Root cause (60 s) - click the live session
Journey path, SHAP signals, rule flags, confidence breakdown (rules 0.30 + model 0.30 + text 0.20 + aggregate 0.20),
explanation linking behaviour to the business cause, recommended recovery → **Trigger recovery**.

## 4. Team alert (60 s) - Alerts → filter *Incidents*
Open the Gateway B or CourierX incident: evidence (observed vs baseline, multiplier), recommended team action,
**Approve / Assign / Create ticket / Dismiss**, **Run investigation agent**, **Draft CS reply** (human approves),
audit trail of every step.

## 5. Team views (30 s)
Operations / Marketing / Product / CS: what's happening → why → recommended action → act.

## 6. Impact (45 s) - Evaluation + Ask the analyst
Cause accuracy ~96%, 99% of friction sessions detected, 0.19% false alerts, 3/3 incidents found, recovery lift vs
10% holdout (simulated). Ask: "Which payment gateway is failing?"

## Key lines
- "Rules catch known friction; ML predicts risk and discovers patterns; text understanding reads thousands of tickets in English and Hinglish."
- "Our system decides and humans approve. The LLM only explains, and every word is checked against the evidence - numbers, friction type, actions, offers, personal data - before anyone sees it."
- "Medium confidence never acts automatically - it goes to a person as *needs review*."
- "We fix the specific reason the customer left, at the right moment, and measure it against a holdout."
