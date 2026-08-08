// What a shop wants to know in the two seconds after opening the app: what do I
// owe, and what happened to the order I sent.
import { Link } from "react-router-dom";
import { Alert, Badge, Loading, money } from "../components/Ui";
import useFetch from "../hooks/useFetch";
import portalApi from "../services/portalApi";

export const ORDER_STATUS = {
  pending: { label: "بانتظار المراجعة", tone: "amber" },
  confirmed: { label: "معتمد — قيد التجهيز", tone: "blue" },
  invoiced: { label: "صدرت فاتورته", tone: "green" },
  cancelled: { label: "ملغى", tone: "slate" },
};

function Panel({ title, action, children }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-bold text-slate-700 dark:text-slate-200">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

const more = (to, text) => (
  <Link
    to={to}
    className="text-xs font-bold text-emerald-600 hover:underline dark:text-emerald-400"
  >
    {text}
  </Link>
);

export default function PortalHome() {
  const statement = useFetch(() => portalApi.get("/portal/statement"));
  const orders = useFetch(() => portalApi.get("/portal/orders"));

  if (statement.loading) return <Loading />;

  const data = statement.data;
  const balance = Number(data?.balance ?? 0);
  // A negative balance means we owe them, which is worth saying in words — a
  // customer reading "-1,240" on their own statement usually assumes it is a debt.
  const owes = balance > 0;

  return (
    <div className="space-y-4">
      <Alert>{statement.error}</Alert>

      <section
        className={`rounded-2xl p-5 text-center ${
          owes
            ? "bg-amber-50 dark:bg-amber-950/40"
            : "bg-emerald-50 dark:bg-emerald-950/40"
        }`}
      >
        <p className="text-sm font-bold text-slate-600 dark:text-slate-300">
          {owes ? "المستحق عليكم" : balance < 0 ? "رصيد لكم لدينا" : "لا يوجد مستحق"}
        </p>
        <p
          className={`mt-1 text-3xl font-bold ${
            owes
              ? "text-amber-800 dark:text-amber-200"
              : "text-emerald-800 dark:text-emerald-200"
          }`}
        >
          {money(Math.abs(balance))}
        </p>
      </section>

      <Panel title="آخر الفواتير" action={more("/portal/invoices", "الكل")}>
        {data?.invoices?.length ? (
          <ul className="divide-y divide-slate-100 dark:divide-slate-700">
            {data.invoices.slice(0, 4).map((invoice) => (
              <li key={invoice.id} className="flex items-center justify-between py-2">
                <span className="text-sm text-slate-600 dark:text-slate-300">
                  #{invoice.id} — {invoice.invoice_date}
                </span>
                <span className="flex items-center gap-2">
                  <span className="text-sm font-bold text-slate-800 dark:text-slate-100">
                    {money(invoice.total)}
                  </span>
                  {invoice.is_settled ? (
                    <Badge tone="green">مسددة</Badge>
                  ) : (
                    <Badge tone="amber">{money(invoice.amount_due)} متبقٍ</Badge>
                  )}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="py-4 text-center text-sm text-slate-400">لا توجد فواتير بعد.</p>
        )}
      </Panel>

      <Panel title="طلباتي الأخيرة" action={more("/portal/orders", "الكل")}>
        {orders.data?.length ? (
          <ul className="divide-y divide-slate-100 dark:divide-slate-700">
            {orders.data.slice(0, 4).map((order) => (
              <li key={order.id} className="flex items-center justify-between py-2">
                <span className="text-sm text-slate-600 dark:text-slate-300">
                  #{order.id} — {order.order_date}
                </span>
                <Badge tone={ORDER_STATUS[order.status].tone}>
                  {ORDER_STATUS[order.status].label}
                </Badge>
              </li>
            ))}
          </ul>
        ) : (
          <p className="py-4 text-center text-sm text-slate-400">
            لم ترسل أي طلب بعد.{" "}
            <Link
              to="/portal/catalog"
              className="font-bold text-emerald-600 dark:text-emerald-400"
            >
              تصفّح الأصناف
            </Link>
          </p>
        )}
      </Panel>
    </div>
  );
}
