import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Input,
  Loading,
  Modal,
  Select,
  Table,
  money,
} from "../components/Ui";
import { useAuth } from "../context/AuthContext";
import useFetch from "../hooks/useFetch";
import api, { apiMessage } from "../services/api";

const TIER_LABELS = { wholesale: "جملة", half_wholesale: "نصف جملة", retail: "تجزئة" };

const EMPTY_FORM = {
  name: "",
  phone: "",
  address: "",
  price_tier: "wholesale",
  credit_limit: "0",
  salesman_id: "",
};

function PaymentSection({ customerId, onPaid }) {
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState("cash");
  const [error, setError] = useState(null);

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    try {
      await api.post("/sales/payments", { customer_id: customerId, amount, method });
      setAmount("");
      onPaid();
    } catch (err) {
      setError(apiMessage(err));
    }
  };

  return (
    <form onSubmit={submit} className="rounded-lg border border-emerald-200 bg-emerald-50/60 p-4">
      <div className="mb-2 text-sm font-extrabold text-emerald-800">سند قبض جديد</div>
      <Alert>{error}</Alert>
      <div className="grid grid-cols-3 items-end gap-3">
        <Input
          label="المبلغ"
          type="number"
          step="0.01"
          min="0.01"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          required
        />
        <Select label="طريقة الدفع" value={method} onChange={(e) => setMethod(e.target.value)}>
          <option value="cash">نقدي</option>
          <option value="bank">حوالة بنكية</option>
          <option value="cheque">شيك</option>
        </Select>
        <Button type="submit">تسجيل السند</Button>
      </div>
    </form>
  );
}

export default function CustomersPage() {
  const { can } = useAuth();
  const canManage = can("customers.manage");
  const { data, loading, error, reload } = useFetch(() => api.get("/sales/customers"));
  const salesmen = useFetch(() =>
    canManage ? api.get("/auth/users") : Promise.resolve({ data: { data: [] } })
  );

  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [formError, setFormError] = useState(null);
  const [statement, setStatement] = useState(null);
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  const submit = async (event) => {
    event.preventDefault();
    setFormError(null);
    try {
      await api.post("/sales/customers", { ...form, salesman_id: form.salesman_id || null });
      setOpen(false);
      setForm(EMPTY_FORM);
      reload();
    } catch (err) {
      setFormError(apiMessage(err));
    }
  };

  const showStatement = async (customer) => {
    try {
      const { data: res } = await api.get(`/sales/customers/${customer.id}/statement`);
      setStatement(res.data);
    } catch (err) {
      setStatement({ error: apiMessage(err) });
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-extrabold">العملاء</h1>
        {canManage && <Button onClick={() => setOpen(true)}>+ عميل جديد</Button>}
      </div>
      <Card>
        <Alert>{error}</Alert>
        {loading ? (
          <Loading />
        ) : (
          <Table
            columns={[
              { key: "name", label: "اسم العميل" },
              { key: "phone", label: "الهاتف", render: (r) => r.phone || "—" },
              { key: "price_tier", label: "فئة السعر", render: (r) => <Badge tone="blue">{TIER_LABELS[r.price_tier]}</Badge> },
              { key: "credit_limit", label: "الحد الائتماني", render: (r) => money(r.credit_limit) },
              {
                key: "is_active",
                label: "الحالة",
                render: (r) => (r.is_active ? <Badge tone="green">نشط</Badge> : <Badge tone="red">موقوف</Badge>),
              },
              {
                key: "actions",
                label: "",
                render: (r) => (
                  <Button variant="secondary" onClick={() => showStatement(r)}>
                    كشف حساب
                  </Button>
                ),
              },
            ]}
            rows={data}
          />
        )}
      </Card>

      <Modal open={open} title="إضافة عميل جديد" onClose={() => setOpen(false)}>
        <form onSubmit={submit} className="space-y-4">
          <Alert>{formError}</Alert>
          <Input label="اسم العميل" value={form.name} onChange={set("name")} required autoFocus />
          <div className="grid grid-cols-2 gap-4">
            <Input label="الهاتف" value={form.phone} onChange={set("phone")} />
            <Select label="فئة السعر" value={form.price_tier} onChange={set("price_tier")}>
              <option value="wholesale">جملة</option>
              <option value="half_wholesale">نصف جملة</option>
              <option value="retail">تجزئة</option>
            </Select>
            <Input label="الحد الائتماني" type="number" step="0.01" min="0" value={form.credit_limit} onChange={set("credit_limit")} />
            <Select label="المندوب المسؤول" value={form.salesman_id} onChange={set("salesman_id")}>
              <option value="">— بدون —</option>
              {(salesmen.data || [])
                .filter((u) => u.role === "sales" && u.is_active)
                .map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.full_name}
                  </option>
                ))}
            </Select>
          </div>
          <Input label="العنوان" value={form.address} onChange={set("address")} />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setOpen(false)}>
              إلغاء
            </Button>
            <Button type="submit">حفظ العميل</Button>
          </div>
        </form>
      </Modal>

      <Modal
        open={!!statement}
        title={statement?.customer ? `كشف حساب — ${statement.customer.name}` : "كشف حساب"}
        onClose={() => setStatement(null)}
        wide
      >
        {statement?.error ? (
          <Alert>{statement.error}</Alert>
        ) : statement ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="rounded-lg bg-slate-50 p-3 text-center">
                <div className="text-xs font-bold text-slate-500">إجمالي الفواتير</div>
                <div className="text-lg font-extrabold">{money(statement.total_invoices)}</div>
              </div>
              <div className="rounded-lg bg-slate-50 p-3 text-center">
                <div className="text-xs font-bold text-slate-500">المرتجعات</div>
                <div className="text-lg font-extrabold">{money(statement.total_returns)}</div>
              </div>
              <div className="rounded-lg bg-slate-50 p-3 text-center">
                <div className="text-xs font-bold text-slate-500">المسدد</div>
                <div className="text-lg font-extrabold">{money(statement.total_paid)}</div>
              </div>
              <div className="rounded-lg bg-emerald-50 p-3 text-center">
                <div className="text-xs font-bold text-emerald-700">الرصيد المستحق</div>
                <div className="text-lg font-extrabold text-emerald-800">{money(statement.balance)}</div>
              </div>
            </div>
            <Table
              columns={[
                { key: "id", label: "فاتورة #" },
                { key: "invoice_date", label: "التاريخ" },
                { key: "payment_method", label: "الدفع", render: (r) => (r.payment_method === "cash" ? "نقدي" : "آجل") },
                { key: "total", label: "الإجمالي", render: (r) => money(r.total) },
                { key: "paid_amount", label: "المسدد", render: (r) => money(r.paid_amount) },
              ]}
              rows={statement.invoices}
              empty="لا توجد فواتير لهذا العميل."
            />
            {can("sales.payments") && (
              <PaymentSection
                customerId={statement.customer.id}
                onPaid={() => {
                  showStatement(statement.customer);
                  reload();
                }}
              />
            )}
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
