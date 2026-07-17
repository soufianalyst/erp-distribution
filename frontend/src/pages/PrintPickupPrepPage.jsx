import { useNavigate, useParams } from "react-router-dom";
import { Button, Loading, qty } from "../components/Ui";
import useFetch from "../hooks/useFetch";
import api from "../services/api";

// Print-ready prep sheet (قسيمة تجهيز) for a single warehouse-pickup invoice — no prices.
export default function PrintPickupPrepPage() {
  const { invoiceId } = useParams();
  const navigate = useNavigate();
  const prep = useFetch(
    () => api.get(`/delivery/invoices/${invoiceId}/prep`),
    [invoiceId]
  );
  const warehouses = useFetch(() => api.get("/inventory/warehouses"));

  if (prep.loading || warehouses.loading) return <Loading />;
  if (prep.error) {
    return <div className="p-10 text-center font-bold text-rose-700">{prep.error}</div>;
  }

  const { invoice_id, invoice_date, customer_name, lines } = prep.data;
  const totalQuantity = lines.reduce((sum, l) => sum + Number(l.quantity), 0);
  const warehouseName = (id) =>
    warehouses.data?.find((w) => w.id === id)?.name ?? "غير محدد";

  // Group by warehouse: a pickup invoice can span more than one location.
  const groups = [];
  for (const line of lines) {
    let group = groups.find((g) => g.warehouseId === line.warehouse_id);
    if (!group) {
      group = { warehouseId: line.warehouse_id, lines: [] };
      groups.push(group);
    }
    group.lines.push(line);
  }

  return (
    <div className="min-h-screen bg-slate-200 py-8 print:bg-white print:py-0">
      <div className="mx-auto mb-4 flex max-w-[210mm] justify-between gap-2 print:hidden">
        <Button variant="secondary" onClick={() => navigate("/delivery")}>
          ← العودة للتوزيع والتسليم
        </Button>
        <Button onClick={() => window.print()}>🖨️ طباعة</Button>
      </div>

      <div className="mx-auto max-w-[210mm] bg-white p-10 shadow print:max-w-none print:p-0 print:shadow-none">
        <header className="flex items-start justify-between border-b-4 border-slate-800 pb-4">
          <div>
            <h1 className="text-2xl font-extrabold text-slate-900">شركة التوزيع الغذائي</h1>
            <div className="mt-1 text-sm text-slate-600">بيع وتوزيع المواد الغذائية بالجملة</div>
          </div>
          <div className="rounded-lg border-2 border-slate-800 px-6 py-3 text-center">
            <div className="text-lg font-extrabold">قسيمة تجهيز — استلام من المستودع</div>
            <div className="mt-1 text-sm font-bold text-slate-600">
              فاتورة: {invoice_id} — التاريخ: {invoice_date}
            </div>
          </div>
        </header>

        <section className="mt-5 grid grid-cols-3 gap-4 text-sm">
          <div className="rounded-lg bg-slate-50 p-3 print:border print:border-slate-300 print:bg-white">
            <div className="font-extrabold text-slate-500">العميل</div>
            <div className="font-bold">{customer_name}</div>
          </div>
          <div className="rounded-lg bg-slate-50 p-3 print:border print:border-slate-300 print:bg-white">
            <div className="font-extrabold text-slate-500">عدد الأصناف</div>
            <div className="font-bold">{lines.length}</div>
          </div>
          <div className="rounded-lg bg-slate-50 p-3 print:border print:border-slate-300 print:bg-white">
            <div className="font-extrabold text-slate-500">إجمالي الوحدات</div>
            <div className="font-bold">{qty(totalQuantity)}</div>
          </div>
        </section>

        {groups.map((group) => (
          <div key={group.warehouseId ?? "unknown"} className="mt-6">
            <div className="mb-1 rounded-t-lg bg-slate-700 px-3 py-1.5 text-sm font-extrabold text-white">
              🏬 مستودع: {warehouseName(group.warehouseId)}
            </div>
            <table className="w-full border-collapse text-right text-sm">
              <thead>
                <tr className="bg-slate-800 text-white">
                  <th className="border border-slate-800 px-3 py-2">#</th>
                  <th className="border border-slate-800 px-3 py-2">الصنف</th>
                  <th className="border border-slate-800 px-3 py-2">التشغيلة</th>
                  <th className="border border-slate-800 px-3 py-2">الكمية</th>
                  <th className="border border-slate-800 px-3 py-2">الوحدة</th>
                  <th className="border border-slate-800 px-3 py-2">تم التجهيز ✓</th>
                </tr>
              </thead>
              <tbody>
                {group.lines.map((line, index) => (
                  <tr key={`${line.product_name}-${line.batch_number}`}>
                    <td className="border border-slate-300 px-3 py-2">{index + 1}</td>
                    <td className="border border-slate-300 px-3 py-2 font-bold">{line.product_name}</td>
                    <td className="border border-slate-300 px-3 py-2">{line.batch_number}</td>
                    <td className="border border-slate-300 px-3 py-2 font-bold">{qty(line.quantity)}</td>
                    <td className="border border-slate-300 px-3 py-2">{line.unit}</td>
                    <td className="border border-slate-300 px-3 py-2"></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}

        <footer className="mt-14 grid grid-cols-2 gap-10 text-center text-sm font-bold text-slate-600">
          <div className="border-t-2 border-dotted border-slate-400 pt-2">توقيع أمين المستودع</div>
          <div className="border-t-2 border-dotted border-slate-400 pt-2">توقيع العميل عند الاستلام</div>
        </footer>
      </div>
    </div>
  );
}
