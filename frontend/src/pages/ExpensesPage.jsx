import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Loading,
  Modal,
  PaginatedTable,
  money,
} from "../components/Ui";
import useFetch from "../hooks/useFetch";
import api, { apiMessage } from "../services/api";

const CATEGORIES = [
  { value: "utilities", label: "فواتير المرافق" },
  { value: "food", label: "طعام" },
  { value: "water", label: "مياه شرب" },
  { value: "rent", label: "إيجار" },
  { value: "salaries", label: "رواتب" },
  { value: "transport", label: "نقل ومواصلات" },
  { value: "maintenance", label: "صيانة" },
  { value: "office", label: "مكتبية" },
  { value: "other", label: "أخرى" },
];

const EXPENSE_ACCOUNTS = [
  { code: "5100", name: "فواتير المرافق" },
  { code: "5200", name: "طعام" },
  { code: "5300", name: "مياه شرب" },
  { code: "5400", name: "إيجار" },
  { code: "5500", name: "رواتب" },
  { code: "5600", name: "نقل ومواصلات" },
  { code: "5700", name: "صيانة" },
  { code: "5800", name: "مكتبية" },
  { code: "5900", name: "مصاريف أخرى" },
];

const CATEGORY_MAP = Object.fromEntries(CATEGORIES.map((c) => [c.value, c.label]));
const ACCOUNT_MAP = Object.fromEntries(EXPENSE_ACCOUNTS.map((a) => [a.code, a.name]));

const blank = {
  category: "utilities",
  payee_name: "",
  description: "",
  amount: "",
  expense_date: new Date().toISOString().slice(0, 10),
  payment_method: "cash",
  account_code: "5100",
  reference_no: "",
  notes: "",
};

export default function ExpensesPage() {
  const [notice, setNotice] = useState(null);
  const [modal, setModal] = useState(null); // null | "new" | expense object for edit
  const [form, setForm] = useState(blank);
  const [saving, setSaving] = useState(false);

  const expenses = useFetch(() => api.get("/expenses/"));

  const openNew = () => {
    setForm({ ...blank });
    setModal("new");
  };

  const openEdit = (exp) => {
    setForm({
      category: exp.category,
      payee_name: exp.payee_name,
      description: exp.description || "",
      amount: exp.amount,
      expense_date: exp.expense_date,
      payment_method: exp.payment_method,
      account_code: exp.account_code,
      reference_no: exp.reference_no || "",
      notes: exp.notes || "",
    });
    setModal(exp);
  };

  const save = async () => {
    if (!form.payee_name.trim()) {
      alert("اسم المستلم مطلوب.");
      return;
    }
    if (!form.amount || parseFloat(form.amount) <= 0) {
      alert("أدخل مبلغ صحيح.");
      return;
    }
    setSaving(true);
    try {
      const payload = { ...form, amount: String(form.amount) };
      if (modal === "new") {
        await api.post("/expenses/", payload);
        setNotice("تم إنشاء سند المصروف بنجاح.");
      } else {
        await api.put(`/expenses/${modal.id}`, payload);
        setNotice("تم تعديل سند المصروف بنجاح.");
      }
      setModal(null);
      expenses.reload();
    } catch (err) {
      alert(apiMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const remove = async (exp) => {
    if (!window.confirm(`حذف سند المصروف رقم ${exp.id}؟`)) return;
    try {
      await api.delete(`/expenses/${exp.id}`);
      setNotice("تم حذف سند المصروف.");
      expenses.reload();
    } catch (err) {
      alert(apiMessage(err));
    }
  };

  if (expenses.loading) return <Loading />;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-extrabold">المصاريف والمدفوعات</h1>
        <Button onClick={openNew}>+ سند مصروف جديد</Button>
      </div>

      {notice && <Alert>{notice}</Alert>}

      <Card>
        <Alert>{expenses.error}</Alert>
        <PaginatedTable
          columns={[
            { key: "id", label: "#", searchable: (r) => String(r.id) },
            { key: "expense_date", label: "التاريخ" },
            {
              key: "category",
              label: "الفئة",
              render: (r) => <Badge>{CATEGORY_MAP[r.category] || r.category}</Badge>,
              searchable: (r) => CATEGORY_MAP[r.category] || r.category,
            },
            { key: "payee_name", label: "المستلم" },
            { key: "description", label: "الوصف" },
            {
              key: "amount",
              label: "المبلغ",
              render: (r) => money(r.amount),
            },
            {
              key: "payment_method",
              label: "الدفع",
              render: (r) =>
                r.payment_method === "cash" ? (
                  <Badge tone="green">نقدي</Badge>
                ) : (
                  <Badge tone="blue">آجل</Badge>
                ),
            },
            {
              key: "paid_amount",
              label: "المدفوع",
              render: (r) => money(r.paid_amount),
            },
            {
              key: "account_code",
              label: "الحساب",
              render: (r) => `${r.account_code} - ${ACCOUNT_MAP[r.account_code] || ""}`,
            },
            {
              key: "actions",
              label: "",
              render: (r) => (
                <div className="flex gap-1">
                  <Button variant="secondary" onClick={() => openEdit(r)}>
                    تعديل
                  </Button>
                  <Button variant="danger" onClick={() => remove(r)}>
                    حذف
                  </Button>
                </div>
              ),
            },
          ]}
          rows={expenses.data}
          empty="لا توجد مصروفات."
          searchable
          searchPlaceholder="بحث بالاسم أو الوصف..."
          dateFromField="expense_date"
          dateToField="expense_date"
          amountField="amount"
          amountLabel="المبلغ"
        />
      </Card>

      {/* Create/Edit Modal */}
      <Modal
        open={!!modal}
        title={modal === "new" ? "سند مصروف جديد" : `تعديل سند رقم ${modal?.id}`}
        onClose={() => setModal(null)}
        wide
      >
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-sm font-bold">الفئة</label>
            <select
              value={form.category}
              onChange={(e) => setForm({ ...form, category: e.target.value })}
              className="w-full rounded-lg border px-3 py-2"
            >
              {CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-sm font-bold">المستلم</label>
            <input
              value={form.payee_name}
              onChange={(e) => setForm({ ...form, payee_name: e.target.value })}
              className="w-full rounded-lg border px-3 py-2"
              placeholder="اسم الشخص أو الجهة"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-bold">المبلغ</label>
            <input
              type="number"
              min="0.01"
              step="0.01"
              value={form.amount}
              onChange={(e) => setForm({ ...form, amount: e.target.value })}
              className="w-full rounded-lg border px-3 py-2"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-bold">التاريخ</label>
            <input
              type="date"
              value={form.expense_date}
              onChange={(e) => setForm({ ...form, expense_date: e.target.value })}
              className="w-full rounded-lg border px-3 py-2"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-bold">طريقة الدفع</label>
            <select
              value={form.payment_method}
              onChange={(e) => setForm({ ...form, payment_method: e.target.value })}
              className="w-full rounded-lg border px-3 py-2"
            >
              <option value="cash">نقدي — الصندوق</option>
              <option value="credit">آجل — المدفوعات المستحقة</option>
            </select>
          </div>
          <div>
            <label className="mb-1 block text-sm font-bold">حساب المصروف</label>
            <select
              value={form.account_code}
              onChange={(e) => setForm({ ...form, account_code: e.target.value })}
              className="w-full rounded-lg border px-3 py-2"
            >
              {EXPENSE_ACCOUNTS.map((a) => (
                <option key={a.code} value={a.code}>
                  {a.code} — {a.name}
                </option>
              ))}
            </select>
          </div>
          <div className="sm:col-span-2">
            <label className="mb-1 block text-sm font-bold">الوصف</label>
            <input
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              className="w-full rounded-lg border px-3 py-2"
              placeholder="تفاصيل المصروف"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-bold">رقم المرجع</label>
            <input
              value={form.reference_no}
              onChange={(e) => setForm({ ...form, reference_no: e.target.value })}
              className="w-full rounded-lg border px-3 py-2"
              placeholder="رقم الفاتورة أو الإيصال"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-bold">ملاحظات</label>
            <input
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              className="w-full rounded-lg border px-3 py-2"
            />
          </div>
        </div>
        <div className="mt-4 flex gap-2">
          <Button variant="primary" onClick={save} disabled={saving}>
            {saving ? "جاري الحفظ..." : "حفظ"}
          </Button>
          <Button onClick={() => setModal(null)}>إلغاء</Button>
        </div>
      </Modal>
    </div>
  );
}
