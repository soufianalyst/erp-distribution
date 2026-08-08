// Tracking what was asked for and what the office said back.
import { useState } from "react";
import { Link } from "react-router-dom";
import { Alert, Badge, Button, Loading, qty } from "../components/Ui";
import useFetch from "../hooks/useFetch";
import portalApi, { portalMessage } from "../services/portalApi";
import { ORDER_STATUS } from "./PortalHome";

export default function PortalMyOrders() {
  const orders = useFetch(() => portalApi.get("/portal/orders"));
  const [busyId, setBusyId] = useState(null);
  const [error, setError] = useState(null);

  const cancel = async (order) => {
    setBusyId(order.id);
    setError(null);
    try {
      await portalApi.post(`/portal/orders/${order.id}/cancel`, { reason: null });
      orders.reload();
    } catch (err) {
      setError(portalMessage(err));
    } finally {
      setBusyId(null);
    }
  };

  if (orders.loading) return <Loading />;

  return (
    <div className="space-y-3">
      <Alert>{orders.error ?? error}</Alert>

      {!orders.data?.length ? (
        <p className="py-10 text-center text-sm text-slate-400">
          لم ترسل أي طلب بعد.{" "}
          <Link
            to="/portal/catalog"
            className="font-bold text-emerald-600 dark:text-emerald-400"
          >
            ابدأ من الأصناف
          </Link>
        </p>
      ) : null}

      {(orders.data ?? []).map((order) => (
        <article
          key={order.id}
          className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800"
        >
          <header className="mb-3 flex items-center justify-between gap-2">
            <div>
              <p className="text-sm font-bold text-slate-800 dark:text-slate-100">
                طلب #{order.id}
              </p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {order.order_date} ·{" "}
                {order.fulfillment === "delivery" ? "توصيل" : "استلام من المستودع"}
              </p>
            </div>
            <Badge tone={ORDER_STATUS[order.status].tone}>
              {ORDER_STATUS[order.status].label}
            </Badge>
          </header>

          <ul className="space-y-1 text-sm">
            {order.lines.map((line) => (
              <li
                key={line.product_id}
                className="flex justify-between gap-2 text-slate-600 dark:text-slate-300"
              >
                <span className="truncate">{line.product_name}</span>
                <span className="shrink-0">
                  {qty(line.quantity)} {line.unit}
                </span>
              </li>
            ))}
          </ul>

          {order.notes ? (
            <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
              ملاحظتك: {order.notes}
            </p>
          ) : null}
          {/* The office writes this for the customer, so it is shown prominently
              rather than tucked away as metadata. */}
          {order.decision_note ? (
            <p className="mt-2 rounded-lg bg-slate-50 p-2 text-xs text-slate-600 dark:bg-slate-900/60 dark:text-slate-300">
              ردّ الشركة: {order.decision_note}
            </p>
          ) : null}

          <footer className="mt-3 flex flex-wrap gap-2">
            {order.status === "pending" ? (
              <Button
                variant="danger"
                onClick={() => cancel(order)}
                disabled={busyId === order.id}
              >
                إلغاء الطلب
              </Button>
            ) : null}
            {order.invoice_id ? (
              <Link
                to={`/portal/invoices?open=${order.invoice_id}`}
                className="rounded-lg bg-slate-100 px-4 py-2 text-sm font-bold text-slate-700 dark:bg-slate-700 dark:text-slate-200"
              >
                عرض الفاتورة #{order.invoice_id}
              </Link>
            ) : null}
          </footer>
        </article>
      ))}
    </div>
  );
}
