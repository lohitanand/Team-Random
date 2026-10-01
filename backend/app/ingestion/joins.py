"""Join transactions and service interactions onto sessions by shared IDs (CLAUDE.md §7.3)."""
from __future__ import annotations

import pandas as pd

JOIN_COLUMNS = [
    "n_payment_records", "failed_debited_payments", "n_gateways",
    "n_tickets", "n_reviews", "min_review_rating",
    "order_delay_days", "order_is_delayed", "order_refund_pending", "order_return_requested",
]


def join_session_data(
    sessions: pd.DataFrame,
    payments: pd.DataFrame,
    orders: pd.DataFrame,
    tickets: pd.DataFrame,
    reviews: pd.DataFrame,
) -> pd.DataFrame:
    """One row per session with transaction/order/feedback aggregates (0 when nothing joins)."""
    out = sessions[["session_id", "order_id"]].copy()

    pay = payments.assign(
        failed_debited=(payments["status"] == "failed") & payments["amount_debited"].astype(bool)
    ).groupby("session_id").agg(
        n_payment_records=("payment_id", "size"),
        failed_debited_payments=("failed_debited", "sum"),
        n_gateways=("gateway", "nunique"),
    )
    out = out.join(pay, on="session_id")

    out = out.join(tickets.groupby("session_id").size().rename("n_tickets"), on="session_id")
    rev = reviews.dropna(subset=["session_id"]).groupby("session_id").agg(
        n_reviews=("review_id", "size"), min_review_rating=("rating", "min"))
    out = out.join(rev, on="session_id")

    lookup = orders.set_index("order_id")[["delay_days", "status", "refund_status"]].to_dict("index")
    joined = pd.DataFrame([lookup.get(oid, {}) if isinstance(oid, str) else {} for oid in out["order_id"]],
                          index=out.index, columns=["delay_days", "status", "refund_status"])
    out["order_delay_days"] = joined["delay_days"]
    out["order_is_delayed"] = joined["status"].isin(["delayed"]) | (joined["delay_days"].fillna(0) > 0)
    out["order_refund_pending"] = joined["refund_status"].eq("pending")
    out["order_return_requested"] = joined["status"].isin(["return_requested", "returned"])

    out = out.drop(columns=["order_id"])
    for col in JOIN_COLUMNS:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype(float)
    return out


def session_texts(tickets: pd.DataFrame, chats: pd.DataFrame, reviews: pd.DataFrame) -> pd.DataFrame:
    """All customer text with its join keys: source, text_id, session_id, user_id, order_id, product_id."""
    frames = [
        tickets.assign(source="ticket", text_id=tickets["ticket_id"], ts=tickets["created_at"])[
            ["source", "text_id", "session_id", "user_id", "order_id", "product_id", "ts", "text",
             "language", "theme_label"]],
        chats.assign(source="chat", text_id=chats["chat_id"], ts=chats["started_at"], text=chats["customer_text"],
                     order_id=None, product_id=None)[
            ["source", "text_id", "session_id", "user_id", "order_id", "product_id", "ts", "text",
             "language", "theme_label"]],
        reviews.assign(source="review", text_id=reviews["review_id"], ts=reviews["created_at"])[
            ["source", "text_id", "session_id", "user_id", "order_id", "product_id", "ts", "text",
             "language", "theme_label"]],
    ]
    out = pd.concat(frames, ignore_index=True)
    for col in ("session_id", "order_id", "product_id"):
        out[col] = out[col].astype(object).where(out[col].notna(), None)
    return out
