import { useState } from "react";
import { Alert, Badge, Button, Card, Input, Loading, Modal, Select, Table } from "../components/Ui";
import useFetch from "../hooks/useFetch";
import api from "../services/api";

const ACTION_LABELS = { insert: "إنشاء", update: "تعديل", delete: "حذف" };
const ACTION_TONE = { insert: "green", update: "amber", delete: "red" };

// Best-effort Arabic labels for the tables seen most often; any table not
// listed here still shows fine using its raw (English) name.
const TABLE_LABELS = {
  users: "المستخدمون",
  warehouses: "المستودعات",
  products: "الأصناف",
  product_units: "وحدات القياس",
  product_batches: "تشغيلات المخزون",
  stock_adjustments: "تعديلات المخزون",
  stock_adjustment_lines: "أسطر تعديلات المخزون",
  suppliers: "الموردون",
  purchase_invoices: "فواتير المشتريات",
  purchase_invoice_lines: "أسطر فواتير المشتريات",
  purchase_invoice_taxes: "ضرائب فواتير المشتريات",
  purchase_returns: "مرتجعات المشتريات",
  purchase_return_lines: "أسطر مرتجعات المشتريات",
  supplier_payments: "سندات صرف الموردين",
  customers: "العملاء",
  sales_invoices: "فواتير المبيعات",
  sales_invoice_lines: "أسطر فواتير المبيعات",
  sales_invoice_taxes: "ضرائب فواتير المبيعات",
  sales_returns: "مرتجعات المبيعات",
  sales_return_lines: "أسطر مرتجعات المبيعات",
  customer_payments: "سندات قبض العملاء",
  expenses: "المصاريف",
  expense_categories: "تصنيفات المصاريف",
  cash_movements: "حركات الصندوق",
  accounts: "دليل الحسابات",
  journal_entries: "قيود اليومية",
  journal_items: "أطراف القيود",
  tax_rates: "الضرائب",
  company_settings: "بيانات الشركة",
  delivery_trips: "رحلات التوزيع",
  delivery_stops: "محطات التوزيع",
};

const tableLabel = (name) => TABLE_LABELS[name] || name;

function ChangesViewer({ entry }) {
  const rows = Object.entries(entry.changes);
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b border-slate-200 text-xs font-bold text-slate-500">
          <th className="px-2 py-1 text-right">الحقل</th>
          {entry.action === "update" ? (
            <>
              <th className="px-2 py-1 text-right">القيمة السابقة</th>
              <th className="px-2 py-1 text-right">القيمة الجديدة</th>
            </>
          ) : (
            <th className="px-2 py-1 text-right">القيمة</th>
          )}
        </tr>
      </thead>
      <tbody>
        {rows.map(([field, value]) => (
          <tr key={field} className="border-b border-slate-100 last:border-0">
            <td className="px-2 py-1.5 font-bold">{field}</td>
            {entry.action === "update" ? (
              <>
                <td className="px-2 py-1.5 text-red-700">{String(value[0] ?? "—")}</td>
                <td className="px-2 py-1.5 text-emerald-700">{String(value[1] ?? "—")}</td>
              </>
            ) : (
              <td className="px-2 py-1.5">{String(value ?? "—")}</td>
            )}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function AuditLogPage() {
  const [tableName, setTableName] = useState("");
  const [action, setAction] = useState("");
  const [recordId, setRecordId] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [viewing, setViewing] = useState(null);

  const tables = useFetch(() => api.get("/audit/tables"));
  const users = useFetch(() => api.get("/auth/users"));
  const logs = useFetch(
    () =>
      api.get("/audit/logs", {
        params: {
          table_name: tableName || undefined,
          action: action || undefined,
          record_id: recordId || undefined,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
        },
      }),
    [tableName, action, recordId, dateFrom, dateTo]
  );

  const userName = (id) => {
    if (id == null) return "—";
    return users.data?.find((u) => u.id === id)?.full_name || `مستخدم #${id}`;
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-extrabold">سجل تتبع العمليات (Audit Trail)</h1>
      <p className="text-sm text-slate-500">
        سجل تلقائي لكل إضافة أو تعديل أو حذف في النظام، مع تحديد من قام بها ومتى.
      </p>

      <Card title="تصفية السجل">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3 lg:grid-cols-5">
          <Select label="الجدول" value={tableName} onChange={(e) => setTableName(e.target.value)}>
            <option value="">الكل</option>
            {(tables.data || []).map((t) => (
              <option key={t} value={t}>
                {tableLabel(t)}
              </option>
            ))}
          </Select>
          <Select label="نوع العملية" value={action} onChange={(e) => setAction(e.target.value)}>
            <option value="">الكل</option>
            <option value="insert">إنشاء</option>
            <option value="update">تعديل</option>
            <option value="delete">حذف</option>
          </Select>
          <Input
            label="رقم السجل (اختياري)"
            type="number"
            value={recordId}
            onChange={(e) => setRecordId(e.target.value)}
          />
          <Input label="من تاريخ" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          <Input label="إلى تاريخ" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </div>
      </Card>

      <Card>
        <Alert>{logs.error}</Alert>
        {logs.loading || tables.loading ? (
          <Loading />
        ) : (
          <Table
            columns={[
              { key: "id", label: "#" },
              {
                key: "created_at",
                label: "الوقت",
                render: (r) => r.created_at?.replace("T", " ").slice(0, 19),
              },
              { key: "user_id", label: "المستخدم", render: (r) => userName(r.user_id) },
              { key: "table_name", label: "الجدول", render: (r) => tableLabel(r.table_name) },
              {
                key: "action",
                label: "العملية",
                render: (r) => <Badge tone={ACTION_TONE[r.action]}>{ACTION_LABELS[r.action]}</Badge>,
              },
              { key: "record_id", label: "رقم السجل" },
              {
                key: "view",
                label: "",
                render: (r) => (
                  <Button variant="secondary" onClick={() => setViewing(r)}>
                    عرض التفاصيل
                  </Button>
                ),
              },
            ]}
            rows={logs.data}
            empty="لا توجد حركات مطابقة."
          />
        )}
      </Card>

      <Modal
        open={!!viewing}
        title={
          viewing
            ? `تفاصيل ${ACTION_LABELS[viewing.action]} — ${tableLabel(viewing.table_name)} #${viewing.record_id}`
            : ""
        }
        onClose={() => setViewing(null)}
        wide
      >
        {viewing && <ChangesViewer entry={viewing} />}
      </Modal>
    </div>
  );
}
