// Customer requests (طلبات العملاء) — a module of the main system.
//
// Shops send requests in from their own portal; this is where the company
// answers them. Deliberately an ordinary ERP module beside sales and stock,
// not a second portal: the only separate application is the customer's.
//
// Opening and withdrawing a customer's portal access is *not* here. That is
// administration of the customer, and lives on the customers page.
//
// A request arriving here is a request, not a sale — it has moved no stock and
// carries no price, because nothing is priced until this screen turns it into an
// invoice. That is why the queue shows quantities and never a total: quoting one
// would mean the portal had already decided what the sale is worth.
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  Badge,
  Button,
  CancelButton,
  Card,
  Input,
  Modal,
  Select,
  Table,
  qty,
} from "../components/Ui";
import useFetch from "../hooks/useFetch";
import api, { apiMessage } from "../services/api";

const STATUS_LABELS = {
  pending: "بانتظار المراجعة",
  confirmed: "معتمد — قيد التجهيز",
  invoiced: "صدرت فاتورته",
  cancelled: "ملغى",
};
const STATUS_TONES = {
  pending: "amber",
  confirmed: "blue",
  invoiced: "green",
  cancelled: "slate",
};

// Deliberately words, not numbers. The customer sees the same three bands, and
// the office should be reading exactly what the shop read when it ordered.
const AVAILABILITY_LABELS = {
  available: "متوفر",
  limited: "كمية محدودة",
  unavailable: "غير متوفر",
};
const AVAILABILITY_TONES = {
  available: "green",
  limited: "amber",
  unavailable: "red",
};

const FULFILLMENT_LABELS = { pickup: "استلام من المستودع", delivery: "توصيل" };

// Arabic counts its nouns by number; "3 صنف" reads as broken software.
const lineCount = (n) => {
  const count = Number(n) || 0;
  if (count === 1) return "صنف واحد";
  if (count === 2) return "صنفان";
  if (count >= 3 && count <= 10) return `${count} أصناف`;
  return `${count} صنف`;
};

function OrderLines({ order }) {
  return (
    <div className="space-y-2">
      {order.lines.map((line) => (
        <div
          key={line.product_id}
          className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-slate-50 px-3 py-2 text-sm dark:bg-slate-800/60"
        >
          <span className="font-medium text-slate-700 dark:text-slate-200">
            {line.product_name}
          </span>
          <span className="flex items-center gap-2">
            <span className="text-slate-600 dark:text-slate-300">
              {qty(line.quantity)} {line.unit}
            </span>
            {/* Re-read now, not frozen when the order was placed: what matters
                to whoever is about to pick it is whether it can be filled today. */}
            <Badge tone={AVAILABILITY_TONES[line.availability]}>
              {AVAILABILITY_LABELS[line.availability]}
            </Badge>
          </span>
        </div>
      ))}
      {order.notes ? (
        <p className="text-sm text-slate-500 dark:text-slate-400">
          ملاحظة العميل: {order.notes}
        </p>
      ) : null}
      {order.decision_note ? (
        <p className="text-sm text-slate-500 dark:text-slate-400">
          ما أُبلغ به العميل: {order.decision_note}
        </p>
      ) : null}
    </div>
  );
}

function InvoiceDialog({ order, onClose, onDone }) {
  const [paymentMethod, setPaymentMethod] = useState("credit");
  const [warehouseId, setWarehouseId] = useState("");
  const [taxRateIds, setTaxRateIds] = useState([]);
  const [creditOverride, setCreditOverride] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const warehouses = useFetch(() => api.get("/inventory/warehouses"));
  const taxRates = useFetch(() => api.get("/settings/tax-rates"));

  // A van's stock belongs to a salesman's round; an order from the portal is
  // served from a depot.
  const depots = (warehouses.data ?? []).filter((w) => !w.is_vehicle && w.is_active);

  const submit = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const { data } = await api.post(`/customer-orders/${order.id}/invoice`, {
        payment_method: paymentMethod,
        tax_rate_ids: taxRateIds,
        warehouse_id: warehouseId ? Number(warehouseId) : null,
        credit_override: creditOverride,
      });
      onDone(data.data, data.message);
    } catch (err) {
      // The credit limit and short stock both surface here, from the sales
      // pipeline rather than from any rule this screen invented.
      setError(apiMessage(err));
      setSaving(false);
    }
  };

  return (
    <Modal open title={`إصدار فاتورة للطلب #${order.id}`} onClose={onClose} wide>
      <form onSubmit={submit} className="space-y-4">
        <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
          <p className="mb-2 text-sm font-bold text-slate-700 dark:text-slate-200">
            {order.customer_name}
          </p>
          <OrderLines order={order} />
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <Select
            label="طريقة الدفع"
            value={paymentMethod}
            onChange={(e) => setPaymentMethod(e.target.value)}
          >
            <option value="credit">آجل</option>
            <option value="cash">نقدي</option>
            <option value="card">بطاقة</option>
          </Select>
          <Select
            label="المستودع"
            value={warehouseId}
            onChange={(e) => setWarehouseId(e.target.value)}
          >
            <option value="">اختيار تلقائي</option>
            {depots.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </Select>
        </div>

        <fieldset>
          <legend className="mb-2 text-sm font-medium text-slate-600 dark:text-slate-300">
            الضرائب المطبقة
          </legend>
          <div className="flex flex-wrap gap-3">
            {(taxRates.data ?? []).map((rate) => (
              <label
                key={rate.id}
                className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-200"
              >
                <input
                  type="checkbox"
                  checked={taxRateIds.includes(rate.id)}
                  onChange={(e) =>
                    setTaxRateIds((current) =>
                      e.target.checked
                        ? [...current, rate.id]
                        : current.filter((id) => id !== rate.id)
                    )
                  }
                />
                {rate.name} ({rate.rate}%)
              </label>
            ))}
            {!(taxRates.data ?? []).length ? (
              <span className="text-sm text-slate-400">لا توجد ضرائب معرّفة.</span>
            ) : null}
          </div>
        </fieldset>

        <label className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-200">
          <input
            type="checkbox"
            checked={creditOverride}
            onChange={(e) => setCreditOverride(e.target.checked)}
          />
          تجاوز الحد الائتماني للعميل (بموافقة المدير)
        </label>

        <Alert>{error}</Alert>
        <div className="flex justify-end gap-2">
          <CancelButton onClose={onClose} />
          <Button type="submit" disabled={saving}>
            {saving ? "جارٍ الإصدار…" : "إصدار الفاتورة"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function RejectDialog({ order, onClose, onDone }) {
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const submit = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const { data } = await api.post(`/customer-orders/${order.id}/reject`, { reason });
      onDone(data.message);
    } catch (err) {
      setError(apiMessage(err));
      setSaving(false);
    }
  };

  return (
    <Modal open title={`رفض الطلب #${order.id}`} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <Input
          label="السبب — سيقرأه العميل في بوابته"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="مثال: الكمية غير متوفرة هذا الأسبوع، تواصل معنا لبديل."
          required
          maxLength={300}
          autoFocus
        />
        <Alert>{error}</Alert>
        <div className="flex justify-end gap-2">
          <CancelButton onClose={onClose} />
          <Button type="submit" variant="danger" disabled={saving}>
            {saving ? "جارٍ الرفض…" : "رفض وإبلاغ العميل"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function OrdersQueue({ onNotice }) {
  const navigate = useNavigate();
  const [status, setStatus] = useState("pending");
  const [rejecting, setRejecting] = useState(null);
  const [invoicing, setInvoicing] = useState(null);
  const [error, setError] = useState(null);
  const [busyId, setBusyId] = useState(null);

  const orders = useFetch(
    () => api.get("/customer-orders", { params: status ? { status } : {} }),
    [status]
  );

  const approve = async (order) => {
    setBusyId(order.id);
    setError(null);
    try {
      const { data } = await api.post(`/customer-orders/${order.id}/approve`);
      onNotice(data.message);
      orders.reload();
    } catch (err) {
      setError(apiMessage(err));
    } finally {
      setBusyId(null);
    }
  };

  const columns = [
    { key: "id", label: "رقم الطلب", render: (row) => `#${row.id}` },
    { key: "customer_name", label: "العميل" },
    { key: "order_date", label: "التاريخ" },
    {
      key: "lines",
      label: "الأصناف",
      sortable: false,
      search: (row) => row.lines.map((l) => l.product_name).join(" "),
      render: (row) => lineCount(row.lines.length),
    },
    {
      key: "fulfillment",
      label: "التسليم",
      render: (row) => FULFILLMENT_LABELS[row.fulfillment],
    },
    {
      key: "status",
      label: "الحالة",
      render: (row) => (
        <Badge tone={STATUS_TONES[row.status]}>{STATUS_LABELS[row.status]}</Badge>
      ),
    },
    {
      key: "actions",
      label: "",
      sortable: false,
      render: (row) => (
        <div className="flex flex-wrap gap-2">
          {row.status === "pending" ? (
            <>
              <Button
                variant="secondary"
                onClick={() => approve(row)}
                disabled={busyId === row.id}
              >
                اعتماد
              </Button>
              <Button variant="danger" onClick={() => setRejecting(row)}>
                رفض
              </Button>
            </>
          ) : null}
          {row.status === "pending" || row.status === "confirmed" ? (
            <Button onClick={() => setInvoicing(row)}>إصدار فاتورة</Button>
          ) : null}
          {row.invoice_id ? (
            <Button
              variant="secondary"
              onClick={() => navigate(`/print/invoice/${row.invoice_id}`)}
            >
              الفاتورة #{row.invoice_id}
            </Button>
          ) : null}
        </div>
      ),
    },
  ];

  return (
    <Card
      title="طلبات العملاء من البوابة"
      actions={
        <Select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="pending">بانتظار المراجعة</option>
          <option value="confirmed">معتمدة</option>
          <option value="invoiced">صدرت فواتيرها</option>
          <option value="cancelled">ملغاة</option>
          <option value="">كل الطلبات</option>
        </Select>
      }
    >
      <Alert>{error ?? orders.error}</Alert>
      <Table
        columns={columns}
        rows={orders.data ?? []}
        empty="لا توجد طلبات في هذه الحالة."
        renderDetail={(row) => <OrderLines order={row} />}
      />

      {rejecting ? (
        <RejectDialog
          order={rejecting}
          onClose={() => setRejecting(null)}
          onDone={(message) => {
            setRejecting(null);
            onNotice(message);
            orders.reload();
          }}
        />
      ) : null}
      {invoicing ? (
        <InvoiceDialog
          order={invoicing}
          onClose={() => setInvoicing(null)}
          onDone={(invoice, message) => {
            setInvoicing(null);
            onNotice(`${message} رقم الفاتورة #${invoice.id}.`);
            orders.reload();
          }}
        />
      ) : null}
    </Card>
  );
}

export default function CustomerRequestsPage() {
  const [notice, setNotice] = useState(null);

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold text-slate-800 dark:text-slate-100">
        طلبات العملاء
      </h1>
      <Alert tone="success">{notice}</Alert>
      <OrdersQueue onNotice={setNotice} />
    </div>
  );
}
