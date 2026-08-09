// Customer file: who they are, which price tier they buy at, the credit limit
// they may not exceed, and which salesman owns the relationship.
//
// Also where receipts (سند قبض) are recorded against a customer's balance and
// where their statement is read — the document handed over when settling up.
//
// Portal access lives here too: giving a shop a way to sign in is administration
// of that customer, not review of the requests they later send. Those are two
// different jobs held by two different permissions, so they sit on two screens.
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

function AccountDialog({ onClose, onDone }) {
  const [customerId, setCustomerId] = useState("");
  const [loginId, setLoginId] = useState("");
  const [password, setPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const customers = useFetch(() => api.get("/sales/customers"));

  const submit = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const { data } = await api.post("/customer-logins", {
        customer_id: Number(customerId),
        login_id: loginId,
        temporary_password: password,
      });
      onDone(data.message);
    } catch (err) {
      setError(apiMessage(err));
      setSaving(false);
    }
  };

  return (
    <Modal open title="فتح حساب بوابة لعميل" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <Select
          label="العميل"
          value={customerId}
          onChange={(e) => setCustomerId(e.target.value)}
          required
        >
          <option value="">— اختر العميل —</option>
          {(customers.data ?? [])
            .filter((c) => c.is_active)
            .map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
        </Select>
        <Input
          label="معرّف الدخول (رقم الجوال أو البريد)"
          value={loginId}
          onChange={(e) => setLoginId(e.target.value)}
          required
          minLength={3}
          maxLength={120}
        />
        <Input
          label="كلمة مرور مؤقتة"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          minLength={8}
          maxLength={200}
        />
        {/* Said plainly, because the office hands this over by phone and the
            portal refuses everything until the customer replaces it. */}
        <p className="text-sm text-slate-500 dark:text-slate-400">
          سلّم العميل كلمة المرور المؤقتة بنفسك؛ سيُطلب منه تغييرها عند أول دخول،
          ولن يستطيع استخدام البوابة قبل ذلك.
        </p>
        <Alert>{error}</Alert>
        <div className="flex justify-end gap-2">
          <CancelButton onClose={onClose} />
          <Button type="submit" disabled={saving}>
            {saving ? "جارٍ الفتح…" : "فتح الحساب"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function ResetDialog({ account, onClose, onDone }) {
  const [password, setPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const submit = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const { data } = await api.put(`/customer-logins/${account.id}`, {
        temporary_password: password,
      });
      onDone(data.message);
    } catch (err) {
      setError(apiMessage(err));
      setSaving(false);
    }
  };

  return (
    <Modal open title={`كلمة مرور جديدة لـ ${account.customer_name}`} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <Input
          label="كلمة مرور مؤقتة"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          minLength={8}
          maxLength={200}
          autoFocus
        />
        <p className="text-sm text-slate-500 dark:text-slate-400">
          هذا أيضاً يفكّ الإيقاف المؤقت الناتج عن محاولات دخول خاطئة.
        </p>
        <Alert>{error}</Alert>
        <div className="flex justify-end gap-2">
          <CancelButton onClose={onClose} />
          <Button type="submit" disabled={saving}>
            {saving ? "جارٍ الحفظ…" : "حفظ"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function PortalAccounts({ onNotice }) {
  const [creating, setCreating] = useState(false);
  const [resetting, setResetting] = useState(null);
  const [error, setError] = useState(null);
  const accounts = useFetch(() => api.get("/customer-logins"));

  const toggle = async (account) => {
    setError(null);
    try {
      const { data } = await api.put(`/customer-logins/${account.id}`, {
        is_active: !account.is_active,
      });
      onNotice(data.message);
      accounts.reload();
    } catch (err) {
      setError(apiMessage(err));
    }
  };

  const remove = async (account) => {
    // Says plainly what survives, because "delete the account" reads to most
    // people as "delete the customer" — and it is not that.
    if (
      !window.confirm(
        `حذف حساب دخول «${account.customer_name}» نهائياً؟\n\n` +
          "العميل وفواتيره وطلباته تبقى كما هي — يُحذف فقط دخوله إلى البوابة. " +
          "إن كنت تنوي إيقافه مؤقتاً فاستخدم «إيقاف»."
      )
    )
      return;
    setError(null);
    try {
      const { data } = await api.delete(`/customer-logins/${account.id}`);
      onNotice(data.message);
      accounts.reload();
    } catch (err) {
      setError(apiMessage(err));
    }
  };

  const columns = [
    { key: "customer_name", label: "العميل" },
    { key: "login_id", label: "معرّف الدخول" },
    {
      key: "state",
      label: "الحالة",
      search: (row) => (row.is_active ? "مفعل" : "موقوف"),
      render: (row) => (
        <div className="flex flex-wrap gap-1">
          <Badge tone={row.is_active ? "green" : "slate"}>
            {row.is_active ? "مفعّل" : "موقوف"}
          </Badge>
          {row.is_locked ? <Badge tone="red">موقوف مؤقتاً</Badge> : null}
          {row.must_change_password ? (
            <Badge tone="amber">بانتظار تغيير كلمة المرور</Badge>
          ) : null}
        </div>
      ),
    },
    {
      key: "last_login_at",
      label: "آخر دخول",
      render: (row) =>
        row.last_login_at ? new Date(row.last_login_at).toLocaleString("ar") : "لم يدخل بعد",
    },
    {
      key: "actions",
      label: "",
      sortable: false,
      render: (row) => (
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={() => setResetting(row)}>
            كلمة مرور جديدة
          </Button>
          <Button
            variant={row.is_active ? "danger" : "secondary"}
            onClick={() => toggle(row)}
          >
            {row.is_active ? "إيقاف" : "إعادة تفعيل"}
          </Button>
          <Button variant="danger" onClick={() => remove(row)}>
            حذف
          </Button>
        </div>
      ),
    },
  ];

  return (
    <Card
      title="حسابات الدخول إلى بوابة العملاء"
      actions={<Button onClick={() => setCreating(true)}>فتح حساب جديد</Button>}
    >
      <Alert>{error ?? accounts.error}</Alert>
      <Table
        columns={columns}
        rows={accounts.data ?? []}
        empty="لم يُفتح أي حساب بوابة بعد."
      />
      {creating ? (
        <AccountDialog
          onClose={() => setCreating(false)}
          onDone={(message) => {
            setCreating(false);
            onNotice(message);
            accounts.reload();
          }}
        />
      ) : null}
      {resetting ? (
        <ResetDialog
          account={resetting}
          onClose={() => setResetting(null)}
          onDone={(message) => {
            setResetting(null);
            onNotice(message);
            accounts.reload();
          }}
        />
      ) : null}
    </Card>
  );
}


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
  // Confirmation for the portal-access section below the list.
  const [notice, setNotice] = useState(null);
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

      {can("customers.portal_access") ? (
        <>
          <Alert tone="success">{notice}</Alert>
          <PortalAccounts onNotice={setNotice} />
        </>
      ) : null}
    </div>
  );
}
