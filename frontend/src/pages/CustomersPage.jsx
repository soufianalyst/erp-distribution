// Customer file: who they are, which price tier they buy at, the credit limit
// they may not exceed, and which salesman owns the relationship.
//
// Also where receipts (سند قبض) are recorded against a customer's balance and
// where their statement is read — the document handed over when settling up.
import { useState } from "react";
import {
  CancelButton,
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

/** Record a receipt against this customer's balance and show their statement. */
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
    <form onSubmit={submit} className="rounded-lg border border-emerald-200 dark:border-emerald-900 bg-emerald-50/60 p-4">
      <div className="mb-2 text-sm font-extrabold text-emerald-800 dark:text-emerald-300">سند قبض جديد</div>
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

  // Portal account dialog: balance-less credentials for the customer's login.
  const [portal, setPortal] = useState(null);
  const [portalForm, setPortalForm] = useState({ username: "", password: "" });
  const [portalBusy, setPortalBusy] = useState(false);
  const [portalError, setPortalError] = useState(null);
  const [portalSaved, setPortalSaved] = useState(null);

  const openPortal = async (customer) => {
    setPortalError(null);
    setPortalSaved(null);
    setPortalForm({ username: "", password: "" });
    setPortal(customer);
    try {
      const { data: res } = await api.get(`/portal/accounts/${customer.id}`);
      const account = res.data;
      if (account) {
        setPortalForm({ username: account.username, password: "" });
        setPortalSaved({
          text: account.is_active ? `موجود (@${account.username})` : "موجود لكنه موقوف",
          tone: account.is_active ? "green" : "amber",
        });
      }
    } catch {
      // No account yet — plain create mode.
    }
  };

  const savePortal = async (event) => {
    event.preventDefault();
    setPortalBusy(true);
    setPortalError(null);
    try {
      if (portalSaved && portalForm.password) {
        // Account exists: reset password (and reactivate) only.
        await api.patch(`/portal/accounts/${portal.id}`, {
          password: portalForm.password,
          is_active: true,
        });
      } else if (portalSaved) {
        // No password change requested — nothing to do.
        return;
      } else {
        await api.post(`/portal/accounts/${portal.id}`, {
          username: portalForm.username,
          password: portalForm.password,
        });
      }
      setPortalSaved({ text: "تم الحفظ", tone: "green" });
      setPortalForm({ username: portalForm.username, password: "" });
    } catch (err) {
      setPortalError(apiMessage(err));
    } finally {
      setPortalBusy(false);
    }
  };

  const deactivatePortal = async () => {
    if (!window.confirm("إيقاف حساب البوابة يمنع العميل من الدخول. هل تريد المتابعة؟")) return;
    setPortalError(null);
    try {
      await api.patch(`/portal/accounts/${portal.id}`, { is_active: false });
      setPortalSaved({ text: "تم إيقاف الحساب", tone: "red" });
    } catch (err) {
      setPortalError(apiMessage(err));
    }
  };

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
      <div className="flex flex-wrap items-center justify-between gap-3">
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
                  <div className="flex flex-wrap gap-2">
                    {canManage && (
                      <Button variant="secondary" onClick={() => openPortal(r)}>
                        حساب البوابة
                      </Button>
                    )}
                    <Button variant="secondary" onClick={() => showStatement(r)}>
                      كشف حساب
                    </Button>
                  </div>
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
            <CancelButton onClose={() => setOpen(false)} />
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
              <div className="rounded-lg bg-slate-50 dark:bg-slate-800/60 p-3 text-center">
                <div className="text-xs font-bold text-slate-500 dark:text-slate-400">إجمالي الفواتير</div>
                <div className="text-lg font-extrabold">{money(statement.total_invoices)}</div>
              </div>
              <div className="rounded-lg bg-slate-50 dark:bg-slate-800/60 p-3 text-center">
                <div className="text-xs font-bold text-slate-500 dark:text-slate-400">المرتجعات</div>
                <div className="text-lg font-extrabold">{money(statement.total_returns)}</div>
              </div>
              <div className="rounded-lg bg-slate-50 dark:bg-slate-800/60 p-3 text-center">
                <div className="text-xs font-bold text-slate-500 dark:text-slate-400">المسدد</div>
                <div className="text-lg font-extrabold">{money(statement.total_paid)}</div>
              </div>
              <div className="rounded-lg bg-emerald-50 dark:bg-emerald-950/40 p-3 text-center">
                <div className="text-xs font-bold text-emerald-700 dark:text-emerald-400">الرصيد المستحق</div>
                <div className="text-lg font-extrabold text-emerald-800 dark:text-emerald-300">{money(statement.balance)}</div>
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

      <Modal
        open={!!portal}
        title={`حساب البوابة — ${portal?.name || ""}`}
        onClose={() => setPortal(null)}
      >
        <form onSubmit={savePortal} className="space-y-4">
          <Alert>{portalError}</Alert>
          {portalSaved && (
            <div
              className={`rounded-lg border px-4 py-3 text-sm font-bold ${
                portalSaved.tone === "green"
                  ? "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-200"
                  : portalSaved.tone === "red"
                  ? "border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-900 dark:bg-rose-950/50 dark:text-rose-200"
                  : "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950/50 dark:text-amber-200"
              }`}
            >
              {portalSaved.text}
            </div>
          )}
          <p className="text-sm text-slate-500 dark:text-slate-400">
            يصل العميل للنظام بحساب خاص به ليتابع كشف حسابه ويقدّم طلباته — بلا أي
            صلاحيات داخلية.
          </p>
          {portalSaved && !portalSaved.text.includes("تم") ? (
            <Input
              label="كلمة مرور جديدة (اختياري — لتغييرها)"
              type="password"
              value={portalForm.password}
              onChange={(e) => setPortalForm({ ...portalForm, password: e.target.value })}
              placeholder="8 أحرف على الأقل"
            />
          ) : (
            <>
              <Input
                label="اسم المستخدم"
                value={portalForm.username}
                onChange={(e) => setPortalForm({ ...portalForm, username: e.target.value })}
                required
                autoFocus
              />
              <Input
                label="كلمة المرور"
                type="password"
                value={portalForm.password}
                onChange={(e) => setPortalForm({ ...portalForm, password: e.target.value })}
                required
                minLength={8}
              />
            </>
          )}
          {portalSaved && portalSaved.text.includes("موجود") && (
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="danger" onClick={deactivatePortal}>
                إيقاف الحساب
              </Button>
            </div>
          )}
          <div className="flex justify-end gap-2">
            <CancelButton onClose={() => setPortal(null)} />
            {portalSaved ? (
              <Button type="submit" disabled={portalBusy || !portalForm.password}>
                {portalBusy ? "جارٍ الحفظ..." : "حفظ كلمة المرور"}
              </Button>
            ) : (
              <Button type="submit" disabled={portalBusy}>
                {portalBusy ? "جارٍ الإنشاء..." : "إنشاء حساب البوابة"}
              </Button>
            )}
          </div>
        </form>
      </Modal>
    </div>
  );
}
