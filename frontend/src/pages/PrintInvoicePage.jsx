import { useNavigate, useParams } from "react-router-dom";
import { Button, Loading, money, qty } from "../components/Ui";
import useFetch from "../hooks/useFetch";
import api from "../services/api";

// Print-ready A4 view of a sales invoice; opened in a new tab from the sales page.
export default function PrintInvoicePage() {
  const { invoiceId } = useParams();
  const navigate = useNavigate();
  const invoice = useFetch(() => api.get(`/sales/invoices/${invoiceId}`), [invoiceId]);
  const customers = useFetch(() => api.get("/sales/customers"));
  const products = useFetch(() => api.get("/inventory/products"));
  const warehouses = useFetch(() => api.get("/inventory/warehouses"));

  if (invoice.loading || customers.loading || products.loading || warehouses.loading) return <Loading />;
  if (invoice.error) {
    return <div className="p-10 text-center font-bold text-rose-700">{invoice.error}</div>;
  }

  const inv = invoice.data;
  const customer = customers.data?.find((c) => c.id === inv.customer_id);
  const productOf = (id) => products.data?.find((p) => p.id === id);
  const warehouseOf = (id) => warehouses.data?.find((w) => w.id === id);

  // Group lines by warehouse for delivery/pickup efficiency.
  const linesByWarehouse = {};
  inv.lines.forEach((line) => {
    const wid = line.warehouse_id;
    if (!linesByWarehouse[wid]) linesByWarehouse[wid] = [];
    linesByWarehouse[wid].push(line);
  });
  const warehouseIds = Object.keys(linesByWarehouse).map(Number);

  return (
    <div className="min-h-screen bg-slate-200 py-8 print:bg-white print:py-0">
      <div className="mx-auto mb-4 flex max-w-[210mm] justify-between gap-2 print:hidden">
        <Button variant="secondary" onClick={() => navigate("/sales")}>
          ← العودة إلى الفواتير
        </Button>
        <Button onClick={() => window.print()}>🖨️ طباعة</Button>
      </div>

      <div className="mx-auto max-w-[210mm] bg-white p-10 shadow print:max-w-none print:p-0 print:shadow-none">
        {/* Header */}
        <header className="flex items-start justify-between border-b-4 border-slate-800 pb-4">
          <div>
            <h1 className="text-2xl font-extrabold text-slate-900">شركة التوزيع الغذائي</h1>
            <div className="mt-1 text-sm text-slate-600">بيع وتوزيع المواد الغذائية بالجملة</div>
          </div>
          <div className="rounded-lg border-2 border-slate-800 px-6 py-3 text-center">
            <div className="text-lg font-extrabold">فاتورة مبيعات</div>
            <div className="mt-1 text-sm font-bold text-slate-600">
              رقم: {inv.id} — التاريخ: {inv.invoice_date}
            </div>
          </div>
        </header>

        {/* Parties */}
        <section className="mt-5 grid grid-cols-2 gap-6 text-sm">
          <div className="rounded-lg bg-slate-50 p-4 print:border print:border-slate-300 print:bg-white">
            <div className="mb-1 font-extrabold text-slate-500">العميل</div>
            <div className="text-base font-extrabold">{customer?.name ?? inv.customer_id}</div>
            {customer?.phone && <div className="text-slate-600">هاتف: {customer.phone}</div>}
            {customer?.address && <div className="text-slate-600">{customer.address}</div>}
          </div>
          <div className="rounded-lg bg-slate-50 p-4 print:border print:border-slate-300 print:bg-white">
            <div className="mb-1 font-extrabold text-slate-500">تفاصيل الدفع</div>
            <div>
              طريقة الدفع:{" "}
              <b>{inv.payment_method === "cash" ? "نقدي" : "آجل (على الحساب)"}</b>
            </div>
            <div>
              طريقة الاستلام:{" "}
              <b>{inv.fulfillment === "pickup" ? "استلام من المستودع" : "توصيل إلى العميل"}</b>
            </div>
            <div>
              المسدد: <b>{money(inv.paid_amount)}</b>
            </div>
          </div>
        </section>

        {/* Lines grouped by warehouse */}
        {warehouseIds.map((wid, groupIndex) => {
          const wh = warehouseOf(wid);
          const lines = linesByWarehouse[wid];
          const groupSubtotal = lines.reduce((s, l) => s + Number(l.line_total), 0);
          return (
            <div key={wid} className={groupIndex > 0 ? "mt-8" : "mt-6"}>
              <div className="mb-2 rounded bg-slate-700 px-3 py-1.5 text-sm font-extrabold text-white print:bg-slate-300 print:text-slate-900">
                المستودع: {wh?.name ?? wid}
              </div>
              <table className="w-full border-collapse text-right text-sm">
                <thead>
                  <tr className="bg-slate-800 text-white">
                    <th className="border border-slate-800 px-3 py-2">#</th>
                    <th className="border border-slate-800 px-3 py-2">الصنف</th>
                    <th className="border border-slate-800 px-3 py-2">التشغيلية</th>
                    <th className="border border-slate-800 px-3 py-2">الكمية</th>
                    <th className="border border-slate-800 px-3 py-2">الوحدة</th>
                    <th className="border border-slate-800 px-3 py-2">سعر الوحدة</th>
                    <th className="border border-slate-800 px-3 py-2">الإجمالي</th>
                  </tr>
                </thead>
                <tbody>
                  {lines.map((line, index) => {
                    const product = productOf(line.product_id);
                    return (
                      <tr key={line.id}>
                        <td className="border border-slate-300 px-3 py-2">{index + 1}</td>
                        <td className="border border-slate-300 px-3 py-2 font-bold">
                          {product?.name ?? line.product_id}
                        </td>
                        <td className="border border-slate-300 px-3 py-2">{line.batch_number}</td>
                        <td className="border border-slate-300 px-3 py-2">{qty(line.quantity)}</td>
                        <td className="border border-slate-300 px-3 py-2">
                          {product?.base_unit_name ?? ""}
                        </td>
                        <td className="border border-slate-300 px-3 py-2">{money(line.unit_price)}</td>
                        <td className="border border-slate-300 px-3 py-2 font-bold">
                          {money(line.line_total)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
                <tfoot>
                  <tr className="bg-slate-100 font-bold">
                    <td colSpan={6} className="border border-slate-300 px-3 py-2 text-left">
                      المجموع — {wh?.name ?? wid}
                    </td>
                    <td className="border border-slate-300 px-3 py-2">{money(groupSubtotal)}</td>
                  </tr>
                </tfoot>
              </table>
            </div>
          );
        })}

        {/* Totals */}
        <div className="mt-4 flex justify-start">
          <table className="w-72 border-collapse text-sm">
            <tbody>
              <tr>
                <td className="border border-slate-300 bg-slate-50 px-3 py-2 font-bold print:bg-white">
                  المجموع قبل الضريبة
                </td>
                <td className="border border-slate-300 px-3 py-2">{money(inv.subtotal)}</td>
              </tr>
              {(inv.tax_lines && inv.tax_lines.length > 0
                ? inv.tax_lines
                : [{ id: "vat", tax_type: { name: "ضريبة القيمة المضافة" }, rate_at_time: "0", amount: inv.vat_amount }]
              ).map((tl) => (
                <tr key={tl.id}>
                  <td className="border border-slate-300 bg-slate-50 px-3 py-2 font-bold print:bg-white">
                    {tl.tax_type?.name ?? "ضريبة"}
                    {Number(tl.rate_at_time) > 0
                      ? ` (${(Number(tl.rate_at_time) * 100).toFixed(1)}%)`
                      : ""}
                  </td>
                  <td className="border border-slate-300 px-3 py-2">{money(tl.amount)}</td>
                </tr>
              ))}
              <tr className="text-base font-extrabold">
                <td className="border-2 border-slate-800 bg-slate-800 px-3 py-2 text-white">
                  الإجمالي المستحق
                </td>
                <td className="border-2 border-slate-800 px-3 py-2">{money(inv.total)}</td>
              </tr>
            </tbody>
          </table>
        </div>

        {inv.notes && (
          <div className="mt-4 text-sm">
            <b>ملاحظات:</b> {inv.notes}
          </div>
        )}

        {/* Signatures */}
        <footer className="mt-14 grid grid-cols-3 gap-10 text-center text-sm font-bold text-slate-600">
          <div className="border-t-2 border-dotted border-slate-400 pt-2">توقيع البائع</div>
          <div className="border-t-2 border-dotted border-slate-400 pt-2">توقيع السائق</div>
          <div className="border-t-2 border-dotted border-slate-400 pt-2">توقيع المستلم</div>
        </footer>
      </div>
    </div>
  );
}
