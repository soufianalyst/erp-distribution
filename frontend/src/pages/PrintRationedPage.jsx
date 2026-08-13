import { useNavigate, useParams } from "react-router-dom";

import { Button, Loading, money, qty } from "../components/Ui";
import useFetch from "../hooks/useFetch";
import api from "../services/api";

// Print-ready A4 view of a المواد المقننة register — the monthly declaration.
//
// Laid out like the sales invoice on purpose: it is handed to the same people, and a
// document that looks unlike everything else the company issues invites questions about
// whether it is genuine. But it is *not* an invoice, and the difference has to survive
// being photocopied: the title says بيان مواد مقننة, the number is prefixed so it can
// never be read as a sales-invoice number, and a line under the total says in words
// that the goods were already billed on their own invoices. Without that line a client
// could reasonably pay this document twice.
//
// Every figure here is read from the register, which reads through to the live invoice
// lines. Reprinting after a correction produces the corrected declaration rather than
// the one that was true the first time it was printed.
export default function PrintRationedPage() {
  const { recordId } = useParams();
  const navigate = useNavigate();
  const register = useFetch(() => api.get(`/sales/rationed/${recordId}`), [recordId]);
  const company = useFetch(() => api.get("/settings/company"));

  if (register.loading || company.loading) return <Loading />;
  if (register.error) {
    return (
      <div className="p-10 text-center font-bold text-rose-700">{register.error}</div>
    );
  }

  const reg = register.data;
  const co = company.data;
  const period = reg.closed_at
    ? `${reg.opened_at.slice(0, 10)} — ${reg.closed_at.slice(0, 10)}`
    : `${reg.opened_at.slice(0, 10)} — حتى تاريخه`;

  return (
    <div className="min-h-screen bg-slate-200 py-8 print:bg-white print:py-0">
      <div className="mx-auto mb-4 flex max-w-[210mm] justify-between gap-2 print:hidden">
        <Button variant="secondary" onClick={() => navigate("/customers")}>
          ← العودة إلى العملاء
        </Button>
        <Button onClick={() => window.print()}>🖨️ طباعة</Button>
      </div>

      <div className="mx-auto max-w-[210mm] bg-white p-10 text-slate-900 shadow print:max-w-none print:p-0 print:shadow-none">
        <header className="flex items-start justify-between border-b-4 border-slate-800 pb-4">
          <div>
            <h1 className="text-2xl font-extrabold text-slate-900">{co.name}</h1>
            {co.tagline && <div className="mt-1 text-sm text-slate-600">{co.tagline}</div>}
            {co.address && <div className="text-sm text-slate-600">{co.address}</div>}
            {co.phone && <div className="text-sm text-slate-600">هاتف: {co.phone}</div>}
            {co.tax_number && (
              <div className="text-sm text-slate-600">الرقم الضريبي: {co.tax_number}</div>
            )}
          </div>
          <div className="rounded-lg border-2 border-slate-800 px-6 py-3 text-center">
            <div className="text-lg font-extrabold">بيان مواد مقننة</div>
            {/* Prefixed so this number cannot be mistaken for a sales-invoice number
                by anyone reading the two documents side by side. */}
            <div className="mt-1 text-sm font-bold text-slate-600">
              رقم: ق-{reg.record_id}
            </div>
            <div className="text-sm font-bold text-slate-600">الفترة: {period}</div>
            <div className="mt-1 text-xs font-bold text-slate-500">
              {reg.closed_at ? "بيان مقفل" : "بيان مبدئي — السجل ما زال مفتوحاً"}
            </div>
          </div>
        </header>

        <section className="mt-5 grid grid-cols-2 gap-6 text-sm">
          <div className="rounded-lg bg-slate-50 p-4 print:border print:border-slate-300 print:bg-white">
            <div className="mb-1 font-extrabold text-slate-500">العميل</div>
            <div className="text-base font-extrabold">{reg.customer_name}</div>
            {reg.customer_phone && (
              <div className="text-slate-600">هاتف: {reg.customer_phone}</div>
            )}
          </div>
          <div className="rounded-lg bg-slate-50 p-4 print:border print:border-slate-300 print:bg-white">
            <div className="mb-1 font-extrabold text-slate-500">ملخص البيان</div>
            <div>
              عدد الأسطر: <b>{reg.line_count}</b>
            </div>
            <div>
              إجمالي الكميات: <b>{qty(reg.total_quantity)}</b>
            </div>
            <div>
              تاريخ الإصدار: <b>{new Date().toISOString().slice(0, 10)}</b>
            </div>
          </div>
        </section>

        <div className="mt-6">
          <table className="w-full border-collapse text-right text-sm">
            <thead>
              <tr className="bg-slate-800 text-white">
                <th className="border border-slate-800 px-3 py-2">#</th>
                <th className="border border-slate-800 px-3 py-2">الصنف</th>
                <th className="border border-slate-800 px-3 py-2">الفاتورة</th>
                <th className="border border-slate-800 px-3 py-2">التاريخ</th>
                <th className="border border-slate-800 px-3 py-2">الكمية</th>
                <th className="border border-slate-800 px-3 py-2">الوحدة</th>
                <th className="border border-slate-800 px-3 py-2">سعر الوحدة</th>
                <th className="border border-slate-800 px-3 py-2">الإجمالي</th>
              </tr>
            </thead>
            <tbody>
              {reg.entries.map((entry, index) => (
                <tr key={entry.line_id}>
                  <td className="border border-slate-300 px-3 py-2">{index + 1}</td>
                  <td className="border border-slate-300 px-3 py-2 font-bold">
                    {entry.product_name}
                  </td>
                  <td className="border border-slate-300 px-3 py-2">
                    {entry.invoice_reference}
                  </td>
                  <td className="border border-slate-300 px-3 py-2">
                    {entry.invoice_date}
                  </td>
                  {/* The net quantity: a credit note against the invoice reduces what
                      the client actually kept, and the declaration must say what was
                      kept, not what first left the warehouse. */}
                  <td className="border border-slate-300 px-3 py-2">
                    {qty(entry.net_quantity)}
                    {Number(entry.returned_quantity) > 0 && (
                      <span className="text-xs text-slate-500">
                        {" "}
                        (مرتجع {qty(entry.returned_quantity)})
                      </span>
                    )}
                  </td>
                  <td className="border border-slate-300 px-3 py-2">{entry.unit_name}</td>
                  <td className="border border-slate-300 px-3 py-2">
                    {money(entry.unit_price)}
                  </td>
                  <td className="border border-slate-300 px-3 py-2 font-bold">
                    {money(entry.net_total)}
                  </td>
                </tr>
              ))}
              {!reg.entries.length && (
                <tr>
                  <td
                    colSpan={8}
                    className="border border-slate-300 px-3 py-6 text-center font-bold text-slate-500"
                  >
                    لا توجد مواد مقننة في هذا السجل.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="mt-4 flex justify-start">
          <table className="w-80 border-collapse text-sm">
            <tbody>
              <tr>
                <td className="border border-slate-300 bg-slate-50 px-3 py-2 font-bold print:bg-white">
                  قيمة المواد
                </td>
                <td className="border border-slate-300 px-3 py-2">
                  {money(reg.total_value)}
                </td>
              </tr>
              {reg.taxes.map((tax) => (
                <tr key={tax.name}>
                  <td className="border border-slate-300 bg-slate-50 px-3 py-2 font-bold print:bg-white">
                    {tax.name} ({tax.rate}%)
                  </td>
                  <td className="border border-slate-300 px-3 py-2">{money(tax.amount)}</td>
                </tr>
              ))}
              <tr className="text-base font-extrabold">
                <td className="border-2 border-slate-800 bg-slate-800 px-3 py-2 text-white">
                  الإجمالي
                </td>
                <td className="border-2 border-slate-800 px-3 py-2">
                  {money(reg.grand_total)}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        {/* The one sentence that keeps this document from being paid. It is printed,
            not shown on screen only, because the paper is what leaves the building. */}
        <div className="mt-4 rounded-lg border-2 border-slate-800 p-3 text-sm font-bold">
          هذا بيان بالمواد المقننة التي استلمها العميل، وليس فاتورة ولا مطالبة مالية.
          المواد الواردة فيه محسوبة ومحصّلة على فواتير البيع المذكورة أمام كل سطر.
        </div>

        {reg.notes && (
          <div className="mt-3 text-sm">
            <b>ملاحظات:</b> {reg.notes}
          </div>
        )}

        <footer className="mt-14 grid grid-cols-2 gap-10 text-center text-sm font-bold text-slate-600">
          <div className="border-t-2 border-dotted border-slate-400 pt-2">
            توقيع المسؤول
          </div>
          <div className="border-t-2 border-dotted border-slate-400 pt-2">
            توقيع العميل
          </div>
        </footer>
      </div>
    </div>
  );
}
