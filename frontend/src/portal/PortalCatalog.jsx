// Browsing what we sell, and asking for some of it.
//
// There are no prices here, and that is the point rather than an omission: the
// office prices an order when it turns it into an invoice. The screen says so
// plainly instead of leaving a shop to wonder what it will be charged.
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Alert, Badge, Button, Input, Loading, qty } from "../components/Ui";
import useFetch from "../hooks/useFetch";
import portalApi, { portalMessage } from "../services/portalApi";

const AVAILABILITY = {
  available: { label: "متوفر", tone: "green" },
  limited: { label: "كمية محدودة", tone: "amber" },
  unavailable: { label: "غير متوفر", tone: "red" },
};

export default function PortalCatalog() {
  const navigate = useNavigate();
  const catalog = useFetch(() => portalApi.get("/portal/catalog"));
  const [query, setQuery] = useState("");
  const [basket, setBasket] = useState({});
  const [fulfillment, setFulfillment] = useState("delivery");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [reviewing, setReviewing] = useState(false);

  const items = catalog.data ?? [];
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const matching = q ? items.filter((i) => i.name.toLowerCase().includes(q)) : items;
    // 1,060 items will not render usefully on a phone; the search is the way in,
    // so an unfiltered list is capped rather than paginated.
    return matching.slice(0, 60);
  }, [items, query]);

  const lines = Object.entries(basket).filter(([, n]) => Number(n) > 0);

  const setQuantity = (productId, value) =>
    setBasket((current) => ({ ...current, [productId]: value }));

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await portalApi.post("/portal/orders", {
        lines: lines.map(([productId, quantity]) => ({
          product_id: Number(productId),
          quantity: String(quantity),
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
        الأسعار تُحتسب عند تأكيد الطلب وإصدار الفاتورة من المكتب.
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
                <p className="mt-1 flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
                  <Badge tone={AVAILABILITY[item.availability].tone}>
                    {AVAILABILITY[item.availability].label}
                  </Badge>
                  {item.unit}
                </p>
              </div>
              <input
                type="number"
                min="0"
                step="any"
                inputMode="decimal"
                disabled={out}
                value={basket[item.product_id] ?? ""}
                onChange={(e) => setQuantity(item.product_id, e.target.value)}
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

      {items.length > visible.length && !query ? (
        <p className="text-center text-xs text-slate-400">
          يُعرض {visible.length} من {items.length} صنفاً — استخدم البحث للوصول إلى البقية.
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
                  {lines.map(([productId, quantity]) => {
                    const item = items.find((i) => i.product_id === Number(productId));
                    return (
                      <li key={productId} className="flex justify-between gap-2">
                        <span className="truncate">{item?.name}</span>
                        <span className="shrink-0">
                          {qty(quantity)} {item?.unit}
                        </span>
                      </li>
                    );
                  })}
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
