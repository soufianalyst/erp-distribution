import { useState } from "react";
import { Alert, Badge, Button, Card, Input, Modal, Stat, Table, money, qty } from "../components/Ui";
import useFetch from "../hooks/useFetch";
import api, { apiMessage } from "../services/api";

const PAYMENT_METHOD_LABELS = { cash: "نقدي", card: "بطاقة" };
const PAYMENT_METHOD_TONE = { cash: "green", card: "blue" };
const PAYABLE_TYPE_LABELS = { purchase_invoice: "فاتورة شراء", expense: "مصروف" };
const REFERENCE_TYPE_LABELS = {
  sales_invoice: "فاتورة مبيعات",
  purchase_invoice: "فاتورة شراء",
  expense: "مصروف",
};

const todayStr = () => new Date().toISOString().slice(0, 10);
const remaining = (doc) => (Number(doc.total) - Number(doc.paid_amount)).toFixed(2);
const payableRemaining = (payable) => Number(payable.remaining).toFixed(2);

export default function CashierPage() {
  const [viewing, setViewing] = useState(null);
  const [collectingFor, setCollectingFor] = useState(null);
  const [payingFor, setPayingFor] = useState(null);
  const [amount, setAmount] = useState("");
  const [dialogError, setDialogError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [error, setError] = useState(null);
  const [summaryDay, setSummaryDay] = useState(todayStr());

  const invoices = useFetch(() => api.get("/cashier/invoices"));
  const payables = useFetch(() => api.get("/cashier/payables"));
  const customers = useFetch(() => api.get("/sales/customers"));
  const summary = useFetch(
    () => api.get("/cashier/daily-summary", { params: { day: summaryDay } }),
    [summaryDay]
  );

  if (customers.loading) return null;

  const customerName = (id) => customers.data?.find((c) => c.id === id)?.name ?? id;

  const reloadAll = () => {
    invoices.reload();
    payables.reload();
    summary.reload();
  };

  const openCollectDialog = (invoice) => {
    setDialogError(null);
    setAmount(remaining(invoice));
    setCollectingFor(invoice);
  };

  const openPayDialog = (payable) => {
    setDialogError(null);
    setAmount(payableRemaining(payable));
    setPayingFor(payable);
  };

  const submitCollection = async (event) => {
    event.preventDefault();
    setDialogError(null);
    try {
      const { data } = await api.post(
        `/cashier/invoices/${collectingFor.id}/collect`,
        { amount }
      );
      setNotice(data.message);
      setError(null);
      setCollectingFor(null);
      setViewing(null);
      reloadAll();
    } catch (err) {
      setDialogError(apiMessage(err));
    }
  };

  const submitPayment = async (event) => {
    event.preventDefault();
    setDialogError(null);
    const path =
      payingFor.payable_type === "purchase_invoice"
        ? `/cashier/purchases/${payingFor.id}/pay`
        : `/cashier/expenses/${payingFor.id}/pay`;
    try {
      const { data } = await api.post(path, { amount });
      setNotice(data.message);
      setError(null);
      setPayingFor(null);
      reloadAll();
    } catch (err) {
      setDialogError(apiMessage(err));
    }
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-extrabold">الصندوق</h1>
      <Alert>{invoices.error || payables.error || error}</Alert>
      <Alert tone="success">{notice}</Alert>

      <Card
        title="ملخص الصندوق — لإغلاق يومك"
        actions={
          <Input
            type="date"
            value={summaryDay}
            onChange={(e) => setSummaryDay(e.target.value)}
            max={todayStr()}
          />
        }
      >
        {summary.loading || !summary.data ? null : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
              <Stat label="إجمالي المُحصّل (وارد)" value={money(summary.data.total_in)} tone="emerald" />
              <Stat label="إجمالي المصروف (صادر)" value={money(summary.data.total_out)} tone="rose" />
              <Stat
                label="الصافي"
                value={money(summary.data.net)}
                tone={Number(summary.data.net) >= 0 ? "emerald" : "rose"}
              />
              <Stat label="نقدي وارد" value={money(summary.data.cash_in)} tone="slate" />
              <Stat label="بطاقة واردة" value={money(summary.data.card_in)} tone="slate" />
              <Stat label="عدد الحركات" value={summary.data.movement_count} tone="slate" />
            </div>
            <Table
              columns={[
                {
                  key: "direction",
                  label: "الاتجاه",
                  render: (m) =>
                    m.direction === "in" ? (
                      <Badge tone="green">وارد ↓</Badge>
                    ) : (
                      <Badge tone="red">صادر ↑</Badge>
                    ),
                },
                {
                  key: "reference_type",
                  label: "النوع",
                  render: (m) => REFERENCE_TYPE_LABELS[m.reference_type] ?? m.reference_type,
                },
                { key: "reference_id", label: "رقم المستند" },
                {
                  key: "collected_at",
                  label: "الوقت",
                  render: (m) => new Date(m.collected_at).toLocaleTimeString("ar-EG"),
                },
                {
                  key: "method",
                  label: "طريقة الدفع",
                  render: (m) => (
                    <Badge tone={PAYMENT_METHOD_TONE[m.method]}>
                      {PAYMENT_METHOD_LABELS[m.method]}
                    </Badge>
                  ),
                },
                { key: "amount", label: "المبلغ", render: (m) => money(m.amount) },
              ]}
              rows={summary.data.movements}
              empty="لا توجد حركات صندوق في هذا اليوم."
            />
          </div>
        )}
      </Card>

      <Card title="فواتير بانتظار التحصيل (وارد)">
        {invoices.loading ? null : (
          <Table
            columns={[
              { key: "id", label: "#" },
              { key: "invoice_date", label: "التاريخ" },
              {
                key: "customer_id",
                label: "العميل",
                render: (r) => customerName(r.customer_id),
              },
              {
                key: "payment_method",
                label: "طريقة الدفع",
                render: (r) => (
                  <Badge tone={PAYMENT_METHOD_TONE[r.payment_method]}>
                    {PAYMENT_METHOD_LABELS[r.payment_method]}
                  </Badge>
                ),
              },
              {
                key: "paid_amount",
                label: "محصّل حتى الآن",
                render: (r) =>
                  Number(r.paid_amount) > 0 ? (
                    <Badge tone="amber">{money(r.paid_amount)}</Badge>
                  ) : (
                    "—"
                  ),
              },
              {
                key: "remaining",
                label: "المتبقي للتحصيل",
                sortValue: (r) => remaining(r),
                render: (r) => <b>{money(remaining(r))}</b>,
              },
              {
                key: "actions",
                label: "",
                sortable: false,
                render: (r) => (
                  <div className="flex gap-2">
                    <Button variant="secondary" onClick={() => setViewing(r)}>
                      عرض
                    </Button>
                    <Button onClick={() => openCollectDialog(r)}>💰 تحصيل</Button>
                  </div>
                ),
              },
            ]}
            rows={invoices.data}
            empty="لا توجد فواتير بانتظار التحصيل حالياً."
          />
        )}
      </Card>

      <Card title="مستحقات بانتظار السداد (صادر) — فواتير شراء ومصاريف">
        {payables.loading ? null : (
          <Table
            columns={[
              { key: "id", label: "#" },
              {
                key: "payable_type",
                label: "النوع",
                render: (r) => (
                  <Badge tone={r.payable_type === "expense" ? "amber" : "blue"}>
                    {PAYABLE_TYPE_LABELS[r.payable_type]}
                  </Badge>
                ),
              },
              { key: "date", label: "التاريخ" },
              { key: "description", label: "الوصف" },
              {
                key: "payment_method",
                label: "طريقة الدفع",
                render: (r) => (
                  <Badge tone={PAYMENT_METHOD_TONE[r.payment_method]}>
                    {PAYMENT_METHOD_LABELS[r.payment_method]}
                  </Badge>
                ),
              },
              {
                key: "paid_amount",
                label: "مسدّد حتى الآن",
                render: (r) =>
                  Number(r.paid_amount) > 0 ? (
                    <Badge tone="amber">{money(r.paid_amount)}</Badge>
                  ) : (
                    "—"
                  ),
              },
              {
                key: "remaining",
                label: "المتبقي للسداد",
                render: (r) => <b>{money(r.remaining)}</b>,
              },
              {
                key: "actions",
                label: "",
                sortable: false,
                render: (r) => <Button onClick={() => openPayDialog(r)}>💸 سداد</Button>,
              },
            ]}
            rows={payables.data}
            empty="لا توجد مستحقات بانتظار السداد حالياً."
          />
        )}
      </Card>

      <Modal
        open={!!viewing}
        title={viewing ? `فاتورة رقم ${viewing.id} — ${customerName(viewing.customer_id)}` : ""}
        onClose={() => setViewing(null)}
        wide
      >
        {viewing && (
          <div className="space-y-4">
            <Table
              columns={[
                { key: "product_id", label: "رقم الصنف" },
                { key: "batch_number", label: "التشغيلة" },
                { key: "quantity", label: "الكمية", render: (r) => qty(r.quantity) },
                { key: "unit_price", label: "سعر الوحدة", render: (r) => money(r.unit_price) },
                { key: "line_total", label: "الإجمالي", render: (r) => money(r.line_total) },
              ]}
              rows={viewing.lines}
            />
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="flex flex-wrap gap-6 text-sm font-bold">
                <span>قبل الضريبة: {money(viewing.subtotal)}</span>
                {viewing.taxes.map((t) => (
                  <span key={t.id}>
                    {t.name} ({t.rate}%): {money(t.amount)}
                  </span>
                ))}
                <span className="text-emerald-700">الإجمالي: {money(viewing.total)}</span>
                {Number(viewing.paid_amount) > 0 && (
                  <span className="text-amber-700">
                    محصّل: {money(viewing.paid_amount)} — المتبقي: {money(remaining(viewing))}
                  </span>
                )}
              </div>
              <Button onClick={() => openCollectDialog(viewing)}>💰 تحصيل الدفعة</Button>
            </div>
          </div>
        )}
      </Modal>

      <Modal
        open={!!collectingFor}
        title={collectingFor ? `تحصيل دفعة — فاتورة رقم ${collectingFor.id}` : ""}
        onClose={() => setCollectingFor(null)}
      >
        {collectingFor && (
          <form onSubmit={submitCollection} className="space-y-4">
            <Alert>{dialogError}</Alert>
            <div className="rounded-lg bg-slate-50 p-3 text-sm font-bold">
              <div>العميل: {customerName(collectingFor.customer_id)}</div>
              <div>الإجمالي: {money(collectingFor.total)}</div>
              {Number(collectingFor.paid_amount) > 0 && (
                <div>تم تحصيله سابقاً: {money(collectingFor.paid_amount)}</div>
              )}
              <div>المتبقي: {money(remaining(collectingFor))}</div>
            </div>
            <Input
              label="المبلغ المُستلم الآن"
              type="number"
              step="0.01"
              min="0.01"
              max={remaining(collectingFor)}
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              required
              autoFocus
            />
            <p className="text-xs text-slate-500">
              إذا كان المبلغ المُدخل أقل من المتبقي، تبقى الفاتورة بانتظار استكمال التحصيل
              ولا تُحرَّر لفريق التوزيع إلا بعد تحصيل كامل قيمتها.
            </p>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="secondary" onClick={() => setCollectingFor(null)}>
                إلغاء
              </Button>
              <Button type="submit">تأكيد التحصيل</Button>
            </div>
          </form>
        )}
      </Modal>

      <Modal
        open={!!payingFor}
        title={
          payingFor
            ? `سداد — ${PAYABLE_TYPE_LABELS[payingFor.payable_type]} رقم ${payingFor.id}`
            : ""
        }
        onClose={() => setPayingFor(null)}
      >
        {payingFor && (
          <form onSubmit={submitPayment} className="space-y-4">
            <Alert>{dialogError}</Alert>
            <div className="rounded-lg bg-slate-50 p-3 text-sm font-bold">
              <div>{payingFor.description}</div>
              <div>الإجمالي: {money(payingFor.total)}</div>
              {Number(payingFor.paid_amount) > 0 && (
                <div>تم سداده سابقاً: {money(payingFor.paid_amount)}</div>
              )}
              <div>المتبقي: {money(payingFor.remaining)}</div>
            </div>
            <Input
              label="المبلغ المدفوع الآن"
              type="number"
              step="0.01"
              min="0.01"
              max={payableRemaining(payingFor)}
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              required
              autoFocus
            />
            <p className="text-xs text-slate-500">
              إذا كان المبلغ المُدخل أقل من المتبقي، يبقى المستند بانتظار استكمال السداد.
            </p>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="secondary" onClick={() => setPayingFor(null)}>
                إلغاء
              </Button>
              <Button type="submit">تأكيد السداد</Button>
            </div>
          </form>
        )}
      </Modal>
    </div>
  );
}
