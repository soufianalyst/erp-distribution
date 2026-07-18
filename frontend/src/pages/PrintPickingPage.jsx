import { useNavigate, useParams } from "react-router-dom";
import { Button, Loading, qty } from "../components/Ui";
import useFetch from "../hooks/useFetch";
import api from "../services/api";

// Print-ready picking list (قائمة التجهيز) for a delivery trip.
export default function PrintPickingPage() {
  const { tripId } = useParams();
  const navigate = useNavigate();
  const picking = useFetch(() => api.get(`/delivery/trips/${tripId}/picking-list`), [tripId]);
  const warehouses = useFetch(() => api.get("/inventory/warehouses"));
  const company = useFetch(() => api.get("/settings/company"));

  if (picking.loading || warehouses.loading || company.loading) return <Loading />;
  if (picking.error) {
    return <div className="p-10 text-center font-bold text-rose-700">{picking.error}</div>;
  }

  const { trip, lines, invoice_count, total_quantity } = picking.data;
  // Every invoice on a trip is loaded from the trip's own warehouse (enforced at assignment).
  const warehouseName =
    warehouses.data?.find((w) => w.id === trip.warehouse_id)?.name ?? "غير محدد";

  return (
    <div className="min-h-screen bg-slate-200 py-8 print:bg-white print:py-0">
      <div className="mx-auto mb-4 flex max-w-[210mm] justify-between gap-2 print:hidden">
        <Button variant="secondary" onClick={() => navigate("/delivery")}>
          ← العودة إلى الرحلات
        </Button>
        <Button onClick={() => window.print()}>🖨️ طباعة</Button>
      </div>

      <div className="mx-auto max-w-[210mm] bg-white p-10 shadow print:max-w-none print:p-0 print:shadow-none">
        <header className="flex items-start justify-between border-b-4 border-slate-800 pb-4">
          <div>
            <h1 className="text-2xl font-extrabold text-slate-900">{company.data.name}</h1>
            {company.data.tagline && (
              <div className="mt-1 text-sm text-slate-600">{company.data.tagline}</div>
            )}
          </div>
          <div className="rounded-lg border-2 border-slate-800 px-6 py-3 text-center">
            <div className="text-lg font-extrabold">قائمة تجهيز</div>
            <div className="mt-1 text-sm font-bold text-slate-600">
              رحلة: {trip.id} — التاريخ: {trip.trip_date}
            </div>
          </div>
        </header>

        <section className="mt-5 grid grid-cols-3 gap-4 text-sm">
          <div className="rounded-lg bg-slate-50 p-3 print:border print:border-slate-300 print:bg-white">
            <div className="font-extrabold text-slate-500">السائق</div>
            <div className="font-bold">{trip.driver_name}</div>
            {trip.vehicle && <div className="text-slate-600">{trip.vehicle}</div>}
          </div>
          <div className="rounded-lg bg-slate-50 p-3 print:border print:border-slate-300 print:bg-white">
            <div className="font-extrabold text-slate-500">عدد الطلبيات</div>
            <div className="font-bold">{invoice_count} فاتورة</div>
          </div>
          <div className="rounded-lg bg-slate-50 p-3 print:border print:border-slate-300 print:bg-white">
            <div className="font-extrabold text-slate-500">إجمالي الوحدات</div>
            <div className="font-bold">{qty(total_quantity)}</div>
          </div>
        </section>

        <div className="mt-6">
          <div className="mb-1 rounded-t-lg bg-slate-700 px-3 py-1.5 text-sm font-extrabold text-white">
            🏬 مستودع: {warehouseName}
          </div>
          <table className="w-full border-collapse text-right text-sm">
            <thead>
              <tr className="bg-slate-800 text-white">
                <th className="border border-slate-800 px-3 py-2">#</th>
                <th className="border border-slate-800 px-3 py-2">الصنف</th>
                <th className="border border-slate-800 px-3 py-2">التشغيلة</th>
                <th className="border border-slate-800 px-3 py-2">الكمية</th>
                <th className="border border-slate-800 px-3 py-2">الوحدة</th>
                <th className="border border-slate-800 px-3 py-2">تم التحميل ✓</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((line, index) => (
                <tr key={`${line.product_id}-${line.batch_number}`}>
                  <td className="border border-slate-300 px-3 py-2">{index + 1}</td>
                  <td className="border border-slate-300 px-3 py-2 font-bold">{line.product_name}</td>
                  <td className="border border-slate-300 px-3 py-2">{line.batch_number}</td>
                  <td className="border border-slate-300 px-3 py-2 font-bold">{qty(line.quantity)}</td>
                  <td className="border border-slate-300 px-3 py-2">{line.base_unit_name}</td>
                  <td className="border border-slate-300 px-3 py-2"></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <footer className="mt-14 grid grid-cols-2 gap-10 text-center text-sm font-bold text-slate-600">
          <div className="border-t-2 border-dotted border-slate-400 pt-2">توقيع أمين المستودع</div>
          <div className="border-t-2 border-dotted border-slate-400 pt-2">توقيع السائق</div>
        </footer>
      </div>
    </div>
  );
}
