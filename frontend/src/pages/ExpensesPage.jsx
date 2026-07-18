import { useState } from "react";
import { Alert, Badge, Button, Card, Input, Modal, Select, Table, money } from "../components/Ui";
import { useAuth } from "../context/AuthContext";
import useFetch from "../hooks/useFetch";
import api, { apiMessage } from "../services/api";

const PAYMENT_METHOD_LABELS = { cash: "نقدي", card: "بطاقة" };
const PAYMENT_METHOD_TONE = { cash: "green", card: "blue" };

function CategoryForm({ onSaved, onClose }) {
  const [name, setName] = useState("");
  const [error, setError] = useState(null);

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    try {
      await api.post("/expenses/categories", { name });
      onSaved();
    } catch (err) {
      setError(apiMessage(err));
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <Alert>{error}</Alert>
      <Input label="اسم التصنيف" value={name} onChange={(e) => setName(e.target.value)} required autoFocus />
      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onClose}>
          إلغاء
        </Button>
        <Button type="submit">حفظ التصنيف</Button>
      </div>
    </form>
  );
}

function CategoriesSection({ canManage, categories, onReload }) {
  const [open, setOpen] = useState(false);
  const [notice, setNotice] = useState(null);

  const toggleActive = async (category) => {
    try {
      await api.patch(`/expenses/categories/${category.id}`, {
        is_active: !category.is_active,
      });
      onReload();
    } catch (err) {
      setNotice(apiMessage(err));
    }
  };

  return (
    <Card
      title="تصنيفات المصاريف"
      actions={canManage && <Button onClick={() => setOpen(true)}>+ تصنيف جديد</Button>}
    >
      <Alert tone="success">{notice}</Alert>
      <Table
        columns={[
          { key: "name", label: "التصنيف" },
          {
            key: "is_active",
            label: "الحالة",
            render: (r) =>
              canManage ? (
                <button onClick={() => toggleActive(r)}>
                  {r.is_active ? <Badge tone="green">مفعّل</Badge> : <Badge tone="red">موقوف</Badge>}
                </button>
              ) : r.is_active ? (
                <Badge tone="green">مفعّل</Badge>
              ) : (
                <Badge tone="red">موقوف</Badge>
              ),
          },
        ]}
        rows={categories}
        searchPlaceholder="بحث في التصنيفات..."
      />
      <Modal open={open} title="إضافة تصنيف مصاريف" onClose={() => setOpen(false)}>
        <CategoryForm
          onSaved={() => {
            setOpen(false);
            setNotice("تم إضافة التصنيف بنجاح.");
            onReload();
          }}
          onClose={() => setOpen(false)}
        />
      </Modal>
    </Card>
  );
}

const EMPTY_EXPENSE = { category_id: "", description: "", amount: "", payment_method: "cash", notes: "" };

function ExpenseForm({ categories, onCreated }) {
  const [form, setForm] = useState(EMPTY_EXPENSE);
  const [error, setError] = useState(null);
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    try {
      const { data } = await api.post("/expenses", {
        ...form,
        notes: form.notes || null,
      });
      setForm(EMPTY_EXPENSE);
      onCreated(data.data, data.message);
    } catch (err) {
      setError(apiMessage(err));
    }
  };

  const activeCategories = categories.filter((c) => c.is_active);

  return (
    <form onSubmit={submit} className="space-y-4">
      <Alert>{error}</Alert>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Select label="التصنيف" value={form.category_id} onChange={set("category_id")} required>
          <option value="">— اختر التصنيف —</option>
          {activeCategories.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </Select>
        <Select label="طريقة الدفع" value={form.payment_method} onChange={set("payment_method")}>
          <option value="cash">نقدي</option>
          <option value="card">بطاقة</option>
        </Select>
        <Input label="الوصف" value={form.description} onChange={set("description")} required />
        <Input label="المبلغ" type="number" step="0.01" min="0.01" value={form.amount} onChange={set("amount")} required />
      </div>
      <Input label="ملاحظات (اختياري)" value={form.notes} onChange={set("notes")} />
      <Button type="submit">تسجيل المصروف</Button>
    </form>
  );
}

export default function ExpensesPage() {
  const { can } = useAuth();
  const canManage = can("expenses.manage");

  const categories = useFetch(() => api.get("/expenses/categories"));
  const expenses = useFetch(() => api.get("/expenses"));
  const [notice, setNotice] = useState(null);

  if (categories.loading || expenses.loading) return null;

  const categoryName = (id) => categories.data?.find((c) => c.id === id)?.name ?? id;

  const reloadAll = () => {
    categories.reload();
    expenses.reload();
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-extrabold">المصاريف</h1>
      <Alert tone="success">{notice}</Alert>

      {!canManage && (
        <Alert>لا تملك صلاحية تسجيل المصاريف أو إدارة تصنيفاتها، يمكنك العرض فقط.</Alert>
      )}

      {canManage && (
        <Card title="تسجيل مصروف جديد — يبقى بانتظار الصرف من الصندوق">
          <ExpenseForm
            categories={categories.data || []}
            onCreated={(_expense, message) => {
              setNotice(message);
              reloadAll();
            }}
          />
        </Card>
      )}

      <CategoriesSection
        canManage={canManage}
        categories={categories.data || []}
        onReload={reloadAll}
      />

      <Card title="سجل المصاريف">
        <Table
          columns={[
            { key: "id", label: "#" },
            { key: "category_id", label: "التصنيف", render: (r) => categoryName(r.category_id) },
            { key: "description", label: "الوصف" },
            {
              key: "payment_method",
              label: "طريقة الدفع",
              render: (r) => (
                <Badge tone={PAYMENT_METHOD_TONE[r.payment_method]}>
                  {PAYMENT_METHOD_LABELS[r.payment_method]}
                </Badge>
              ),
            },
            { key: "amount", label: "المبلغ", render: (r) => money(r.amount) },
            {
              key: "payment_confirmed_at",
              label: "حالة السداد",
              render: (r) =>
                r.payment_confirmed_at ? (
                  <Badge tone="green">تم السداد</Badge>
                ) : Number(r.paid_amount) > 0 ? (
                  <Badge tone="amber">سداد جزئي ({money(r.paid_amount)})</Badge>
                ) : (
                  <Badge tone="amber">بانتظار الصندوق</Badge>
                ),
            },
          ]}
          rows={expenses.data}
          empty="لا توجد مصاريف مسجلة بعد."
        />
      </Card>
    </div>
  );
}
