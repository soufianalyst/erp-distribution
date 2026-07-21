import { useState } from "react";
import {
  Alert,
  Button,
  Card,
  Input,
  Loading,
  PaginatedTable,
  money,
} from "../components/Ui";
import useFetch from "../hooks/useFetch";
import api from "../services/api";

export default function BalanceSheetPage() {
  const [asOfDate, setAsOfDate] = useState("");

  const buildUrl = () => {
    const params = new URLSearchParams();
    if (asOfDate) params.set("as_of_date", asOfDate);
    const qs = params.toString();
    return `/reports/balance-sheet${qs ? `?${qs}` : ""}`;
  };

  const { data, loading, error, reload } = useFetch(() => api.get(buildUrl()));
  const report = data;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-extrabold">الميزانية العمومية</h1>
        <Button variant="secondary" onClick={reload}>تحديث</Button>
      </div>

      <Card>
        <div className="flex items-end gap-4">
          <Input
            label="حتى تاريخ"
            type="date"
            value={asOfDate}
            onChange={(e) => setAsOfDate(e.target.value)}
          />
          <Button onClick={reload}>عرض التقرير</Button>
          {asOfDate && (
            <Button
              variant="secondary"
              onClick={() => { setAsOfDate(""); }}
            >
              مسح التاريخ
            </Button>
          )}
        </div>
      </Card>

      <Alert>{error}</Alert>

      {loading ? (
        <Loading />
      ) : report ? (
        <>
          <div className="text-sm text-slate-500">
            بتاريخ: {report.as_of_date}
          </div>

          {/* Assets */}
          <Card>
            <h2 className="mb-4 text-lg font-extrabold text-blue-800">{report.assets.title}</h2>
            <PaginatedTable
              columns={[
                { key: "account_code", label: "رقم الحساب" },
                { key: "account_name", label: "اسم الحساب" },
                {
                  key: "balance",
                  label: "الرصيد",
                  render: (r) => <b className="text-blue-700">{money(r.balance)}</b>,
                },
              ]}
              rows={report.assets.items}
              empty="لا توجد أصول مسجلة."
            />
            <div className="mt-4 flex items-center justify-between border-t pt-4">
              <span className="text-lg font-extrabold">إجمالي الأصول</span>
              <span className="text-xl font-extrabold text-blue-800">{money(report.assets.total)}</span>
            </div>
          </Card>

          {/* Liabilities */}
          <Card>
            <h2 className="mb-4 text-lg font-extrabold text-rose-800">{report.liabilities.title}</h2>
            <PaginatedTable
              columns={[
                { key: "account_code", label: "رقم الحساب" },
                { key: "account_name", label: "اسم الحساب" },
                {
                  key: "balance",
                  label: "الرصيد",
                  render: (r) => <b className="text-rose-700">{money(r.balance)}</b>,
                },
              ]}
              rows={report.liabilities.items}
              empty="لا توجد خصوم مسجلة."
            />
            <div className="mt-4 flex items-center justify-between border-t pt-4">
              <span className="text-lg font-extrabold">إجمالي الخصوم</span>
              <span className="text-xl font-extrabold text-rose-800">{money(report.liabilities.total)}</span>
            </div>
          </Card>

          {/* Equity */}
          <Card>
            <h2 className="mb-4 text-lg font-extrabold text-emerald-800">{report.equity.title}</h2>
            <PaginatedTable
              columns={[
                { key: "account_code", label: "رقم الحساب" },
                { key: "account_name", label: "اسم الحساب" },
                {
                  key: "balance",
                  label: "الرصيد",
                  render: (r) => <b className="text-emerald-700">{money(r.balance)}</b>,
                },
              ]}
              rows={report.equity.items}
              empty="لا توجد حقوق ملكية مسجلة."
            />
            <div className="mt-4 flex items-center justify-between border-t pt-4">
              <span className="text-lg font-extrabold">إجمالي حقوق الملكية</span>
              <span className="text-xl font-extrabold text-emerald-800">{money(report.equity.total)}</span>
            </div>
          </Card>

          {/* Total */}
          <Card>
            <div className="flex items-center justify-between">
              <span className="text-lg font-extrabold">إجمالي الخصوم + حقوق الملكية</span>
              <span className="text-2xl font-extrabold text-slate-800">
                {money(report.total_liabilities_and_equity)}
              </span>
            </div>
            <div className="mt-2 flex items-center justify-between text-sm text-slate-500">
              <span>إجمالي الأصول: {money(report.assets.total)}</span>
              <span className={`font-bold ${
                Math.abs(report.assets.total - report.total_liabilities_and_equity) < 0.01
                  ? "text-emerald-600"
                  : "text-amber-600"
              }`}>
                {Math.abs(report.assets.total - report.total_liabilities_and_equity) < 0.01
                  ? "✓ متوازنة"
                  : "⚠ غير متوازنة"}
              </span>
            </div>
          </Card>
        </>
      ) : null}
    </div>
  );
}
