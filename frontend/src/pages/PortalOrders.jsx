// The customer's own orders, newest first. Each shows its status timeline and
// a cancel button while it is still pending. Quantities only — no prices.
import { useState } from "react";
import { Link } from "react-router-dom";
import { Alert, Badge, Button, Card, Loading, Table, qty } from "../components/Ui";
import useFetch from "../hooks/useFetch";
import api, { apiMessage } from "../services/api";

export const ORDER_STATUS_META = {
  pending: { label: "قيد الانتظار", tone: "amber" },
  confirmed: { label: "تم التأكيد", tone: "blue" },
  invoiced: { label: "تم تحويله لفاتورة", tone: "green" },
  cancelled: { label: "ملغي", tone: "red" },
};

const FULFILLMENT_LABELS = { delivery: "توصيل", pickup: "استلام من المستودع" };

export default function PortalOrders() {
  const { data, loading, error, reload } = useFetch(() => api.get("/portal/orders"));
  const [busyId, setBusyId] = useState(null);
  const [actionError, setActionError] = useState(null);

  const cancel = async (order) => {
    if (!window.confirm(`هل تريد إلغاء الطلب رقم ${order.id}؟`)) return;
    const reason = window.prompt("سبب الإلغاء (اختياري):") ?? "";
    setBusyId(order.id);
    setActionError(null);
    try {
      await api.post(`/portal/orders/${order.id}/cancel`, { reason: reason || null });
      reload();
    } catch (err) {
      setActionError(apiMessage(err));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-extrabold">طلباتي</h1>
        <Link to="/portal/catalog">
          <Button>+ طلب جديد</Button>
        </Link>
      </div>

      <Alert>{error}</Alert>
      <Alert>{actionError}</Alert>

      {loading ? (
        <Loading />
      ) : (
        <Card>
          <Table
            columns={[
              { key: "id", label: "الطلب" },
              { key: "order_date", label: "التاريخ", sortValue: (r) => r.order_date },
              {
                key: "fulfillment",
                label: "التوصيل",
                render: (r) => FULFILLMENT_LABELS[r.fulfillment] || r.fulfillment,
              },
              {
                key: "warehouse_name",
                label: "المستودع",
                render: (r) => r.warehouse_name || "—",
              },
              { key: "total_quantity", label: "الكمية", render: (r) => qty(r.total_quantity) },
              {
                key: "status",
                label: "الحالة",
                render: (r) => {
                  const meta = ORDER_STATUS_META[r.status] ?? ORDER_STATUS_META.pending;
                  return <Badge tone={meta.tone}>{meta.label}</Badge>;
                },
              },
              {
                key: "cancel",
                label: "",
                render: (r) =>
                  r.status === "pending" ? (
                    <Button
                      variant="danger"
                      disabled={busyId === r.id}
                      onClick={() => cancel(r)}
                    >
                      {busyId === r.id ? "..." : "إلغاء"}
                    </Button>
                  ) : null,
              },
            ]}
            rows={data}
            empty="لا توجد طلبات بعد. ابدأ طلبك من الكتالوج."
            renderDetail={(r) => (
              <div className="space-y-3">
                {r.notes && (
                  <div className="text-sm text-slate-600 dark:text-slate-300">
                    ملاحظات: {r.notes}
                  </div>
                )}
                <ul className="space-y-1">
                  {r.lines.map((line) => (
                    <li key={line.id} className="flex justify-between text-sm">
                      <span>{line.product_name || "صنف"}</span>
                      <span className="font-bold">{qty(line.quantity)}</span>
                    </li>
                  ))}
                </ul>
                {r.cancel_reason && (
                  <div className="text-xs text-rose-600 dark:text-rose-400">
                    سبب الإلغاء: {r.cancel_reason}
                  </div>
                )}
                {r.status === "invoiced" && (
                  <div className="text-sm font-bold text-emerald-700 dark:text-emerald-400">
                    فاتورة #{r.converted_invoice_id} مرفقة بكشف الحساب.
                  </div>
                )}
              </div>
            )}
          />
        </Card>
      )}
    </div>
  );
}