// Sales team's portal confirmation queue: every customer order still pending,
// oldest first. Confirming converts the order into a real invoice through the
// normal sales pipeline (FEFO + credit check + journal entries) in one atomic
// transaction. Credit sales to a customer at/over their limit require the
// manager-override flag — the same rule as counter credit sales.
import { useState } from "react";
import { Alert, Badge, Button, Card, Loading, Select, Table, qty } from "../components/Ui";
import useFetch from "../hooks/useFetch";
import api, { apiMessage } from "../services/api";

const FULFILLMENT_LABELS = { delivery: "توصيل", pickup: "استلام من المستودع" };

export default function PortalOrdersQueue() {
  const { data, loading, error, reload } = useFetch(() => api.get("/portal/orders/pending"));
  const [confirming, setConfirming] = useState(null);
  const [form, setForm] = useState({ payment_method: "credit", credit_override: false });
  const [actionError, setActionError] = useState(null);

  const open = (order) => {
    setActionError(null);
    setForm({ payment_method: "credit", credit_override: false });
    setConfirming(order);
  };

  const confirm = async (event) => {
    event.preventDefault();
    try {
      await api.post(`/portal/orders/${confirming.id}/confirm`, form);
      setConfirming(null);
      reload();
    } catch (err) {
      setActionError(apiMessage(err));
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-extrabold">طلبات العملاء في الانتظار</h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            أكّد الطلبات لتحويلها إلى فواتير مبيعات رسمية.
          </p>
        </div>
        <Button variant="secondary" onClick={reload}>
          تحديث
        </Button>
      </div>

      <Alert>{error}</Alert>

      {loading ? (
        <Loading />
      ) : (
        <Card>
          <Table
            columns={[
              { key: "id", label: "طلب #" },
              { key: "customer_name", label: "العميل" },
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
              {
                key: "total_quantity",
                label: "الكمية",
                render: (r) => qty(r.total_quantity),
              },
              {
                key: "confirm",
                label: "",
                render: (r) => (
                  <Button onClick={() => open(r)}>التحويل إلى فاتورة</Button>
                ),
              },
            ]}
            rows={data}
            empty="لا توجد طلبات بانتظار التأكيد الآن."
            renderDetail={(r) => (
              <div className="space-y-3">
                {r.notes && (
                  <div className="text-sm text-slate-600 dark:text-slate-300">
                    ملاحظات العميل: {r.notes}
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
              </div>
            )}
          />
        </Card>
      )}

      {confirming && (
        <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/50 p-3 pt-6 sm:p-4 sm:pt-14 dark:bg-slate-950/70"
          onClick={() => setConfirming(null)}
        >
          <div
            className="w-full max-w-lg rounded-xl bg-white p-4 shadow-xl sm:p-6 dark:bg-slate-900 dark:ring-1 dark:ring-slate-700"
            onClick={(event) => event.stopPropagation()}
          >
            <header className="mb-4 flex items-start justify-between gap-3">
              <h3 className="text-base font-extrabold sm:text-lg dark:text-slate-100">
                تحويل طلب #{confirming.id} ({confirming.customer_name}) إلى فاتورة
              </h3>
              <button
                onClick={() => setConfirming(null)}
                aria-label="إغلاق"
                className="shrink-0 text-2xl leading-none text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
              >
                ×
              </button>
            </header>
            <form onSubmit={confirm} className="space-y-4">
              <Alert>{actionError}</Alert>
              <div>
                <label className="mb-1 block text-sm font-bold text-slate-600 dark:text-slate-400">
                  طريقة الدفع
                </label>
                <select
                  value={form.payment_method}
                  onChange={(e) =>
                    setForm({ ...form, payment_method: e.target.value })
                  }
                  className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-emerald-600 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
                >
                  <option value="cash">نقدي</option>
                  <option value="card">بطاقة</option>
                  <option value="credit">آجل (على الحساب)</option>
                </select>
              </div>
              <label className="flex items-center gap-2 text-sm font-bold text-slate-600 dark:text-slate-300">
                <input
                  type="checkbox"
                  checked={form.credit_override}
                  onChange={(e) =>
                    setForm({ ...form, credit_override: e.target.checked })
                  }
                  className="h-4 w-4"
                />
                تجاوز الحد الائتماني (بموافقة المدير)
              </label>
              <div className="flex justify-end gap-2">
                <Button type="button" variant="secondary" onClick={() => setConfirming(null)}>
                  إلغاء
                </Button>
                <Button type="submit">تأكيد الفوترة</Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}