import { useNavigate, useSearchParams } from "react-router-dom";
import { Button, Loading, money } from "../components/Ui";
import useFetch from "../hooks/useFetch";
import api from "../services/api";

// Print-ready report of discounts granted on invoices over a chosen period.
export default function PrintDiscountReportPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const dateFrom = params.get("from") || "";
  const dateTo = params.get("to") || "";

  const report = useFetch(
    () =>
      api.get("/analytics/sales/discount-report", {
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
    dateFrom || dateTo ? `${dateFrom || "البداية"} ← ${dateTo || "اليوم"}` : "كل الفترات";

  const th = "border border-slate-300 bg-slate-800 px-3 py-2 text-white print:bg-slate-800";
  const td = "border border-slate-300 px-3 py-2";

  return (
    <div className="min-h-screen bg-slate-200 py-8 print:bg-white print:py-0">
      <div className="mx-auto mb-4 flex max-w-[210mm] justify-between gap-2 print:hidden">
        <Button variant="secondary" onClick={() => navigate("/analytics")}>
          ← العودة للتحليلات
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
            <div className="text-lg font-extrabold">تقرير الخصومات الممنوحة</div>
            <div className="mt-1 text-sm font-bold text-slate-600">الفترة: {periodLabel}</div>
          </div>
        </header>

        <div className="mt-6 grid grid-cols-4 gap-3 text-sm">
          <div className="rounded-lg bg-slate-50 p-3">
            <div className="font-extrabold text-slate-500">عدد الفواتير</div>
            <div className="text-lg font-extrabold">{r.invoice_count}</div>
          </div>
          <div className="rounded-lg bg-slate-50 p-3">
            <div className="font-extrabold text-slate-500">إجمالي الخصومات</div>
            <div className="text-lg font-extrabold">{money(r.total_discount)}</div>
          </div>
          <div className="rounded-lg bg-slate-50 p-3">
            <div className="font-extrabold text-slate-500">قبل الخصم</div>
            <div className="text-lg font-extrabold">{money(r.total_gross)}</div>
          </div>
          <div className="rounded-lg bg-slate-50 p-3">
            <div className="font-extrabold text-slate-500">صافي المحصّل</div>
            <div className="text-lg font-extrabold">{money(r.total_net)}</div>
          </div>
        </div>

        <section className="mt-6">
          <div className="rounded-t-lg bg-slate-800 px-3 py-2 text-sm font-extrabold text-white">
            التوزيع حسب العميل
          </div>
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr>
                <th className={th}>العميل</th>
                <th className={th}>عدد الفواتير</th>
                <th className={th}>إجمالي الخصم</th>
              </tr>
            </thead>
            <tbody>
              {r.by_customer.map((row) => (
                <tr key={row.customer_id}>
                  <td className={`${td} font-bold`}>{row.customer_name}</td>
                  <td className={td}>{row.invoice_count}</td>
                  <td className={`${td} font-bold`}>{money(row.discount_amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="mt-6">
          <div className="rounded-t-lg bg-slate-800 px-3 py-2 text-sm font-extrabold text-white">
            التوزيع حسب المندوب
          </div>
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr>
                <th className={th}>المندوب</th>
                <th className={th}>عدد الفواتير</th>
                <th className={th}>إجمالي الخصم</th>
              </tr>
            </thead>
            <tbody>
              {r.by_salesman.map((row) => (
                <tr key={String(row.salesman_id)}>
                  <td className={`${td} font-bold`}>{row.salesman_name}</td>
                  <td className={td}>{row.invoice_count}</td>
                  <td className={`${td} font-bold`}>{money(row.discount_amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="mt-6">
          <div className="rounded-t-lg bg-slate-800 px-3 py-2 text-sm font-extrabold text-white">
            الفواتير المخصومة
          </div>
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr>
                <th className={th}>#</th>
                <th className={th}>التاريخ</th>
                <th className={th}>العميل</th>
                <th className={th}>المندوب</th>
                <th className={th}>قبل الخصم</th>
                <th className={th}>الخصم</th>
                <th className={th}>المستحق</th>
              </tr>
            </thead>
            <tbody>
              {r.invoices.map((row) => (
                <tr key={row.invoice_id}>
                  <td className={td}>#{row.invoice_id}</td>
                  <td className={td}>{row.invoice_date}</td>
                  <td className={`${td} font-bold`}>{row.customer_name}</td>
                  <td className={td}>{row.salesman_name ?? "—"}</td>
                  <td className={td}>{money(row.gross_amount)}</td>
                  <td className={`${td} font-bold`}>{money(row.discount_amount)}</td>
                  <td className={`${td} font-bold`}>{money(row.total)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="font-extrabold">
                <td className={td} colSpan={4}>
                  الإجمالي
                </td>
                <td className={td}>{money(r.total_gross)}</td>
                <td className={td}>{money(r.total_discount)}</td>
                <td className={td}>{money(r.total_net)}</td>
              </tr>
            </tfoot>
          </table>
        </section>

        <footer className="mt-10 text-xs text-slate-500">
          تم إنشاء التقرير من نظام إدارة التوزيع.
        </footer>
      </div>
    </div>
  );
}
