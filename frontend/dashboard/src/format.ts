export const FRICTION_LABELS: Record<string, string> = {
  unclear_product_info: "Unclear product info",
  delivery_uncertainty: "Delivery uncertainty",
  payment_failure: "Payment failures",
  poor_recommendations: "Poor recommendations",
  post_purchase_concern: "Post-purchase concerns",
  price_shock: "Hidden costs / price shock",
  coupon_failure: "Coupon failure",
  login_otp_issue: "Login / OTP issues",
  out_of_stock: "Out of stock",
  technical_glitch: "Technical glitches",
};

export const FRICTION_COLORS: Record<string, string> = {
  unclear_product_info: "#6366f1",
  delivery_uncertainty: "#f59e0b",
  payment_failure: "#ef4444",
  poor_recommendations: "#14b8a6",
  post_purchase_concern: "#8b5cf6",
  price_shock: "#ec4899",
  coupon_failure: "#f97316",
  login_otp_issue: "#0ea5e9",
  out_of_stock: "#84cc16",
  technical_glitch: "#64748b",
};

export const TEAMS: { key: string; label: string }[] = [
  { key: "customer_service", label: "Customer Service" },
  { key: "marketing", label: "Marketing" },
  { key: "product", label: "Product" },
  { key: "operations", label: "Operations" },
];

export const TEAM_LABELS: Record<string, string> = {
  customer_service: "Customer Service",
  marketing: "Marketing",
  product: "Product",
  operations: "Operations",
  operations_tech: "Operations / Tech",
};

export const friction = (key?: string | null) => (key ? FRICTION_LABELS[key] ?? key : "-");
export const humanize = (s?: string | null) => (s ? s.replace(/_/g, " ") : "-");

export function money(v?: number | null): string {
  if (v == null) return "-";
  if (v >= 1e7) return `₹${(v / 1e7).toFixed(2)} Cr`;
  if (v >= 1e5) return `₹${(v / 1e5).toFixed(2)} L`;
  return `₹${Math.round(v).toLocaleString("en-IN")}`;
}

export const pct = (v?: number | null, digits = 1) => (v == null ? "-" : `${(v * 100).toFixed(digits)}%`);
export const num = (v?: number | null) => (v == null ? "-" : v.toLocaleString("en-IN"));

export function time(v?: string | null): string {
  if (!v) return "-";
  const d = new Date(v);
  return d.toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function parseRoute(hash: string): { page: string; id?: string; query: URLSearchParams } {
  const [path, qs] = hash.replace(/^#\/?/, "").split("?");
  const parts = path.split("/").filter(Boolean);
  return { page: parts[0] ?? "overview", id: parts[1] ? decodeURIComponent(parts[1]) : undefined, query: new URLSearchParams(qs ?? "") };
}
