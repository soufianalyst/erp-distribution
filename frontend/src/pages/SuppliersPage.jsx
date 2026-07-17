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

function PaymentSection({ supplierId, onPaid }) {
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState("cash");
  const [error, setError] = useState(null);

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    try {
      await api.post("/purchases/payments", { supplier_id: supplierId, amount, method });
      setAmount("");
      onPaid();
    } catch (err) {
      setError(apiMessage(err));
    }
  };

  return (
    <form onSubmit={submit} className="rounded-lg border border-rose-200 bg-rose-50/60 p-4">
      <div className="mb-2 text-sm font-extrabold text-rose-800">سند صرف جديد</div>
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
        <Button type="submit" variant="danger">
          تسجيل السند
        </Button>
      </div>
    </form>
  );
}

export default function SuppliersPage() {
  const { can } = useAuth();
  const canManage = can("suppliers.manage");
  const { data, loading, error, reload } = useFetch(() => api.get("/purchases/suppliers"));
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", phone: "", address: "", opening_balance: "0" });
  const [formError, setFormError] = useState(null);
  const [statement, setStatement] = useState(null);
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  const submit = async (event) => {
    event.preventDefault();
    setFormError(null);
    try {
      await api.post("/purchases/suppliers", form);
      setOpen(false);
      setForm({ name: "", phone: "", address: "", opening_balance: "0" });
      reload();
    } catch (err) {
      setFormError(apiMessage(err));
    }
  };

  const showStatement = async (supplier) => {
    try {
      const { data: res } = await api.get(`/purchases/suppliers/${supplier.id}/statement`);
      setStatement(res.data);
    } catch (err) {
      setStatement({ error: apiMessage(err) });
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-extrabold">الموردون</h1>
        {canManage && <Button onClick={() => setOpen(true)}>+ مورد جديد</Button>}
      </div>
      <Card>
        <Alert>{error}</Alert>
        {loading ? (
          <Loading />
        ) : (
          <Table
            columns={[
              { key: "name", label: "اسم المورد" },
              { key: "phone", label: "الهاتف", render: (r) => r.phone || "—" },
              {
                key: "is_active",
                label: "الحالة",
                render: (r) => (r.is_active ? <Badge tone="green">نشط</Badge> : <Badge tone="red">موقوف</Badge>),
              },
              {
                key: "actions",
                label: "",
                render: (r) =>
                  canManage && (
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

      <Modal open={open} title="إضافة مورد" onClose={() => setOpen(false)}>
        <form onSubmit={submit} className="space-y-4">
          <Alert>{formError}</Alert>
          <Input label="اسم المورد" value={form.name} onChange={set("name")} required autoFocus />
          <div className="grid grid-cols-2 gap-4">
            <Input label="الهاتف" value={form.phone} onChange={set("phone")} />
            <Input label="رصيد افتتاحي" type="number" step="0.01" min="0" value={form.opening_balance} onChange={set("opening_balance")} />
          </div>
          <Input label="العنوان" value={form.address} onChange={set("address")} />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setOpen(false)}>
              إلغاء
            </Button>
            <Button type="submit">حفظ</Button>
          </div>
        </form>
      </Modal>

      <Modal
        open={!!statement}
        title={statement?.supplier ? `كشف حساب — ${statement.supplier.name}` : "كشف حساب"}
        onClose={() => setStatement(null)}
        wide
      >
        {statement?.error ? (
          <Alert>{statement.error}</Alert>
        ) : statement ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="rounded-lg bg-slate-50 p-3 text-center">
                <div className="text-xs font-bold text-slate-500">رصيد افتتاحي</div>
                <div className="text-lg font-extrabold">{money(statement.opening_balance)}</div>
              </div>
              <div className="rounded-lg bg-slate-50 p-3 text-center">
                <div className="text-xs font-bold text-slate-500">إجمالي الفواتير</div>
                <div className="text-lg font-extrabold">{money(statement.total_invoices)}</div>
              </div>
              <div className="rounded-lg bg-slate-50 p-3 text-center">
                <div className="text-xs font-bold text-slate-500">المسدد</div>
                <div className="text-lg font-extrabold">{money(statement.total_paid)}</div>
              </div>
              <div className="rounded-lg bg-rose-50 p-3 text-center">
                <div className="text-xs font-bold text-rose-700">المستحق للمورد</div>
                <div className="text-lg font-extrabold text-rose-800">{money(statement.balance)}</div>
              </div>
            </div>
            <Table
              columns={[
                { key: "id", label: "فاتورة #" },
                { key: "invoice_date", label: "التاريخ" },
                { key: "payment_method", label: "الدفع", render: (r) => (r.payment_method === "cash" ? "نقدي" : "آجل") },
                { key: "total", label: "الإجمالي", render: (r) => money(r.total) },
              ]}
              rows={statement.invoices}
              empty="لا توجد فواتير لهذا المورد."
            />
            {can("purchases.payments") && (
              <PaymentSection
                supplierId={statement.supplier.id}
                onPaid={() => showStatement(statement.supplier)}
              />
            )}
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
