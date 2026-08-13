import { useNavigate, useSearchParams } from "react-router-dom";
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

// Print-ready damaged/written-off stock report for a chosen period.
export default function PrintDamageReportPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const dateFrom = params.get("from") || "";
  const dateTo = params.get("to") || "";

  const report = useFetch(
    () =>
      api.get("/analytics/inventory/damage-report", {
        params: { date_from: dateFrom || undefined, date_to: dateTo || undefined },
      }),
    [dateFrom, dateTo]
  );
  const company = useFetch(() => api.get("/settings/company"));

  if (report.loading || company.loading) return <Loading />;
  if (report.error) {
    return <div className="p-10 text-center font-bold text-rose-700">{report.error}</div>;
  }

  const r = report.data;
  const periodLabel =
    dateFrom || dateTo
      ? `${dateFrom || "البداية"} ← ${dateTo || "اليوم"}`
      : "كل الفترات";

  return (
    <div className="min-h-screen bg-slate-200 py-8 print:bg-white print:py-0">
      <div className="mx-auto mb-4 flex max-w-[210mm] justify-between gap-2 print:hidden">
        <Button variant="secondary" onClick={() => navigate("/analytics")}>
          ← العودة للتحليلات
        </Button>
        <Button onClick={() => window.print()}>🖨️ طباعة</Button>
      </div>

      <div className="mx-auto max-w-[210mm] bg-white p-10 text-slate-900 shadow print:max-w-none print:p-0 print:shadow-none">
        <header className="flex items-start justify-between border-b-4 border-slate-800 pb-4">
          <div>
            <h1 className="text-2xl font-extrabold text-slate-900">{company.data.name}</h1>
            {company.data.tagline && (
              <div className="mt-1 text-sm text-slate-600">{company.data.tagline}</div>
            )}
          </div>
          <div className="rounded-lg border-2 border-slate-800 px-6 py-3 text-center">
            <div className="text-lg font-extrabold">تقرير التالف/الهالك</div>
            <div className="mt-1 text-sm font-bold text-slate-600">الفترة: {periodLabel}</div>
          </div>
        </header>

        <section className="mt-5 grid grid-cols-3 gap-4 text-sm">
          <div className="rounded-lg bg-slate-50 p-3 print:border print:border-slate-300 print:bg-white">
            <div className="font-extrabold text-slate-500">عدد عمليات الإتلاف</div>
            <div className="text-lg font-extrabold">{r.adjustment_count}</div>
          </div>
          <div className="rounded-lg bg-slate-50 p-3 print:border print:border-slate-300 print:bg-white">
            <div className="font-extrabold text-slate-500">إجمالي الكمية</div>
            <div className="text-lg font-extrabold">{qty(r.total_quantity)}</div>
          </div>
          <div className="rounded-lg bg-slate-50 p-3 print:border print:border-slate-300 print:bg-white">
            <div className="font-extrabold text-slate-500">إجمالي قيمة الخسارة</div>
            <div className="text-lg font-extrabold">{money(r.total_cost)}</div>
          </div>
        </section>

        <div className="mt-6">
          <div className="mb-1 rounded-t-lg bg-slate-700 px-3 py-1.5 text-sm font-extrabold text-white">
            التوزيع حسب السبب
          </div>
          <table className="w-full border-collapse text-right text-sm">
            <thead>
              <tr className="bg-slate-800 text-white">
                <th className="border border-slate-800 px-3 py-2">السبب</th>
                <th className="border border-slate-800 px-3 py-2">عدد العمليات</th>
                <th className="border border-slate-800 px-3 py-2">الكمية</th>
                <th className="border border-slate-800 px-3 py-2">قيمة الخسارة</th>
              </tr>
            </thead>
            <tbody>
              {r.by_reason.length === 0 && (
                <tr>
                  <td className="border border-slate-300 px-3 py-3 text-center" colSpan={4}>
                    لا يوجد تالف في هذه الفترة.
                  </td>
                </tr>
              )}
              {r.by_reason.map((row) => (
                <tr key={row.reason}>
                  <td className="border border-slate-300 px-3 py-2 font-bold">
                    {REASON_LABELS[row.reason] ?? row.reason}
                  </td>
                  <td className="border border-slate-300 px-3 py-2">{row.adjustment_count}</td>
                  <td className="border border-slate-300 px-3 py-2">{qty(row.total_quantity)}</td>
                  <td className="border border-slate-300 px-3 py-2 font-bold">
                    {money(row.total_cost)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="mt-6">
          <div className="mb-1 rounded-t-lg bg-slate-700 px-3 py-1.5 text-sm font-extrabold text-white">
            التوزيع حسب الصنف
          </div>
          <table className="w-full border-collapse text-right text-sm">
            <thead>
              <tr className="bg-slate-800 text-white">
                <th className="border border-slate-800 px-3 py-2">#</th>
                <th className="border border-slate-800 px-3 py-2">الصنف</th>
                <th className="border border-slate-800 px-3 py-2">الكمية</th>
                <th className="border border-slate-800 px-3 py-2">قيمة الخسارة</th>
              </tr>
            </thead>
            <tbody>
              {r.by_product.length === 0 && (
                <tr>
                  <td className="border border-slate-300 px-3 py-3 text-center" colSpan={4}>
                    لا يوجد تالف في هذه الفترة.
                  </td>
                </tr>
              )}
              {r.by_product.map((row, index) => (
                <tr key={row.product_id}>
                  <td className="border border-slate-300 px-3 py-2">{index + 1}</td>
                  <td className="border border-slate-300 px-3 py-2 font-bold">
                    {row.product_name}
                  </td>
                  <td className="border border-slate-300 px-3 py-2">
                    {qty(row.total_quantity)} {row.base_unit_name}
                  </td>
                  <td className="border border-slate-300 px-3 py-2 font-bold">
                    {money(row.total_cost)}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="bg-slate-100 font-extrabold">
                <td className="border border-slate-300 px-3 py-2" colSpan={2}>
                  الإجمالي
                </td>
                <td className="border border-slate-300 px-3 py-2">{qty(r.total_quantity)}</td>
                <td className="border border-slate-300 px-3 py-2">{money(r.total_cost)}</td>
              </tr>
            </tfoot>
          </table>
        </div>

        <p className="mt-5 text-xs text-slate-500">
          * لا يشمل التقرير عمليات الإتلاف الملغاة، لأن كمياتها أُعيدت إلى المخزون.
        </p>

        <footer className="mt-14 grid grid-cols-2 gap-10 text-center text-sm font-bold text-slate-600">
          <div className="border-t-2 border-dotted border-slate-400 pt-2">توقيع المحاسب</div>
          <div className="border-t-2 border-dotted border-slate-400 pt-2">اعتماد المدير</div>
        </footer>
      </div>
    </div>
  );
}
