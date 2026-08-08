// The customer's financial view: opening balance, invoices, returns and
// payments down to the current balance, with each invoice's line detail
// available in a modal. This is the customer's own money data — it is the one
// place in the portal where amounts are allowed (their statement).
import { useState } from "react";
import { Alert, Badge, Button, Card, Loading, Modal, Table, money } from "../components/Ui";
import useFetch from "../hooks/useFetch";
import api, { apiMessage } from "../services/api";

export default function PortalStatement() {
  const { data, loading, error, reload } = useFetch(() => api.get("/portal/statement"));
  const [invoice, setInvoice] = useState(null);
  const [invoiceError, setInvoiceError] = useState(null);

  const showInvoice = async (id) => {
    setInvoice(null);
    setInvoiceError(null);
    try {
      const { data: res } = await api.get(`/portal/invoices/${id}`);
      setInvoice(res.data);
    } catch (err) {
      setInvoiceError(apiMessage(err));
    }
  };

  const PAYMENT_LABELS = { cash: "نقدي", card: "بطاقة", credit: "آجل" };
  const STATUS_LABELS = {
    draft: { label: "مسودة", tone: "slate" },
    posted: { label: "مثبتة", tone: "green" },
    cancelled: { label: "ملغاة", tone: "red" },
  };
  void STATUS_LABELS;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-extrabold">كشف الحساب والفواتير</h1>
          {data?.customer && (
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{data.customer.name}</p>
          )}
        </div>
        <Button variant="secondary" onClick={reload}>
          تحديث
        </Button>
      </div>

      <Alert>{error}</Alert>

      {loading ? (
        <Loading />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            {[
              { label: "رصيد افتتاحي", value: data?.opening_balance, tone: "slate" },
              { label: "إجمالي الفواتير", value: data?.total_invoices, tone: "sky" },
              { label: "المرتجعات", value: data?.total_returns, tone: "amber" },
              { label: "المسدد", value: data?.total_paid, tone: "emerald" },
            ].map((stat) => (
              <div
                key={stat.label}
                className="rounded-xl bg-white p-4 shadow-sm dark:bg-slate-900 dark:ring-1 dark:ring-slate-800"
              >
                <div className="text-sm font-bold text-slate-500 dark:text-slate-400">{stat.label}</div>
                <div className="mt-1 text-xl font-extrabold">{money(stat.value)}</div>
              </div>
            ))}
            <div className="col-span-2 rounded-xl bg-emerald-50 p-4 dark:bg-emerald-950/40 sm:col-span-4">
              <div className="text-sm font-bold text-emerald-700 dark:text-emerald-300">
                الرصيد المستحق عليك
              </div>
              <div className="mt-1 text-2xl font-extrabold text-emerald-800 dark:text-emerald-200">
                {money(data?.balance)}
              </div>
            </div>
          </div>

          <Card title="الفواتير">
            <Table
              columns={[
                { key: "id", label: "فاتورة #" },
                { key: "invoice_date", label: "التاريخ", sortValue: (r) => r.invoice_date },
                {
                  key: "payment_method",
                  label: "الدفع",
                  render: (r) => PAYMENT_LABELS[r.payment_method] || r.payment_method,
                },
{
                key: "payment_confirmed_at",
                label: "التحصيل",
                render: (r) =>
                  r.payment_confirmed_at ? (
                    <Badge tone="green">تم التحصيل</Badge>
                  ) : (
                    <Badge tone="amber">بانتظار التحصيل</Badge>
                  ),
              },
                { key: "total", label: "الإجمالي", render: (r) => money(r.total) },
                { key: "paid_amount", label: "المسدد", render: (r) => money(r.paid_amount) },
              ]}
              rows={data?.invoices || []}
              empty="لا توجد فواتير بعد."
              renderDetail={(r) => (
                <Button variant="secondary" onClick={() => showInvoice(r.id)}>
                  عرض التفاصيل
                </Button>
              )}
            />
          </Card>
        </>
      )}

      <Modal
        open={!!invoice || !!invoiceError}
        title={invoice ? `تفاصيل الفاتورة #${invoice.id}` : "الفاتورة"}
        onClose={() => {
          setInvoice(null);
          setInvoiceError(null);
        }}
        wide
      >
        <Alert>{invoiceError}</Alert>
        {invoice && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              <div className="rounded-lg bg-slate-50 p-3 text-center dark:bg-slate-800/60">
                <div className="text-xs font-bold text-slate-500 dark:text-slate-400">إجمالي قبل الضريبة</div>
                <div className="text-lg font-extrabold">{money(invoice.subtotal)}</div>
              </div>
              <div className="rounded-lg bg-slate-50 p-3 text-center dark:bg-slate-800/60">
                <div className="text-xs font-bold text-slate-500 dark:text-slate-400">الضريبة</div>
                <div className="text-lg font-extrabold">{money(invoice.vat_amount)}</div>
              </div>
              <div className="rounded-lg bg-emerald-50 p-3 text-center dark:bg-emerald-950/40">
                <div className="text-xs font-bold text-emerald-700 dark:text-emerald-400">الإجمالي المطلوب</div>
                <div className="text-lg font-extrabold text-emerald-800 dark:text-emerald-200">{money(invoice.total)}</div>
              </div>
            </div>
            <Table
              columns={[
                { key: "id", label: "#" },
                { key: "batch_number", label: "التشغيلة" },
                { key: "quantity", label: "الكمية" },
                { key: "unit_price", label: "سعر الوحدة", render: (r) => money(r.unit_price) },
                { key: "line_total", label: "الإجمالي", render: (r) => money(r.line_total) },
              ]}
              rows={invoice.lines || []}
              empty="لا توجد أصناف."
            />
            {(invoice.amount_due != null || invoice.returned_total > 0) && (
              <div className="flex flex-wrap justify-between gap-2 rounded-lg bg-amber-50 px-4 py-3 text-sm font-bold text-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
                <span>المتبقي بعد المرتجعات والمسددات: {money(invoice.amount_due)}</span>
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}