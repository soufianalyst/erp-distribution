import { useNavigate, useParams } from "react-router-dom";
import { Button, Loading, money, qty } from "../components/Ui";
import useFetch from "../hooks/useFetch";
import api from "../services/api";

const REASON_LABELS = {
  expired: "منتهي الصلاحية",
  damaged: "تالف",
  spoiled: "فاسد",
  count_shortfall: "نقص عند الجرد",
  other: "أخرى",
};

// Print-ready write-off voucher (محضر إتلاف) for a single stock adjustment.
export default function PrintAdjustmentPage() {
  const { adjustmentId } = useParams();
  const navigate = useNavigate();
  const adjustment = useFetch(
    () => api.get(`/inventory/stock/adjustments/${adjustmentId}`),
    [adjustmentId]
  );
  const company = useFetch(() => api.get("/settings/company"));

  if (adjustment.loading || company.loading) return <Loading />;
  if (adjustment.error) {
    return (
      <div className="p-10 text-center font-bold text-rose-700">{adjustment.error}</div>
    );
  }

  const a = adjustment.data;
  const cancelled = a.status === "cancelled";

  return (
    <div className="min-h-screen bg-slate-200 py-8 print:bg-white print:py-0">
      <div className="mx-auto mb-4 flex max-w-[210mm] justify-between gap-2 print:hidden">
        <Button variant="secondary" onClick={() => navigate("/stock")}>
          ← العودة لحركة المخزون
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
            <div className="text-lg font-extrabold">محضر إتلاف/تعديل مخزون</div>
            <div className="mt-1 text-sm font-bold text-slate-600">
              رقم: {a.id} — التاريخ: {a.created_at?.slice(0, 10)}
            </div>
          </div>
        </header>

        {cancelled && (
          <div className="mt-4 rounded-lg border-2 border-rose-600 px-4 py-3 text-center">
            <div className="text-lg font-extrabold text-rose-700">ملغى</div>
            <div className="mt-1 text-sm font-bold text-slate-600">
              تاريخ الإلغاء: {a.cancelled_at?.slice(0, 10)}
              {a.cancel_reason ? ` — السبب: ${a.cancel_reason}` : ""}
            </div>
            <div className="mt-1 text-xs text-slate-500">
              أُعيدت الكميات إلى المخزون وعُكس القيد المحاسبي.
            </div>
          </div>
        )}

        <section className="mt-5 grid grid-cols-4 gap-4 text-sm">
          <div className="rounded-lg bg-slate-50 p-3 print:border print:border-slate-300 print:bg-white">
            <div className="font-extrabold text-slate-500">السبب</div>
            <div className="font-bold">{REASON_LABELS[a.reason] ?? a.reason}</div>
          </div>
          <div className="rounded-lg bg-slate-50 p-3 print:border print:border-slate-300 print:bg-white">
            <div className="font-extrabold text-slate-500">عدد الأصناف</div>
            <div className="font-bold">{a.lines.length}</div>
          </div>
          <div className="rounded-lg bg-slate-50 p-3 print:border print:border-slate-300 print:bg-white">
            <div className="font-extrabold text-slate-500">إجمالي الكمية</div>
            <div className="font-bold">{qty(a.total_quantity)}</div>
          </div>
          <div className="rounded-lg bg-slate-50 p-3 print:border print:border-slate-300 print:bg-white">
            <div className="font-extrabold text-slate-500">قيمة الخسارة</div>
            <div className="font-bold">
              {a.cost_known ? money(a.total_cost) : "لا توجد تكلفة مسجلة"}
            </div>
          </div>
        </section>

        {a.notes && (
          <div className="mt-4 rounded-lg bg-slate-50 p-3 text-sm print:border print:border-slate-300 print:bg-white">
            <span className="font-extrabold text-slate-500">ملاحظات: </span>
            <span className="font-bold">{a.notes}</span>
          </div>
        )}

        <table className="mt-6 w-full border-collapse text-right text-sm">
          <thead>
            <tr className="bg-slate-800 text-white">
              <th className="border border-slate-800 px-3 py-2">#</th>
              <th className="border border-slate-800 px-3 py-2">الصنف</th>
              <th className="border border-slate-800 px-3 py-2">المستودع</th>
              <th className="border border-slate-800 px-3 py-2">التشغيلة</th>
              <th className="border border-slate-800 px-3 py-2">تاريخ الانتهاء</th>
              <th className="border border-slate-800 px-3 py-2">الكمية</th>
              <th className="border border-slate-800 px-3 py-2">تكلفة الوحدة</th>
              <th className="border border-slate-800 px-3 py-2">القيمة</th>
            </tr>
          </thead>
          <tbody>
            {a.lines.map((line, index) => (
              <tr key={line.id}>
                <td className="border border-slate-300 px-3 py-2">{index + 1}</td>
                <td className="border border-slate-300 px-3 py-2 font-bold">
                  {line.product_name}
                </td>
                <td className="border border-slate-300 px-3 py-2">{line.warehouse_name}</td>
                <td className="border border-slate-300 px-3 py-2">{line.batch_number}</td>
                <td className="border border-slate-300 px-3 py-2">{line.expiry_date}</td>
                <td className="border border-slate-300 px-3 py-2 font-bold">
                  {qty(line.quantity)} {line.base_unit_name}
                </td>
                <td className="border border-slate-300 px-3 py-2">
                  {Number(line.unit_cost) > 0 ? money(line.unit_cost) : "—"}
                </td>
                <td className="border border-slate-300 px-3 py-2 font-bold">
                  {Number(line.unit_cost) > 0 ? money(line.line_total) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="bg-slate-100 font-extrabold">
              <td className="border border-slate-300 px-3 py-2" colSpan={5}>
                الإجمالي
              </td>
              <td className="border border-slate-300 px-3 py-2">{qty(a.total_quantity)}</td>
              <td className="border border-slate-300 px-3 py-2"></td>
              <td className="border border-slate-300 px-3 py-2">
                {a.cost_known ? money(a.total_cost) : "—"}
              </td>
            </tr>
          </tfoot>
        </table>

        <footer className="mt-14 grid grid-cols-3 gap-10 text-center text-sm font-bold text-slate-600">
          <div className="border-t-2 border-dotted border-slate-400 pt-2">
            توقيع أمين المستودع
          </div>
          <div className="border-t-2 border-dotted border-slate-400 pt-2">توقيع المحاسب</div>
          <div className="border-t-2 border-dotted border-slate-400 pt-2">اعتماد المدير</div>
        </footer>
      </div>
    </div>
  );
}
