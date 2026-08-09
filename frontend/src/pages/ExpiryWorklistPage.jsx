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
  Card,
  Loading,
  Select,
  Stat,
  Table,
  money,
  qty,
} from "../components/Ui";
import useFetch from "../hooks/useFetch";
import api from "../services/api";

const HORIZONS = [
  { value: 30, label: "خلال ٣٠ يوماً" },
  { value: 60, label: "خلال ٦٠ يوماً" },
  { value: 90, label: "خلال ٩٠ يوماً" },
];

// Days left is the thing the eye should catch first, so it carries the colour.
const urgencyTone = (days) => (days <= 14 ? "red" : days <= 30 ? "amber" : "slate");

function Buyers({ item }) {
  if (!item.suggested_buyers.length) {
    return (
      <p className="text-sm text-slate-500 dark:text-slate-400">
        لا يوجد عملاء سبق أن اشتروا هذا الصنف — يحتاج تخفيضاً أو إعادة للمورّد.
      </p>
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
    </div>
  );
}

const columns = (showRate) =>
  [
    { key: "product_name", label: "الصنف" },
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
  const [horizon, setHorizon] = useState(60);
  const [tab, setTab] = useState("calls");

  const worklist = useFetch(
    () =>
      api.get("/analytics/inventory/expiry-worklist", {
        params: { horizon_days: horizon },
      }),
    [horizon]
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

      <Alert>{worklist.error}</Alert>

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
            renderDetail={(row) => <Buyers item={row} />}
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
            renderDetail={(row) => <Buyers item={row} />}
          />
        </Card>
      )}
    </div>
  );
}
