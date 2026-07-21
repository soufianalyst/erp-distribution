import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Input,
  Loading,
  PaginatedTable,
  money,
} from "../components/Ui";
import useFetch from "../hooks/useFetch";
import api from "../services/api";

export default function IncomeStatementPage() {
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const buildUrl = () => {
    const params = new URLSearchParams();
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    const qs = params.toString();
    return `/reports/income-statement${qs ? `?${qs}` : ""}`;
  };

  const { data, loading, error, reload } = useFetch(() => api.get(buildUrl()));
  const report = data;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-extrabold">قائمة الدخل (P&L)</h1>
        <Button variant="secondary" onClick={reload}>تحديث</Button>
      </div>

      <Card>
        <div className="flex items-end gap-4">
          <Input
            label="من تاريخ"
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
          />
          <Input
            label="إلى تاريخ"
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
          />
          <Button onClick={reload}>عرض التقرير</Button>
          {(dateFrom || dateTo) && (
            <Button
              variant="secondary"
              onClick={() => { setDateFrom(""); setDateTo(""); }}
            >
              مسح التواريخ
            </Button>
          )}
        </div>
      </Card>

      <Alert>{error}</Alert>

      {loading ? (
        <Loading />
      ) : report ? (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-lg border bg-blue-50 p-4 text-center">
              <div className="text-xs font-bold text-blue-700">إجمالي المبيعات</div>
              <div className="text-2xl font-extrabold text-blue-800">
                {money(report.gross_sales)}
              </div>
            </div>
            <div className="rounded-lg border bg-amber-50 p-4 text-center">
              <div className="text-xs font-bold text-amber-700">مرتجعات المبيعات</div>
              <div className="text-2xl font-extrabold text-amber-800">
                {money(report.sales_returns)}
              </div>
            </div>
            <div className="rounded-lg border bg-emerald-50 p-4 text-center">
              <div className="text-xs font-bold text-emerald-700">صافي المبيعات</div>
              <div className="text-2xl font-extrabold text-emerald-800">
                {money(report.net_sales)}
              </div>
            </div>
            <div className="rounded-lg border bg-rose-50 p-4 text-center">
              <div className="text-xs font-bold text-rose-700">تكلفة البضاعة المباعة</div>
              <div className="text-2xl font-extrabold text-rose-800">
                {money(report.cogs)}
              </div>
            </div>
          </div>

          {/* Gross profit */}
          <Card>
            <div className="flex items-center justify-between">
              <span className="text-lg font-extrabold">الربح الإجمالي</span>
              <span className={`text-xl font-extrabold ${report.gross_profit >= 0 ? "text-emerald-700" : "text-rose-700"}`}>
                {money(report.gross_profit)}
              </span>
            </div>
          </Card>

          {/* Expenses detail */}
          {report.expenses && report.expenses.length > 0 && (
            <Card>
              <h2 className="mb-4 text-lg font-extrabold">المصروفات التفصيلية</h2>
              <PaginatedTable
                columns={[
                  { key: "account_code", label: "رقم الحساب" },
                  { key: "account_name", label: "اسم الحساب" },
                  {
                    key: "balance",
                    label: "المبلغ",
                    render: (r) => <b className="text-rose-700">{money(r.balance)}</b>,
                  },
                ]}
                rows={report.expenses}
                empty="لا توجد مصروفات مسجلة."
              />
            </Card>
          )}

          {/* Net profit */}
          <Card>
            <div className="flex items-center justify-between">
              <span className="text-lg font-extrabold">صافي الربح</span>
              <span className={`text-2xl font-extrabold ${report.net_profit >= 0 ? "text-emerald-700" : "text-rose-700"}`}>
                {report.net_profit >= 0 ? "+" : ""}{money(report.net_profit)}
              </span>
            </div>
            <div className="mt-2 text-sm text-slate-500">
              صافي الربح = ربح إجمالي ({money(report.gross_profit)}) − المصروفات ({money(report.total_expenses)})
            </div>
          </Card>

          {/* Period info */}
          {(report.date_from || report.date_to) && (
            <div className="text-sm text-slate-500">
              الفترة: {report.date_from || "البداية"} — {report.date_to || "النهاية"}
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}
