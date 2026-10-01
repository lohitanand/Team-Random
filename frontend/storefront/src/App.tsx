import { useEffect, useMemo, useState } from "react";

// ---------------------------------------------------------------------------------------------
// Demo storefront. Every interaction is sent through public/tracker.js (window.FrictionTracker)
// as a schema event. The demo panel forces frictions so they can be acted out live.
// ---------------------------------------------------------------------------------------------

type Product = {
  product_id: string; name: string; brand: string; category: string; subcategory: string; color: string;
  price: number; mrp: number; rating: number; n_reviews: number; sizes: string[]; stock: Record<string, number>;
  in_stock: boolean; has_size_chart: boolean; missing_attributes: string[]; cod_allowed: boolean;
};
type CartItem = { product: Product; size: string | null };
type View = "home" | "product" | "cart" | "checkout" | "payment" | "done";
type Demo = {
  failPayment: boolean; slowDelivery: boolean; couponReject: boolean; otpFail: boolean;
  outOfStock: boolean; hiddenFees: boolean; missingSizeChart: boolean; jsError: boolean;
};

const T = (window as any).FrictionTracker;
const DASHBOARD = "http://localhost:5173";
const CITIES = [
  { city: "Pune", tier: "tier_1", prefix: "411" },
  { city: "Lucknow", tier: "tier_2", prefix: "226" },
  { city: "Siliguri", tier: "tier_3", prefix: "734" },
];
const DEVICE = /Mobi|Android/i.test(navigator.userAgent) ? "mobile_web" : "desktop";
const inr = (v: number) => `₹${Math.round(v).toLocaleString("en-IN")}`;
const DEMO_OFF: Demo = { failPayment: false, slowDelivery: false, couponReject: false, otpFail: false,
  outOfStock: false, hiddenFees: false, missingSizeChart: false, jsError: false };
const EMOJI: Record<string, string> = { apparel: "👕", footwear: "👟", electronics: "🎧", home_kitchen: "🍳", beauty: "🧴" };

function track(event: string, page: string, metadata: Record<string, unknown> = {}, ids: Record<string, string | null> = {}) {
  return T?.track(event, page, metadata, ids);
}

export default function App() {
  const [products, setProducts] = useState<Product[]>([]);
  const [view, setView] = useState<View>("home");
  const [product, setProduct] = useState<Product | null>(null);
  const [cart, setCart] = useState<CartItem[]>([]);
  const [demo, setDemo] = useState<Demo>(DEMO_OFF);
  const [cityIdx, setCityIdx] = useState(0);
  const [loggedIn, setLoggedIn] = useState(false);
  const [sessionId, setSessionId] = useState<string>(T?.sessionId() ?? "");
  const [lastResponse, setLastResponse] = useState<any>(null);
  const [nudge, setNudge] = useState<any>(null);
  const [orderId, setOrderId] = useState<string | null>(null);
  const city = CITIES[cityIdx];

  useEffect(() => {
    fetch("/api/store/products?limit=24").then((r) => r.json()).then(setProducts).catch(() => setProducts([]));
    const off = T?.onResponse((res: any) => {
      setLastResponse(res);
      if (res?.nudge) setNudge(res.nudge);
    });
    startSession();
    return off;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function startSession() {
    track("page_view", "home", { device: DEVICE, city: city.city, city_tier: city.tier, source: "direct", is_logged_in: false });
    track("rec_impression", "home", { slot: "home_top", n_items: 8, in_stock_items: 8 });
  }

  function newCustomer() {
    const sid = T?.newSession();
    setSessionId(sid);
    setView("home"); setProduct(null); setCart([]); setLoggedIn(false); setNudge(null); setLastResponse(null); setOrderId(null);
    setTimeout(startSession, 50);
  }

  const cartValue = useMemo(() => cart.reduce((s, i) => s + i.product.price, 0), [cart]);

  function openProduct(p: Product, fromRec = false) {
    if (fromRec) track("rec_click", "home", { slot: "home_top", position: products.indexOf(p) + 1 }, { product_id: p.product_id });
    setProduct(p); setView("product");
    track("product_view", "product", { price: p.price, category: p.category, in_stock: p.in_stock && !demo.outOfStock, rating: p.rating },
      { product_id: p.product_id });
  }

  function addToCart(p: Product, size: string | null) {
    const next = [...cart, { product: p, size }];
    setCart(next);
    track("add_to_cart", "product", { size, qty: 1, price: p.price, cart_value: next.reduce((s, i) => s + i.product.price, 0) },
      { product_id: p.product_id });
  }

  function goCart() {
    setView("cart");
    track("cart_view", "cart", { n_items: cart.length, cart_value: cartValue });
  }

  return (
    <div className="min-h-screen pb-24">
      <header className="sticky top-0 z-10 border-b border-stone-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3">
          <button onClick={() => { setView("home"); track("page_view", "home"); }} className="text-xl font-bold tracking-tight">Demo<span className="text-orange-600">Store</span></button>
          <SearchBox products={products} onOpen={openProduct} />
          <button onClick={goCart} className="ml-auto rounded-full bg-stone-900 px-4 py-2 text-sm font-medium text-white">Cart ({cart.length})</button>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-6 lg:pr-80">
        {view === "home" && <Home products={products} onOpen={openProduct} />}
        {view === "product" && product && (
          <ProductPage p={product} demo={demo} city={city} onAdd={(s) => { addToCart(product, s); }} onCart={goCart} />
        )}
        {view === "cart" && (
          <CartPage cart={cart} total={cartValue} onRemove={(i) => {
            const item = cart[i];
            const next = cart.filter((_, j) => j !== i);
            setCart(next);
            track("remove_from_cart", "cart", { cart_value: next.reduce((s, x) => s + x.product.price, 0) }, { product_id: item.product.product_id });
          }} onCheckout={() => { track("checkout_start", "cart", { cart_value: cartValue }); setView("checkout"); }} />
        )}
        {view === "checkout" && (
          <Checkout cartValue={cartValue} demo={demo} loggedIn={loggedIn} setLoggedIn={setLoggedIn}
            onBackToCart={goCart} onPay={() => setView("payment")} />
        )}
        {view === "payment" && (
          <Payment cartValue={cartValue} demo={demo} onSuccess={(oid) => { setOrderId(oid); setCart([]); setView("done"); }} />
        )}
        {view === "done" && orderId && <Done orderId={orderId} />}
      </main>

      {nudge && (
        <div className="fixed bottom-6 left-6 z-30 max-w-sm rounded-xl border border-emerald-200 bg-white p-4 shadow-xl">
          <div className="text-xs font-semibold uppercase tracking-wide text-emerald-700">We noticed a problem</div>
          <p className="mt-1 text-sm">{nudge.message}</p>
          <div className="mt-3 flex gap-2">
            <button className="rounded-lg bg-emerald-600 px-3 py-1.5 text-sm text-white" onClick={() => setNudge(null)}>OK</button>
            <span className="self-center text-xs text-stone-400">{nudge.action_id?.replace(/_/g, " ")}</span>
          </div>
        </div>
      )}

      <DemoPanel demo={demo} setDemo={setDemo} cityIdx={cityIdx} setCityIdx={setCityIdx} sessionId={sessionId}
        lastResponse={lastResponse} onNewCustomer={newCustomer} />
    </div>
  );
}

// --- search -------------------------------------------------------------------------------------

function SearchBox({ products, onOpen }: { products: Product[]; onOpen: (p: Product) => void }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Product[] | null>(null);
  function search() {
    const query = q.trim().toLowerCase();
    if (!query) return;
    const hits = products.filter((p) => `${p.name} ${p.subcategory} ${p.category} ${p.color}`.toLowerCase().includes(query));
    if (hits.length) track("search", "search", { query, results_count: hits.length });
    else track("search_zero_results", "search", { query });
    setResults(hits);
  }
  return (
    <div className="relative flex-1">
      <input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search()}
        placeholder="Search products (try 'earbuds' or 'vegan leather')" className="w-full rounded-full border border-stone-300 bg-stone-50 px-4 py-2 text-sm" />
      {results && (
        <div className="absolute left-0 right-0 top-11 max-h-80 overflow-y-auto rounded-xl border border-stone-200 bg-white p-2 shadow-lg">
          {results.length === 0 && <div className="p-2 text-sm text-stone-500">No results for “{q}”.</div>}
          {results.map((p) => (
            <button key={p.product_id} onClick={() => { setResults(null); onOpen(p); }} className="block w-full rounded-lg p-2 text-left text-sm hover:bg-stone-100">
              {p.name} · {inr(p.price)}
            </button>
          ))}
          <button className="mt-1 w-full text-xs text-stone-400" onClick={() => setResults(null)}>close</button>
        </div>
      )}
    </div>
  );
}

// --- pages --------------------------------------------------------------------------------------

function Home({ products, onOpen }: { products: Product[]; onOpen: (p: Product, fromRec?: boolean) => void }) {
  if (!products.length) return <p className="text-stone-500">Loading products… (is the API running on port 8000?)</p>;
  return (
    <div>
      <h1 className="mb-1 text-2xl font-semibold">Recommended for you</h1>
      <p className="mb-5 text-sm text-stone-500">Festive picks across fashion, footwear, electronics, home and beauty.</p>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-4">
        {products.map((p) => (
          <button key={p.product_id} onClick={() => onOpen(p, true)} className="rounded-xl border border-stone-200 bg-white p-3 text-left transition hover:shadow-md">
            <div className="flex aspect-square items-center justify-center rounded-lg bg-stone-100 text-5xl">{EMOJI[p.category] ?? "🛍"}</div>
            <div className="mt-2 line-clamp-1 text-sm font-medium">{p.name}</div>
            <div className="text-xs text-stone-500">{p.subcategory} · ★ {p.rating}</div>
            <div className="mt-1 text-sm"><b>{inr(p.price)}</b> <span className="text-xs text-stone-400 line-through">{inr(p.mrp)}</span></div>
          </button>
        ))}
      </div>
    </div>
  );
}

function ProductPage({ p, demo, city, onAdd, onCart }: {
  p: Product; demo: Demo; city: typeof CITIES[number]; onAdd: (size: string | null) => void; onCart: () => void;
}) {
  const [size, setSize] = useState<string | null>(null);
  const [panel, setPanel] = useState<string | null>(null);
  const [added, setAdded] = useState(false);
  const [eta, setEta] = useState<number | null>(null);
  const available = (s: string) => !demo.outOfStock && (p.stock[s] ?? 0) > 0;
  const hasChart = p.has_size_chart && !demo.missingSizeChart;
  const inStock = p.in_stock && !demo.outOfStock;

  function pickSize(s: string) {
    if (!available(s)) { track("size_unavailable_click", "product", { size: s }, { product_id: p.product_id }); return; }
    setSize(s);
  }
  function checkPincode() {
    const days = (demo.slowDelivery ? 9 : { tier_1: 2, tier_2: 4, tier_3: 6 }[city.tier] ?? 4);
    setEta(days);
    track("pincode_check", "product", { pincode_prefix: city.prefix, eta_days: days, deliverable: true }, { product_id: p.product_id });
  }

  return (
    <div className="grid gap-8 md:grid-cols-2">
      <div className="flex aspect-square items-center justify-center rounded-2xl bg-white text-9xl shadow-sm">{EMOJI[p.category] ?? "🛍"}</div>
      <div>
        <div className="text-sm text-stone-500">{p.brand}</div>
        <h1 className="text-2xl font-semibold">{p.name}</h1>
        <div className="mt-1 text-sm text-stone-500">★ {p.rating} · {p.n_reviews.toLocaleString("en-IN")} reviews</div>
        <div className="mt-3 text-2xl font-bold">{inr(p.price)} <span className="text-base font-normal text-stone-400 line-through">{inr(p.mrp)}</span></div>

        {p.sizes.length > 0 && (
          <div className="mt-5">
            <div className="mb-2 flex items-center justify-between text-sm font-medium">
              Size
              <button data-track="size_chart" className="text-xs text-orange-600 underline" onClick={() => {
                setPanel("size");
                track("size_chart_open", "product", { available: hasChart }, { product_id: p.product_id });
              }}>Size chart</button>
            </div>
            <div className="flex flex-wrap gap-2">
              {p.sizes.map((s) => (
                <button key={s} data-track={`size_${s}`} onClick={() => pickSize(s)}
                  className={`min-w-12 rounded-lg border px-3 py-2 text-sm ${size === s ? "border-stone-900 bg-stone-900 text-white" : available(s) ? "border-stone-300 bg-white" : "border-dashed border-stone-200 text-stone-300 line-through"}`}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="mt-5 flex gap-2">
          {inStock ? (
            <button data-track="add_to_cart_btn" disabled={p.sizes.length > 0 && !size} onClick={() => { onAdd(size); setAdded(true); }}
              className="flex-1 rounded-xl bg-orange-600 py-3 font-medium text-white disabled:opacity-40">
              {p.sizes.length > 0 && !size ? "Select a size" : "Add to cart"}
            </button>
          ) : (
            <button onClick={() => track("notify_me", "product", { size }, { product_id: p.product_id })}
              className="flex-1 rounded-xl border border-stone-300 bg-white py-3 font-medium">Out of stock - notify me</button>
          )}
          {added && <button onClick={onCart} className="rounded-xl bg-stone-900 px-4 text-sm text-white">Go to cart</button>}
        </div>

        <div className="mt-5 flex items-center gap-2 text-sm">
          <span className="text-stone-500">Deliver to {city.city} ({city.prefix}xxx)</span>
          <button onClick={checkPincode} className="text-orange-600 underline">Check delivery</button>
          {eta != null && <span className={eta > 6 ? "text-red-600" : "text-emerald-700"}>Arrives in {eta} days</span>}
        </div>

        <div className="mt-6 flex gap-4 border-b border-stone-200 text-sm">
          {["specifications", "reviews"].map((t) => (
            <button key={t} onClick={() => {
              setPanel(t);
              if (t === "specifications") track("spec_open", "product", { section: t, missing_fields: p.missing_attributes.length }, { product_id: p.product_id });
              else track("review_open", "product", { review_page: 1, filter: "recent" }, { product_id: p.product_id });
            }} className={`pb-2 capitalize ${panel === t ? "border-b-2 border-stone-900 font-medium" : "text-stone-500"}`}>{t}</button>
          ))}
        </div>
        <div className="mt-3 text-sm text-stone-600">
          {panel === "size" && (hasChart ? <p>S 36-38 · M 38-40 · L 40-42 · XL 42-44 (chest, inches)</p> : <p className="text-red-600">Size chart not available for this product.</p>)}
          {panel === "specifications" && <p>Category: {p.subcategory}. {p.missing_attributes.length ? `Details not provided: ${p.missing_attributes.join(", ")}.` : "All details listed."}</p>}
          {panel === "reviews" && <p>“Good quality, fits as expected.” · “Delivery took a while.” · “Colour slightly different.”</p>}
        </div>
      </div>
    </div>
  );
}

function CartPage({ cart, total, onRemove, onCheckout }: { cart: CartItem[]; total: number; onRemove: (i: number) => void; onCheckout: () => void }) {
  return (
    <div className="max-w-2xl">
      <h1 className="mb-4 text-2xl font-semibold">Your cart</h1>
      {cart.length === 0 && <p className="text-stone-500">Cart is empty.</p>}
      {cart.map((item, i) => (
        <div key={i} className="mb-2 flex items-center justify-between rounded-xl border border-stone-200 bg-white p-3">
          <div><div className="font-medium">{item.product.name}</div><div className="text-xs text-stone-500">{item.size ? `Size ${item.size}` : ""}</div></div>
          <div className="flex items-center gap-4"><b>{inr(item.product.price)}</b><button className="text-xs text-stone-400" onClick={() => onRemove(i)}>remove</button></div>
        </div>
      ))}
      {cart.length > 0 && (
        <div className="mt-4 flex items-center justify-between">
          <div>Subtotal <b>{inr(total)}</b></div>
          <button data-track="checkout_btn" onClick={onCheckout} className="rounded-xl bg-orange-600 px-6 py-3 font-medium text-white">Checkout</button>
        </div>
      )}
    </div>
  );
}

function Checkout({ cartValue, demo, loggedIn, setLoggedIn, onBackToCart, onPay }: {
  cartValue: number; demo: Demo; loggedIn: boolean; setLoggedIn: (v: boolean) => void; onBackToCart: () => void; onPay: () => void;
}) {
  const [step, setStep] = useState<"login" | "delivery" | "summary">(loggedIn ? "delivery" : "login");
  const [otpSent, setOtpSent] = useState(false);
  const [resends, setResends] = useState(0);
  const [otpFails, setOtpFails] = useState(0);
  const [otpError, setOtpError] = useState<string | null>(null);
  const [coupon, setCoupon] = useState("");
  const [couponMsg, setCouponMsg] = useState<string | null>(null);
  const [couponTries, setCouponTries] = useState(0);
  const [discount, setDiscount] = useState(0);
  const slow = demo.slowDelivery;
  const shipping = slow ? 99 : cartValue >= 499 ? 0 : 49;
  const handling = demo.hiddenFees ? 129 : 0;
  const total = cartValue + shipping + 9 + handling - discount;

  useEffect(() => {
    if (step === "login") track("login_wall", "checkout_login", { guest_checkout: false });
    if (step === "delivery") {
      track("page_view", "checkout_address");
      track("delivery_info_view", "checkout_delivery", {
        eta_days: slow ? 9 : 3, delivery_fee: shipping, courier: slow ? "CourierX" : "CourierA",
        express_available: !slow, express_fee: 99, ...(slow ? { fee_first_shown: true } : {}),
      });
    }
    if (step === "summary") showTotal(discount);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);

  function showTotal(disc: number) {
    const t = cartValue + shipping + 9 + handling - disc;
    track("total_shown", "checkout_summary", {
      subtotal: cartValue, shipping, platform_fee: 9, cod_fee: 0, discount: disc, total: t,
      delta_pct: Math.round(((t - cartValue) / Math.max(cartValue, 1)) * 1000) / 10, ...(handling ? { handling_fee: handling } : {}),
    });
  }
  function applyCoupon() {
    const code = coupon.trim().toUpperCase() || "SAVE10";
    const attempt = couponTries + 1;
    setCouponTries(attempt);
    track("coupon_apply", "checkout_summary", { code, attempt });
    if (demo.couponReject) {
      track("coupon_failed", "checkout_summary", { code, reason: "expired" });
      setCouponMsg(`Coupon ${code} has expired.`);
    } else {
      track("coupon_applied", "checkout_summary", { code, discount: 100 });
      setDiscount(100); setCouponMsg(`${code} applied.`); showTotal(100);
    }
  }
  function verifyOtp() {
    if (demo.otpFail) {
      const n = otpFails + 1;
      setOtpFails(n);
      track("otp_failed", "checkout_login", { reason: "invalid", attempt: n });
      setOtpError("Invalid OTP. Please try again.");
      return;
    }
    track("login_success", "checkout_login", { method: "otp" });
    setLoggedIn(true); setStep("delivery");
  }

  const box = "rounded-2xl border border-stone-200 bg-white p-6";
  return (
    <div className="max-w-xl space-y-4">
      <h1 className="text-2xl font-semibold">Checkout</h1>
      {step === "login" && (
        <div className={box}>
          <h2 className="font-medium">Log in to continue</h2>
          <p className="text-sm text-stone-500">We'll send a one-time password to your phone.</p>
          {/* The phone/OTP fields are never read by the tracker - only that an OTP was sent/failed. */}
          <input className="mt-3 w-full rounded-lg border border-stone-300 px-3 py-2" placeholder="Mobile number" autoComplete="off" />
          {!otpSent ? (
            <button className="mt-3 w-full rounded-lg bg-stone-900 py-2 text-white" onClick={() => { setOtpSent(true); track("otp_sent", "checkout_login", { channel: "sms" }); }}>Send OTP</button>
          ) : (
            <>
              <input className="mt-3 w-full rounded-lg border border-stone-300 px-3 py-2" placeholder="Enter OTP" autoComplete="one-time-code" />
              {otpError && <p className="mt-1 text-sm text-red-600">{otpError}</p>}
              <div className="mt-3 flex gap-2">
                <button className="flex-1 rounded-lg bg-stone-900 py-2 text-white" onClick={verifyOtp}>Verify</button>
                <button data-track="otp_resend" className="rounded-lg border border-stone-300 px-3 text-sm" onClick={() => {
                  const n = resends + 1; setResends(n); track("otp_resend", "checkout_login", { channel: "sms", attempt: n + 1 });
                }}>Resend OTP</button>
              </div>
            </>
          )}
        </div>
      )}
      {step === "delivery" && (
        <div className={box}>
          <h2 className="font-medium">Delivery</h2>
          <div className={`mt-2 rounded-lg p-3 text-sm ${slow ? "bg-red-50 text-red-800" : "bg-emerald-50 text-emerald-800"}`}>
            Estimated delivery in <b>{slow ? 9 : 3} days</b> via {slow ? "CourierX" : "CourierA"} · delivery fee {shipping ? inr(shipping) : "free"}
          </div>
          <button className="mt-4 w-full rounded-lg bg-stone-900 py-2 text-white" onClick={() => setStep("summary")}>Continue</button>
        </div>
      )}
      {step === "summary" && (
        <div className={box}>
          <h2 className="font-medium">Order summary</h2>
          <div className="mt-3 space-y-1 text-sm">
            <Row k="Subtotal" v={inr(cartValue)} /><Row k="Delivery" v={shipping ? inr(shipping) : "Free"} />
            <Row k="Platform fee" v={inr(9)} />{handling > 0 && <Row k="Handling fee" v={inr(handling)} />}
            {discount > 0 && <Row k="Coupon" v={`- ${inr(discount)}`} />}
            <div className="border-t border-stone-200 pt-2"><Row k={<b>Total</b>} v={<b>{inr(total)}</b>} /></div>
          </div>
          <div className="mt-4 flex gap-2">
            <input value={coupon} onChange={(e) => setCoupon(e.target.value)} placeholder="Coupon code (e.g. SAVE10)" className="flex-1 rounded-lg border border-stone-300 px-3 py-2 text-sm" />
            <button data-track="coupon_apply" className="rounded-lg border border-stone-300 px-3 text-sm" onClick={applyCoupon}>Apply</button>
          </div>
          {couponMsg && <p className={`mt-1 text-sm ${demo.couponReject ? "text-red-600" : "text-emerald-700"}`}>{couponMsg}</p>}
          <div className="mt-4 flex gap-2">
            <button className="rounded-lg border border-stone-300 px-4 py-2 text-sm" onClick={onBackToCart}>Back to cart</button>
            <button data-track="continue_btn" className="flex-1 rounded-lg bg-orange-600 py-2 font-medium text-white" onClick={onPay}>Continue to payment</button>
          </div>
        </div>
      )}
    </div>
  );
}

function Payment({ cartValue, demo, onSuccess }: { cartValue: number; demo: Demo; onSuccess: (orderId: string) => void }) {
  const [method, setMethod] = useState("UPI");
  const [attempt, setAttempt] = useState(0);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const amount = cartValue + 9 + (demo.slowDelivery ? 99 : cartValue >= 499 ? 0 : 49) + (demo.hiddenFees ? 129 : 0);

  useEffect(() => {
    track("page_view", "checkout_payment");
    if (demo.jsError) track("js_error", "checkout_payment", { component: "payment_widget", message: "TypeError: Cannot read properties of undefined (reading 'amount')" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function pay() {
    const n = attempt + 1;
    setAttempt(n); setBusy(true); setStatus("Processing…");
    const gateway = method === "COD" ? null : demo.failPayment ? "B" : "A";
    track("payment_attempt", "checkout_payment", { method, gateway, amount, attempt: n });
    setTimeout(() => {
      setBusy(false);
      if (demo.failPayment && method !== "COD") {
        track("payment_failed", "checkout_payment", { method, gateway, error: method === "UPI" ? "timeout" : "bank_timeout", attempt: n });
        setStatus(`Payment failed (${method === "UPI" ? "UPI timeout" : "bank timeout"}). Please try again.`);
        return;
      }
      const orderId = `o_live_${Date.now().toString(36)}`;
      track("payment_success", "checkout_payment", { method, gateway, amount });
      track("order_placed", "checkout_payment", { order_value: amount, n_items: 1, payment_method: method }, { order_id: orderId });
      track("page_view", "order_confirmation", {}, { order_id: orderId });
      onSuccess(orderId);
    }, 1200);
  }

  return (
    <div className="max-w-xl space-y-4">
      <h1 className="text-2xl font-semibold">Payment</h1>
      <div className="rounded-2xl border border-stone-200 bg-white p-6">
        <div className="text-sm text-stone-500">Amount to pay</div>
        <div className="text-2xl font-bold">{inr(amount)}</div>
        <div className="mt-4 grid grid-cols-2 gap-2">
          {["UPI", "card", "netbanking", "wallet", "COD"].map((m) => (
            <button key={m} onClick={() => setMethod(m)} className={`rounded-lg border px-3 py-2 text-sm ${method === m ? "border-stone-900 bg-stone-900 text-white" : "border-stone-300"}`}>
              {m === "COD" ? "Cash on delivery" : m.toUpperCase() === "UPI" ? "UPI" : m[0].toUpperCase() + m.slice(1)}
            </button>
          ))}
        </div>
        {demo.jsError && <p className="mt-3 text-sm text-red-600">Something went wrong loading the payment widget.</p>}
        <button data-track="pay_btn" disabled={busy} onClick={pay} className="mt-4 w-full rounded-xl bg-orange-600 py-3 font-medium text-white disabled:opacity-50">
          Pay {inr(amount)}
        </button>
        {status && <p className={`mt-2 text-sm ${status.startsWith("Payment failed") ? "text-red-600" : "text-stone-500"}`}>{status}</p>}
      </div>
    </div>
  );
}

function Done({ orderId }: { orderId: string }) {
  const [tracked, setTracked] = useState(0);
  return (
    <div className="max-w-xl rounded-2xl border border-emerald-200 bg-white p-6">
      <div className="text-3xl">🎉</div>
      <h1 className="mt-2 text-2xl font-semibold">Order placed</h1>
      <p className="text-sm text-stone-500">Order {orderId}</p>
      <button className="mt-4 rounded-lg border border-stone-300 px-4 py-2 text-sm" onClick={() => {
        setTracked(tracked + 1);
        track("tracking_view", "order_tracking", { status: "in_transit", days_to_promise: 3 }, { order_id: orderId });
      }}>Track order {tracked > 0 && `(${tracked})`}</button>
    </div>
  );
}

function Row({ k, v }: { k: React.ReactNode; v: React.ReactNode }) {
  return <div className="flex justify-between"><span className="text-stone-600">{k}</span><span>{v}</span></div>;
}

// --- demo panel -----------------------------------------------------------------------------------

const TOGGLES: { key: keyof Demo; label: string; hint: string }[] = [
  { key: "failPayment", label: "Fail payment", hint: "UPI timeouts on gateway B" },
  { key: "slowDelivery", label: "Slow delivery ETA", hint: "9-day ETA + late fee (CourierX)" },
  { key: "couponReject", label: "Reject coupon", hint: "every coupon 'expired'" },
  { key: "otpFail", label: "OTP fails", hint: "verification always invalid" },
  { key: "outOfStock", label: "Out of stock", hint: "all sizes unavailable" },
  { key: "hiddenFees", label: "Hidden fees", hint: "₹129 handling fee at checkout" },
  { key: "missingSizeChart", label: "Missing size chart", hint: "size chart not available" },
  { key: "jsError", label: "JS error on payment", hint: "payment widget error" },
];

function DemoPanel({ demo, setDemo, cityIdx, setCityIdx, sessionId, lastResponse, onNewCustomer }: {
  demo: Demo; setDemo: (d: Demo) => void; cityIdx: number; setCityIdx: (i: number) => void; sessionId: string;
  lastResponse: any; onNewCustomer: () => void;
}) {
  const [open, setOpen] = useState(true);
  return (
    <aside className={`fixed right-4 top-20 z-20 w-72 rounded-2xl border border-indigo-200 bg-white shadow-xl ${open ? "" : "h-11 overflow-hidden"}`}>
      <button onClick={() => setOpen(!open)} className="flex w-full items-center justify-between rounded-t-2xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white">
        Demo panel - force friction <span>{open ? "−" : "+"}</span>
      </button>
      <div className="space-y-3 p-4 text-sm">
        {TOGGLES.map((t) => (
          <label key={t.key} className="flex cursor-pointer items-start gap-2">
            <input type="checkbox" className="mt-1" checked={demo[t.key]} onChange={(e) => setDemo({ ...demo, [t.key]: e.target.checked })} />
            <span><span className="font-medium">{t.label}</span><br /><span className="text-xs text-stone-500">{t.hint}</span></span>
          </label>
        ))}
        <label className="block text-xs text-stone-500">Customer city
          <select value={cityIdx} onChange={(e) => setCityIdx(Number(e.target.value))} className="mt-1 w-full rounded-lg border border-stone-300 px-2 py-1 text-sm text-stone-900">
            {CITIES.map((c, i) => <option key={c.city} value={i}>{c.city} ({c.tier.replace("_", " ")})</option>)}
          </select>
        </label>
        <div className="rounded-lg bg-stone-50 p-2 text-xs">
          <div>Session <span className="font-mono">{sessionId}</span></div>
          {lastResponse && (
            <div className="mt-1">
              Server: risk <b>{Math.round((lastResponse.risk_score ?? 0) * 100)}%</b>
              {lastResponse.at_risk ? <> · <b>{lastResponse.friction_type?.replace(/_/g, " ")}</b> · {lastResponse.gate} ({lastResponse.confidence})</> : " · not at risk"}
            </div>
          )}
          <a className="mt-1 block text-indigo-600 underline" href={`${DASHBOARD}/#/sessions/${sessionId}`} target="_blank" rel="noreferrer">Open in dashboard →</a>
        </div>
        <button onClick={onNewCustomer} className="w-full rounded-lg border border-indigo-300 py-2 text-sm font-medium text-indigo-700 hover:bg-indigo-50">New customer session</button>
      </div>
    </aside>
  );
}
