// What is about to expire, what of it will not sell, and who to ring about it.
//
// The near-expiry alert already existed and was a list of facts. This is the list of
// actions: only the part that will *not* clear at the current rate, ranked by what
// doing nothing costs per day, with the shops that actually buy each product.
//
// The reasoning is on screen rather than behind the ranking. A manager who cannot
// see why a line is at the top will not work the list in order, and the sales rate
// is an estimate that deserves to be argued with.
import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  CancelButton,
  Card,
  Input,
  Loading,
  Modal,
  Select,
  Stat,
  Table,
  money,
  qty,
} from "../components/Ui";
import { useAuth } from "../context/AuthContext";
import useFetch from "../hooks/useFetch";
import api, { apiMessage } from "../services/api";

const HORIZONS = [
  { value: 30, label: "خلال ٣٠ يوماً" },
  { value: 60, label: "خلال ٦٠ يوماً" },
  { value: 90, label: "خلال ٩٠ يوماً" },
];

// Days left is the thing the eye should catch first, so it carries the colour.
const urgencyTone = (days) => (days <= 14 ? "red" : days <= 30 ? "amber" : "slate");

function Buyers({ item, canOffer, onOffer, onEndOffer }) {
  const actions = canOffer ? (
    <div className="flex flex-wrap gap-2 pt-1">
      {item.active_offer_id ? (
        <Button variant="danger" onClick={() => onEndOffer(item)}>
          إيقاف الخصم ({qty(item.active_offer_percent)}%)
        </Button>
      ) : (
        <Button onClick={() => onOffer(item)}>إنشاء عرض خصم</Button>
      )}
    </div>
  ) : null;

  if (!item.suggested_buyers.length) {
    return (
      <div className="space-y-2">
        <p className="text-sm text-slate-500 dark:text-slate-400">
          لا يوجد عملاء سبق أن اشتروا هذا الصنف — يحتاج تخفيضاً أو إعادة للمورّد.
        </p>
        {actions}
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <p className="text-sm font-bold text-slate-700 dark:text-slate-200">
        عملاء سبق أن اشتروا هذا الصنف:
      </p>
      <ul className="space-y-1">
        {item.suggested_buyers.map((buyer) => (
          <li
            key={buyer.customer_id}
            className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-slate-50 px-3 py-2 text-sm dark:bg-slate-800/60"
          >
            <span className="font-medium text-slate-700 dark:text-slate-200">
              {buyer.customer_name}
              {buyer.phone ? (
                // A real separator, not just a margin: copied or read aloud, a CSS
                // gap leaves the name and number fused into one string.
                <span className="text-xs text-slate-500 dark:text-slate-400">
                  {" · "}
                  {buyer.phone}
                </span>
              ) : null}
            </span>
            <span className="text-xs text-slate-500 dark:text-slate-400">
              اشترى {qty(buyer.total_quantity)} · آخر مرة {buyer.last_bought}
            </span>
          </li>
        ))}
      </ul>
      {/* The estimate that drove the ranking, shown so it can be disputed. */}
      <p className="text-xs text-slate-500 dark:text-slate-400">
        يُباع بمعدل {qty(item.daily_sales_rate)} {item.unit}/يوم — يُتوقع بيع{" "}
        {qty(item.projected_sales)} قبل الانتهاء، ويتبقى {qty(item.surplus_quantity)}.
        المستودعات: {item.warehouses.join("، ")}.
      </p>
      {actions}
    </div>
  );
}


// Setting the markdown where the decision is made, with the margin in view.
//
// The preview is computed here from figures the row already carries rather than
// fetched: a discount typed with no idea what it does to the margin is exactly how a
// line ends up sold below cost by accident. Below cost is still allowed — for food
// near its date, recovering some of the cost beats recovering none — but it says so
// before you commit, not after.
function OfferDialog({ item, onClose, onDone }) {
  const today = new Date().toISOString().slice(0, 10);
  // Default the window to the day the first batch expires: past that the goods
  // cannot be sold at all, so a longer offer would be a promise about nothing.
  const until = new Date(item.earliest_expiry).toISOString().slice(0, 10);

  const [percent, setPercent] = useState("20");
  const [endsOn, setEndsOn] = useState(until);
  const [note, setNote] = useState("قرب انتهاء الصلاحية");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const pct = Number(percent) || 0;
  const before = Number(item.wholesale_price ?? 0);
  const after = before * (1 - pct / 100);
  const cost = item.unit_cost === null ? null : Number(item.unit_cost);
  const belowCost = cost !== null && after < cost;
  const recovered = after * Number(item.surplus_quantity ?? 0);

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/inventory/offers", {
        product_id: item.product_id,
        discount_percent: percent,
        starts_on: today,
        ends_on: endsOn,
        note: note.trim() || null,
      });
      onDone(`تم تفعيل خصم ${pct}% على ${item.product_name}.`);
    } catch (err) {
      setError(apiMessage(err));
      setBusy(false);
    }
  };

  return (
    <Modal open title={`عرض على ${item.product_name}`} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <Input
          label="نسبة الخصم %"
          type="number"
          min="1"
          max="99"
          step="any"
          value={percent}
          onChange={(e) => setPercent(e.target.value)}
          required
          autoFocus
        />
        <Input
          label="ساري حتى"
          type="date"
          value={endsOn}
          min={today}
          onChange={(e) => setEndsOn(e.target.value)}
          required
        />
        <Input
          label="سبب العرض — يظهر للعميل"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={200}
        />

        <div className="rounded-lg bg-slate-50 p-3 text-sm dark:bg-slate-800/60">
          <div className="flex justify-between">
            <span className="text-slate-500 dark:text-slate-400">سعر الجملة</span>
            <span className="text-slate-700 dark:text-slate-200">{money(before)}</span>
          </div>
          <div className="flex justify-between font-bold">
            <span className="text-slate-600 dark:text-slate-300">بعد الخصم</span>
            <span className="text-emerald-700 dark:text-emerald-400">{money(after)}</span>
          </div>
          {cost !== null ? (
            <div className="flex justify-between">
              <span className="text-slate-500 dark:text-slate-400">التكلفة</span>
              <span className="text-slate-700 dark:text-slate-200">{money(cost)}</span>
            </div>
          ) : null}
          <div className="mt-1 flex justify-between border-t border-slate-200 pt-1 dark:border-slate-700">
            <span className="text-slate-500 dark:text-slate-400">
              المتحصَّل لو بيع الفائض كله
            </span>
            <span className="text-slate-700 dark:text-slate-200">{money(recovered)}</span>
          </div>
        </div>

        {belowCost ? (
          // A warning, not a block: below cost can be the right call against a
          // write-off. It must simply not be a surprise.
          <Alert tone="error">
            هذا السعر أقل من التكلفة. قد يكون قراراً صحيحاً مقابل الإتلاف، لكن تأكّد.
          </Alert>
        ) : null}
        <p className="text-xs text-slate-500 dark:text-slate-400">
          سيظهر السعر قبل وبعد الخصم للعميل في البوابة، وسيُحتسب به في الفاتورة.
        </p>

        <Alert>{error}</Alert>
        <div className="flex justify-end gap-2">
          <CancelButton onClose={onClose} />
          <Button type="submit" disabled={busy}>
            {busy ? "جارٍ التفعيل…" : "تفعيل العرض"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

const columns = (showRate) =>
  [
    {
      key: "product_name",
      label: "الصنف",
      render: (r) => (
        <span className="flex flex-wrap items-center gap-2">
          {r.product_name}
          {r.active_offer_percent ? (
            <Badge tone="green">خصم {qty(r.active_offer_percent)}%</Badge>
          ) : null}
        </span>
      ),
    },
    {
      key: "days_remaining",
      label: "المتبقي",
      render: (r) => (
        <Badge tone={urgencyTone(r.days_remaining)}>{r.days_remaining} يوم</Badge>
      ),
    },
    { key: "earliest_expiry", label: "أقرب انتهاء" },
    {
      key: "quantity_at_risk",
      label: "الكمية",
      render: (r) => `${qty(r.quantity_at_risk)} ${r.unit}`,
    },
    showRate && {
      key: "daily_sales_rate",
      label: "معدل البيع/يوم",
      render: (r) => qty(r.daily_sales_rate),
    },
    {
      key: "surplus_quantity",
      label: "الفائض المتوقع",
      render: (r) => `${qty(r.surplus_quantity)} ${r.unit}`,
    },
    {
      key: "surplus_value",
      label: "قيمة الفائض",
      render: (r) => money(r.surplus_value),
    },
  ].filter(Boolean);

export default function ExpiryWorklistPage() {
  const { can } = useAuth();
  const canOffer = can("products.offers");
  const [horizon, setHorizon] = useState(60);
  const [tab, setTab] = useState("calls");
  const [offering, setOffering] = useState(null);
  const [notice, setNotice] = useState(null);
  const [actionError, setActionError] = useState(null);

  const worklist = useFetch(
    () =>
      api.get("/analytics/inventory/expiry-worklist", {
        params: { horizon_days: horizon },
      }),
    [horizon]
  );

  const endOffer = async (item) => {
    setActionError(null);
    try {
      await api.post(`/inventory/offers/${item.active_offer_id}/end`);
      setNotice(`تم إيقاف الخصم على ${item.product_name}.`);
      worklist.reload();
    } catch (err) {
      setActionError(apiMessage(err));
    }
  };

  const detail = (row) => (
    <Buyers
      item={row}
      canOffer={canOffer}
      onOffer={setOffering}
      onEndOffer={endOffer}
    />
  );

  if (worklist.loading) return <Loading />;
  const data = worklist.data;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold text-slate-800 dark:text-slate-100">
          الأصناف المهددة بالانتهاء
        </h1>
        <Select value={horizon} onChange={(e) => setHorizon(Number(e.target.value))}>
          {HORIZONS.map((h) => (
            <option key={h.value} value={h.value}>
              {h.label}
            </option>
          ))}
        </Select>
      </div>

      <Alert>{worklist.error ?? actionError}</Alert>
      <Alert tone="success">{notice}</Alert>

      <div className="grid gap-3 sm:grid-cols-2">
        <Stat
          label="فائض يمكن تصريفه بالاتصال"
          value={money(data?.total_surplus_value ?? 0)}
          hint={`${data?.total_products ?? 0} صنفاً لها عملاء سابقون`}
          tone="amber"
        />
        <Stat
          label="راكد لم يُبَع مطلقاً"
          value={money(data?.dead_stock_value ?? 0)}
          hint={`${data?.dead_stock?.length ?? 0} صنفاً — تخفيض أو إرجاع للمورّد`}
          tone="rose"
        />
      </div>

      <div className="flex flex-wrap gap-2">
        <Button
          variant={tab === "calls" ? "primary" : "secondary"}
          onClick={() => setTab("calls")}
        >
          يستحق الاتصال ({data?.items?.length ?? 0})
        </Button>
        <Button
          variant={tab === "dead" ? "primary" : "secondary"}
          onClick={() => setTab("dead")}
        >
          راكد ({data?.dead_stock?.length ?? 0})
        </Button>
      </div>

      {tab === "calls" ? (
        <Card title="أصناف تُباع لكنها لن تنتهي قبل تاريخ الصلاحية">
          <p className="mb-3 text-sm text-slate-500 dark:text-slate-400">
            مرتبة بحسب قيمة الفائض على أيام المهلة — الأعلى أولاً. افتح التفاصيل لترى
            من يُتصل به.
          </p>
          <Table
            columns={columns(true)}
            rows={data?.items ?? []}
            keyField="product_id"
            empty="لا يوجد فائض متوقع في هذه المهلة."
            renderDetail={detail}
          />
        </Card>
      ) : (
        <Card title="أصناف لم تُبَع مطلقاً خلال فترة القياس">
          {/* Kept apart on purpose: no one has ever bought these, so there is no call
              to make. Mixed into the list above they would outrank every real
              opportunity, because "never sold" always scores maximum surplus. */}
          <p className="mb-3 text-sm text-slate-500 dark:text-slate-400">
            لا يوجد عميل سابق لهذه الأصناف، فلا جدوى من الاتصال. القرار هنا تخفيض
            السعر أو الإرجاع للمورّد أو قبول الخسارة قبل أن تكبر.
          </p>
          <Table
            columns={columns(false)}
            rows={data?.dead_stock ?? []}
            keyField="product_id"
            empty="لا يوجد مخزون راكد في هذه المهلة."
            renderDetail={detail}
          />
        </Card>
      )}

      {offering ? (
        <OfferDialog
          item={offering}
          onClose={() => setOffering(null)}
          onDone={(message) => {
            setOffering(null);
            setNotice(message);
            worklist.reload();
          }}
        />
      ) : null}
    </div>
  );
}
