// The customer's own invoices, and the statement behind them.
//
// These are the only portal screens that carry money, and they carry it because it
// is the customer's own: what they were charged, and what is still owed. What the
// goods cost us is on the same database row and never appears here.
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Alert, Badge, Loading, Modal, money, qty } from "../components/Ui";
import useFetch from "../hooks/useFetch";
import portalApi, { portalMessage } from "../services/portalApi";

function InvoiceDetail({ invoiceId, onClose }) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    portalApi
      .get(`/portal/invoices/${invoiceId}`)
      .then(({ data }) => !cancelled && setDetail(data.data))
      .catch((err) => !cancelled && setError(portalMessage(err)));
    return () => {
      cancelled = true;
    };
  }, [invoiceId]);

  return (
    <Modal open title={`فاتورة #${invoiceId}`} onClose={onClose} guardUnsaved={false}>
      <Alert>{error}</Alert>
      {!detail && !error ? <Loading /> : null}
      {detail ? (
        <div className="space-y-4">
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {detail.invoice_date}
          </p>
          <ul className="divide-y divide-slate-100 text-sm dark:divide-slate-700">
            {detail.lines.map((line, index) => (
              <li key={index} className="flex justify-between gap-2 py-2">
                <span className="min-w-0">
                  <span className="block truncate text-slate-700 dark:text-slate-200">
                    {line.product_name}
                  </span>
                  <span className="text-xs text-slate-500 dark:text-slate-400">
                    {qty(line.quantity)} × {money(line.unit_price)}
                  </span>
                </span>
                <span className="shrink-0 font-bold text-slate-800 dark:text-slate-100">
                  {money(line.line_total)}
                </span>
              </li>
            ))}
          </ul>
          <dl className="space-y-1 border-t border-slate-200 pt-3 text-sm dark:border-slate-700">
            <div className="flex justify-between">
              <dt className="text-slate-500 dark:text-slate-400">الإجمالي قبل الضريبة</dt>
              <dd className="text-slate-700 dark:text-slate-200">{money(detail.subtotal)}</dd>
            </div>
            {Number(detail.discount_amount) > 0 ? (
              <div className="flex justify-between">
                <dt className="text-slate-500 dark:text-slate-400">الخصم</dt>
                <dd className="text-slate-700 dark:text-slate-200">
                  {money(detail.discount_amount)}
                </dd>
              </div>
            ) : null}
            {detail.taxes.map((tax, index) => (
              <div key={index} className="flex justify-between">
                <dt className="text-slate-500 dark:text-slate-400">
                  {tax.name} ({tax.rate}%)
                </dt>
                <dd className="text-slate-700 dark:text-slate-200">{money(tax.amount)}</dd>
              </div>
            ))}
            <div className="flex justify-between border-t border-slate-200 pt-2 text-base font-bold dark:border-slate-700">
              <dt className="text-slate-700 dark:text-slate-200">الإجمالي</dt>
              <dd className="text-slate-900 dark:text-slate-50">{money(detail.total)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500 dark:text-slate-400">المدفوع</dt>
              <dd className="text-slate-700 dark:text-slate-200">
                {money(detail.paid_amount)}
              </dd>
            </div>
            <div className="flex justify-between font-bold">
              <dt className="text-slate-700 dark:text-slate-200">المتبقي</dt>
              <dd
                className={
                  detail.is_settled
                    ? "text-emerald-700 dark:text-emerald-300"
                    : "text-amber-700 dark:text-amber-300"
                }
              >
                {money(detail.amount_due)}
              </dd>
            </div>
          </dl>
        </div>
      ) : null}
    </Modal>
  );
}

export function PortalInvoices() {
  const invoices = useFetch(() => portalApi.get("/portal/invoices"));
  // Arriving from "view the invoice" on an order opens it straight away.
  const [params, setParams] = useSearchParams();
  const opened = params.get("open");

  if (invoices.loading) return <Loading />;

  return (
    <div className="space-y-2">
      <Alert>{invoices.error}</Alert>
      {!invoices.data?.length ? (
        <p className="py-10 text-center text-sm text-slate-400">لا توجد فواتير بعد.</p>
      ) : null}
      {(invoices.data ?? []).map((invoice) => (
        <button
          key={invoice.id}
          onClick={() => setParams({ open: String(invoice.id) })}
          className="flex w-full items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-3 text-start transition hover:border-emerald-300 dark:border-slate-700 dark:bg-slate-800"
        >
          <span>
            <span className="block text-sm font-bold text-slate-800 dark:text-slate-100">
              فاتورة #{invoice.id}
            </span>
            <span className="text-xs text-slate-500 dark:text-slate-400">
              {invoice.invoice_date}
            </span>
          </span>
          <span className="shrink-0 text-end">
            <span className="block text-sm font-bold text-slate-800 dark:text-slate-100">
              {money(invoice.total)}
            </span>
            {invoice.is_settled ? (
              <Badge tone="green">مسددة</Badge>
            ) : (
              <Badge tone="amber">{money(invoice.amount_due)} متبقٍ</Badge>
            )}
          </span>
        </button>
      ))}
      {opened ? (
        <InvoiceDetail invoiceId={opened} onClose={() => setParams({})} />
      ) : null}
    </div>
  );
}

export function PortalStatement() {
  const statement = useFetch(() => portalApi.get("/portal/statement"));
  if (statement.loading) return <Loading />;
  const data = statement.data;

  const rows = [
    ["رصيد افتتاحي", data?.opening_balance],
    ["إجمالي الفواتير", data?.total_invoices],
    ["إجمالي المرتجعات", data?.total_returns],
    ["إجمالي المدفوع", data?.total_paid],
  ];

  return (
    <div className="space-y-4">
      <Alert>{statement.error}</Alert>
      <section className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
        <dl className="space-y-2 text-sm">
          {rows.map(([label, value]) => (
            <div key={label} className="flex justify-between">
              <dt className="text-slate-500 dark:text-slate-400">{label}</dt>
              <dd className="text-slate-700 dark:text-slate-200">{money(value ?? 0)}</dd>
            </div>
          ))}
          <div className="flex justify-between border-t border-slate-200 pt-2 text-base font-bold dark:border-slate-700">
            <dt className="text-slate-700 dark:text-slate-200">الرصيد</dt>
            <dd className="text-slate-900 dark:text-slate-50">{money(data?.balance ?? 0)}</dd>
          </div>
        </dl>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
        <h2 className="mb-3 text-sm font-bold text-slate-700 dark:text-slate-200">
          الدفعات المستلمة
        </h2>
        {data?.payments?.length ? (
          <ul className="divide-y divide-slate-100 text-sm dark:divide-slate-700">
            {data.payments.map((payment) => (
              <li key={payment.id} className="flex justify-between py-2">
                <span className="text-slate-600 dark:text-slate-300">
                  {payment.payment_date}
                </span>
                <span className="font-bold text-slate-800 dark:text-slate-100">
                  {money(payment.amount)}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="py-2 text-sm text-slate-400">لا توجد دفعات مسجلة.</p>
        )}
      </section>

      {data?.returns?.length ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
          <h2 className="mb-3 text-sm font-bold text-slate-700 dark:text-slate-200">
            المرتجعات
          </h2>
          <ul className="divide-y divide-slate-100 text-sm dark:divide-slate-700">
            {data.returns.map((item) => (
              <li key={item.id} className="flex justify-between py-2">
                <span className="text-slate-600 dark:text-slate-300">
                  مرتجع #{item.id}
                  {item.invoice_id ? ` — فاتورة #${item.invoice_id}` : ""}
                </span>
                <span className="font-bold text-slate-800 dark:text-slate-100">
                  {money(item.total)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
