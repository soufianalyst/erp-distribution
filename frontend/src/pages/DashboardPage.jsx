// The landing page: headline counts and the alerts that need acting on today,
// each linking to the screen where the work is done.
import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Alert, Badge, Button, Card, Loading, Stat, Table, qty } from "../components/Ui";
import useFetch from "../hooks/useFetch";
import api from "../services/api";

// Severity drives the whole card: how loud it looks and how it sorts. The
// backend decides severity so the UI never has to re-derive urgency.
const SEVERITY = {
  critical: {
    label: "عاجل",
    tone: "red",
    card: "border-rose-300 bg-rose-50 dark:border-rose-900 dark:bg-rose-950/40",
    icon: "🚨",
  },
  warning: {
    label: "تحذير",
    tone: "amber",
    card: "border-amber-300 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/40",
    icon: "⚠️",
  },
  info: {
    label: "للمتابعة",
    tone: "blue",
    card: "border-sky-300 bg-sky-50 dark:border-sky-900 dark:bg-sky-950/40",
    icon: "ℹ️",
  },
};

function AlertCard({ group }) {
  const navigate = useNavigate();
  const style = SEVERITY[group.severity] ?? SEVERITY.info;
  // The group carries a preview, not the full list; say so when more remain.
  const hidden = group.count - group.items.length;

  return (
    <section className={`rounded-xl border p-4 shadow-sm ${style.card}`}>
      <header className="mb-2 flex flex-wrap items-start justify-between gap-2">
        <div className="flex items-start gap-2">
          <span aria-hidden="true">{style.icon}</span>
          <div>
            <h3 className="font-extrabold text-slate-800 dark:text-slate-100">
              {group.label}
            </h3>
            <p className="mt-0.5 text-xs font-bold text-slate-600 dark:text-slate-400">
              {group.hint}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Badge tone={style.tone}>{style.label}</Badge>
          <span className="text-2xl font-extrabold text-slate-800 dark:text-slate-100">
            {group.count}
          </span>
        </div>
      </header>

      <ul className="space-y-1 text-sm">
        {group.items.map((item, index) => (
          <li
            key={`${item.label}-${index}`}
            className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-200/70 pt-1 dark:border-slate-700/70"
          >
            <span className="font-bold text-slate-800 dark:text-slate-200">
              {item.label}
              <span className="ms-2 text-xs font-normal text-slate-600 dark:text-slate-400">
                {item.detail}
              </span>
            </span>
            {item.value && (
              <span className="text-xs font-extrabold text-slate-700 dark:text-slate-300">
                {item.value}
              </span>
            )}
          </li>
        ))}
      </ul>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        {hidden > 0 ? (
          <span className="text-xs font-bold text-slate-600 dark:text-slate-400">
            و{hidden} غيرها
          </span>
        ) : (
          <span />
        )}
        <Button variant="secondary" onClick={() => navigate(group.route)}>
          معالجة الآن ←
        </Button>
      </div>
    </section>
  );
}


// How often the dashboard re-checks for new orders. A notification that only
// appears on a page refresh is not a notification — the screen sits open on a
// desk all morning, and an order that arrives at 09:05 must not wait for someone
// to press F5 at noon.
const POLL_MS = 60_000;

/** A shop is waiting. The loudest thing on the page, and deliberately so.
 *
 * The other alerts are work we owe ourselves — stock to count, orders to chase.
 * This one is a customer standing at their counter wondering whether their order
 * went through, so it sits above everything with the count in the largest type on
 * the screen, rather than as one card among six that the eye slides past.
 *
 * Not dismissible. It disappears when the orders are answered, which is the only
 * honest way for it to go away.
 */
function NewOrdersBanner({ group }) {
  const navigate = useNavigate();
  if (!group) return null;
  const overdue = group.severity === "critical";

  return (
    <section
      // `alert` rather than `status`: a screen reader should interrupt for this.
      role="alert"
      className={`flex flex-wrap items-center gap-4 rounded-2xl border-2 p-5 shadow-md ${
        overdue
          ? "border-rose-400 bg-rose-50 dark:border-rose-700 dark:bg-rose-950/50"
          : "border-teal-400 bg-teal-50 dark:border-teal-600 dark:bg-teal-950/40"
      }`}
    >
      <span className="relative flex h-14 w-14 shrink-0 items-center justify-center">
        {/* The pulse is the only animation on the dashboard, saved for the one
            thing where a person is actually waiting on the other end. */}
        <span
          className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 ${
            overdue ? "bg-rose-300" : "bg-teal-300"
          }`}
        />
        <span
          className={`relative inline-flex h-14 w-14 items-center justify-center rounded-full text-2xl ${
            overdue ? "bg-rose-500" : "bg-teal-500"
          }`}
        >
          🔔
        </span>
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span
            className={`text-4xl font-extrabold leading-none ${
              overdue
                ? "text-rose-700 dark:text-rose-300"
                : "text-teal-700 dark:text-teal-300"
            }`}
          >
            {group.count}
          </span>
          <span className="text-lg font-extrabold text-slate-800 dark:text-slate-100">
            {group.label}
          </span>
        </div>
        <p className="mt-1 text-sm font-bold text-slate-600 dark:text-slate-300">
          {group.hint}
        </p>
        {group.items.length > 0 && (
          <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600 dark:text-slate-400">
            {group.items.map((item, index) => (
              <li key={index}>
                <span className="font-bold">{item.label}</span> — {item.detail} ·{" "}
                {item.value}
              </li>
            ))}
          </ul>
        )}
      </div>

      <Button onClick={() => navigate("/customer-requests")}>
        مراجعة الطلبات ←
      </Button>
    </section>
  );
}

export default function DashboardPage() {
  const alerts = useFetch(() => api.get("/alerts"));
  const levels = useFetch(() => api.get("/inventory/stock/levels"));
  const products = useFetch(() => api.get("/inventory/products"));

  // Only the alerts are re-polled. Stock levels and the catalogue do not change
  // while someone stares at this page, and refetching them every minute would be
  // a megabyte an hour to learn nothing.
  const reloadAlerts = alerts.reload;
  useEffect(() => {
    const timer = setInterval(reloadAlerts, POLL_MS);
    return () => clearInterval(timer);
  }, [reloadAlerts]);

  // Blank the page only on the very first load. Without the `!data` guard the
  // whole dashboard would flash to a spinner every minute when the poll fires.
  if ((alerts.loading && !alerts.data) || levels.loading || products.loading) {
    return <Loading />;
  }
  const error = alerts.error || levels.error || products.error;
  const data = alerts.data;
  const groups = data?.groups ?? [];
  const newOrders = groups.find((g) => g.key === "pending_customer_orders");
  // Promoted to the banner above, so it must not also appear as an ordinary card
  // — the same thing said twice reads as two problems.
  const otherGroups = groups.filter((g) => g.key !== "pending_customer_orders");

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-extrabold">لوحة التحكم</h1>
      <Alert>{error}</Alert>

      <NewOrdersBanner group={newOrders} />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="عدد الأصناف" value={products.data?.total ?? 0} />
        <Stat label="أرصدة مخزنية نشطة" value={levels.data?.length ?? 0} />
        <Stat
          label="تنبيهات عاجلة"
          value={data?.critical_count ?? 0}
          tone="rose"
          hint="تحتاج إجراءً اليوم"
        />
        <Stat
          label="تنبيهات تحذيرية"
          value={data?.warning_count ?? 0}
          tone="amber"
          hint="تحتاج متابعة قريبة"
        />
      </div>

      <Card title="ما يحتاج انتباهك الآن">
        {otherGroups.length === 0 ? (
          <p className="py-8 text-center text-sm font-bold text-emerald-700 dark:text-emerald-400">
            لا توجد تنبيهات — كل شيء على ما يبدو سليم. 👌
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            {otherGroups.map((group) => (
              <AlertCard key={group.key} group={group} />
            ))}
          </div>
        )}
      </Card>

      <Card title="أرصدة المخزون الحالية">
        <Table
          columns={[
            { key: "product_name", label: "الصنف" },
            { key: "warehouse_name", label: "المستودع" },
            {
              key: "total_quantity",
              label: "الرصيد",
              render: (r) => `${qty(r.total_quantity)} ${r.base_unit_name}`,
            },
          ]}
          rows={levels.data}
          keyField={(r) => `${r.product_id}-${r.warehouse_id}`}
          empty="المخزون فارغ حالياً."
        />
      </Card>
    </div>
  );
}
