// Browsing what we sell, and asking for some of it.
//
// There are no prices here, and that is the point rather than an omission: the
// office prices an order when it turns it into an invoice. The screen says so
// plainly instead of leaving a shop to wonder what it will be charged.
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Alert, Badge, Button, Input, Loading, money, qty } from "../components/Ui";
import useFetch from "../hooks/useFetch";
import portalApi, { portalMessage } from "../services/portalApi";

const AVAILABILITY = {
  available: { label: "متوفر", tone: "green" },
  limited: { label: "كمية محدودة", tone: "amber" },
  unavailable: { label: "غير متوفر", tone: "red" },
};

export default function PortalCatalog() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  // Debounced, because the search now goes to the server: a request per keystroke
  // would be worse for a shop on mobile data than the oversized list this replaced.
  const [term, setTerm] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setTerm(query.trim()), 300);
    return () => clearTimeout(timer);
  }, [query]);

  const catalog = useFetch(
    () => portalApi.get("/portal/catalog", { params: term ? { search: term } : {} }),
    [term]
  );
  const [basket, setBasket] = useState({});
  const [fulfillment, setFulfillment] = useState("delivery");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [reviewing, setReviewing] = useState(false);

  // Already searched and capped by the server — see PortalOrderService.catalog.
  const items = catalog.data ?? [];
  const visible = items;

  // Keyed by product id, holding the name and unit alongside the quantity. Looking
  // those up in `items` broke the moment search became server-side: an item added
  // before a second search is no longer in the current results, and the review panel
  // would show a blank line for something the customer is about to order.
  const lines = Object.entries(basket).filter(([, line]) => Number(line.quantity) > 0);

  const setQuantity = (item, value) =>
    setBasket((current) => ({
      ...current,
      [item.product_id]: { quantity: value, name: item.name, unit: item.unit },
    }));

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await portalApi.post("/portal/orders", {
        lines: lines.map(([productId, line]) => ({
          product_id: Number(productId),
          quantity: String(line.quantity),
        })),
        fulfillment,
        notes: notes.trim() || null,
      });
      setBasket({});
      setNotes("");
      setReviewing(false);
      navigate("/portal/orders");
    } catch (err) {
      setError(portalMessage(err));
      setBusy(false);
    }
  };

  if (catalog.loading) return <Loading />;

  return (
    <div className="space-y-4">
      <Input
        label="ابحث عن صنف"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="اسم الصنف…"
      />
      <p className="text-xs text-slate-500 dark:text-slate-400">
        الأسعار تُحتسب عند تأكيد الطلب وإصدار الفاتورة من المكتب — ما عدا الأصناف
        المعروضة بخصم، فسعرها المعروض هو المحتسب.
      </p>

      <Alert>{catalog.error ?? error}</Alert>

      <ul className="space-y-2">
        {visible.map((item) => {
          const out = item.availability === "unavailable";
          return (
            <li
              key={item.product_id}
              className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-3 dark:border-slate-700 dark:bg-slate-800"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-bold text-slate-800 dark:text-slate-100">
                  {item.name}
                </p>
                <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
                  <Badge tone={AVAILABILITY[item.availability].tone}>
                    {AVAILABILITY[item.availability].label}
                  </Badge>
                  {item.unit}
                  {item.discount_percent ? (
                    <Badge tone="red">خصم {qty(item.discount_percent)}%</Badge>
                  ) : null}
                </p>
                {/* Only discounted lines carry a price, and it is this customer's own
                    — their tier price, and that price marked down. It is also what
                    the invoice will charge, so it is written as a fact rather than a
                    guide. */}
                {item.price_now ? (
                  <p className="mt-1 flex items-baseline gap-2 text-sm">
                    <span className="text-slate-400 line-through dark:text-slate-500">
                      {money(item.price_before)}
                    </span>
                    <span className="font-bold text-emerald-700 dark:text-emerald-400">
                      {money(item.price_now)}
                    </span>
                    {item.offer_ends_on ? (
                      <span className="text-[11px] text-slate-500 dark:text-slate-400">
                        حتى {item.offer_ends_on}
                      </span>
                    ) : null}
                  </p>
                ) : null}
                {item.offer_note ? (
                  <p className="text-[11px] text-slate-500 dark:text-slate-400">
                    {item.offer_note}
                  </p>
                ) : null}
              </div>
              <input
                type="number"
                min="0"
                step="any"
                inputMode="decimal"
                disabled={out}
                value={basket[item.product_id]?.quantity ?? ""}
                onChange={(e) => setQuantity(item, e.target.value)}
                placeholder="0"
                className="w-20 shrink-0 rounded-lg border border-slate-300 px-2 py-2 text-center text-sm disabled:bg-slate-100 disabled:text-slate-400 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100 dark:disabled:bg-slate-800"
              />
            </li>
          );
        })}
        {!visible.length ? (
          <li className="py-8 text-center text-sm text-slate-400">
            لا توجد أصناف مطابقة.
          </li>
        ) : null}
      </ul>

      {!term && items.length >= 60 ? (
        <p className="text-center text-xs text-slate-400">
          هذه أوائل الأصناف — استخدم البحث للوصول إلى بقية القائمة.
        </p>
      ) : null}

      {/* Sits above the tab bar so the basket is never out of reach mid-scroll. */}
      {lines.length ? (
        <div className="fixed inset-x-0 bottom-16 z-10 px-4">
          <div className="mx-auto max-w-3xl rounded-xl bg-emerald-600 p-3 shadow-lg">
            {reviewing ? (
              <div className="space-y-3">
                <p className="text-sm font-bold text-white">
                  مراجعة الطلب ({lines.length})
                </p>
                <ul className="max-h-40 space-y-1 overflow-y-auto text-sm text-emerald-50">
                  {lines.map(([productId, line]) => (
                    <li key={productId} className="flex justify-between gap-2">
                      <span className="truncate">{line.name}</span>
                      <span className="shrink-0">
                        {qty(line.quantity)} {line.unit}
                      </span>
                    </li>
                  ))}
                </ul>
                <div className="flex gap-2">
                  {["delivery", "pickup"].map((option) => (
                    <button
                      key={option}
                      onClick={() => setFulfillment(option)}
                      className={`flex-1 rounded-lg px-3 py-2 text-xs font-bold transition ${
                        fulfillment === option
                          ? "bg-white text-emerald-700"
                          : "bg-emerald-700 text-emerald-50"
                      }`}
                    >
                      {option === "delivery" ? "توصيل" : "استلام من المستودع"}
                    </button>
                  ))}
                </div>
                <input
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  maxLength={300}
                  placeholder="ملاحظة للمكتب (اختياري)"
                  className="w-full rounded-lg px-3 py-2 text-sm text-slate-800"
                />
                <div className="flex gap-2">
                  <Button
                    variant="secondary"
                    className="flex-1"
                    onClick={() => setReviewing(false)}
                  >
                    رجوع
                  </Button>
                  {/* Inverted rather than the usual primary: this panel is already
                      emerald, so the standard green button lost its edges against
                      it and the main action read as plain text beside a solid
                      "back". White on green is the strongest pairing here. */}
                  <button
                    onClick={submit}
                    disabled={busy}
                    className="flex-1 rounded-lg bg-white px-4 py-2 text-sm font-bold text-emerald-700 shadow-sm transition hover:bg-emerald-50 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {busy ? "جارٍ الإرسال…" : "إرسال الطلب"}
                  </button>
                </div>
              </div>
            ) : (
              <button
                onClick={() => setReviewing(true)}
                className="flex w-full items-center justify-between text-sm font-bold text-white"
              >
                <span>مراجعة الطلب</span>
                <span>{lines.length} صنف</span>
              </button>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}
