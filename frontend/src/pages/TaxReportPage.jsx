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

export default function TaxReportPage() {
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const buildUrl = () => {
    const params = new URLSearchParams();
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    const qs = params.toString();
    return `/reports/tax-report${qs ? `?${qs}` : ""}`;
  };

  const { data, loading, error, reload } = useFetch(() => api.get(buildUrl()));

  const report = data;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-extrabold">تقرير الضريبة</h1>
        <Button variant="secondary" onClick={reload}>تحديث</Button>
      </div>

      {/* Date range filter */}
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
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
            <div className="rounded-lg border bg-emerald-50 p-4 text-center">
              <div className="text-xs font-bold text-emerald-700">ضريبة محصلة (المبيعات)</div>
              <div className="text-2xl font-extrabold text-emerald-800">
                {money(report.total_collected)}
              </div>
            </div>
            <div className="rounded-lg border bg-amber-50 p-4 text-center">
              <div className="text-xs font-bold text-amber-700">مرتجعات ضريبية</div>
              <div className="text-2xl font-extrabold text-amber-800">
                {money(report.total_returned)}
              </div>
            </div>
            <div className="rounded-lg border bg-blue-50 p-4 text-center">
              <div className="text-xs font-bold text-blue-700">صافي المحصل</div>
              <div className="text-2xl font-extrabold text-blue-800">
                {money(report.net_collected)}
              </div>
            </div>
            <div className="rounded-lg border bg-rose-50 p-4 text-center">
              <div className="text-xs font-bold text-rose-700">ضريبة مدفوعة (المشتريات)</div>
              <div className="text-2xl font-extrabold text-rose-800">
                {money(report.total_paid_on_purchases)}
              </div>
            </div>
            <div className={`rounded-lg border p-4 text-center ${
              report.net_tax_payable >= 0
                ? "border-red-200 bg-red-50"
                : "border-green-200 bg-green-50"
            }`}>
              <div className={`text-xs font-bold ${
                report.net_tax_payable >= 0 ? "text-red-700" : "text-green-700"
              }`}>
                صافي المستحق للحكومة
              </div>
              <div className={`text-2xl font-extrabold ${
                report.net_tax_payable >= 0 ? "text-red-800" : "text-green-800"
              }`}>
                {report.net_tax_payable >= 0 ? "+" : ""}{money(report.net_tax_payable)}
              </div>
              <div className={`text-xs mt-1 ${
                report.net_tax_payable >= 0 ? "text-red-600" : "text-green-600"
              }`}>
                {report.net_tax_payable >= 0 ? "يجب دفعها للحكومة" : "مستردة من الحكومة"}
              </div>
            </div>
          </div>

          {/* Period info */}
          {(report.date_from || report.date_to) && (
            <div className="text-sm text-slate-500">
              الفترة: {report.date_from || "البداية"} — {report.date_to || "النهاية"}
            </div>
          )}

          {/* By tax type table */}
          <Card>
            <h2 className="mb-4 text-lg font-extrabold">تفصيل حسب نوع الضريبة</h2>
            <PaginatedTable
              columns={[
                { key: "tax_type_name", label: "نوع الضريبة" },
                {
                  key: "rate",
                  label: "النسبة",
                  render: (r) => <Badge tone="blue">{(parseFloat(r.rate) * 100).toFixed(1)}%</Badge>,
                },
                { key: "accounting_code", label: "الحساب" },
                {
                  key: "collected",
                  label: "محصل",
                  render: (r) => <b className="text-emerald-700">{money(r.collected)}</b>,
                },
                {
                  key: "returned",
                  label: "مرتجع",
                  render: (r) => r.returned > 0 ? <b className="text-amber-700">{money(r.returned)}</b> : "—",
                },
                {
                  key: "net_collected",
                  label: "صافي المحصل",
                  render: (r) => <b className="text-blue-700">{money(r.net_collected)}</b>,
                },
              ]}
              rows={report.by_tax_type || []}
              empty="لا توجد بيانات ضريبية لهذه الفترة."
              searchable
              searchPlaceholder="بحث..."
            />
          </Card>
        </>
      ) : null}
    </div>
  );
}
