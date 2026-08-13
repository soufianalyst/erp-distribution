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
  qty,
} from "../components/Ui";
import { useAuth } from "../context/AuthContext";
import useFetch from "../hooks/useFetch";
import api, { apiMessage } from "../services/api";

const TIER_LABELS = { wholesale: "جملة", half_wholesale: "نصف جملة", retail: "تجزئة" };

const EMPTY_FORM = {
  name: "",
  phone: "",
  address: "",
  // The customer's own registration numbers, printed on the المواد المقننة
  // declaration. Optional: most shops are billed without either.
  tax_number: "",
  statistical_number: "",
  price_tier: "wholesale",
  credit_limit: "0",
  salesman_id: "",
};

// The same fields, read back off a customer for editing. Nulls become "" because a
// controlled input handed null switches itself to uncontrolled and warns.
const formFrom = (customer) => ({
  name: customer.name ?? "",
  phone: customer.phone ?? "",
  address: customer.address ?? "",
  tax_number: customer.tax_number ?? "",
  statistical_number: customer.statistical_number ?? "",
  price_tier: customer.price_tier ?? "wholesale",
  credit_limit: String(customer.credit_limit ?? "0"),
  salesman_id: customer.salesman_id ? String(customer.salesman_id) : "",
});

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


/** المواد المقننة — the customer's register of regulated goods.
 *
 * It is a record, not a document: the goods on it were charged on their own sales
 * invoices, and nothing here bills anybody or reaches the ledger. So the screen shows a
 * *value* rather than an amount due, and says so, twice — once in the summary and once
 * on the printed declaration. The register is also live: quantities and prices are read
 * from the invoice lines each time it loads, so a correction, a cancellation or a credit
 * note shows up here without anyone re-filing anything.
 *
 * One register is open per customer at a time. Closing it freezes what the declaration
 * says and opens the successor in the same breath, so a line tagged a second later still
 * has somewhere to go.
 */
function RationedDialog({ customer, onClose }) {
  const { can } = useAuth();
  const canManage = can("sales.rationed_manage");
  // null = the customer's currently open register. An id = one of the closed ones,
  // opened from the history list for reading and reprinting.
  const [recordId, setRecordId] = useState(null);
  const [notes, setNotes] = useState("");
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);

  const register = useFetch(
    () =>
      recordId
        ? api.get(`/sales/rationed/${recordId}`)
        : api.get(`/sales/customers/${customer.id}/rationed`),
    [customer.id, recordId]
  );
  const history = useFetch(
    () => api.get(`/sales/customers/${customer.id}/rationed/history`),
    [customer.id]
  );
  const taxRates = useFetch(() =>
    api.get("/settings/tax-rates", {
      params: { active_only: true, in_scope_only: true },
    })
  );

  const reg = register.data;
  // Which rates are ticked comes from the register itself, not from local state: the
  // selection is stored on the record so two prints of the same declaration cannot
  // disagree about the tax on it.
  const selected = (reg?.taxes ?? [])
    .map((t) => t.tax_rate_id)
    .filter((id) => id != null);

  const toggleTax = async (taxId) => {
    const next = selected.includes(taxId)
      ? selected.filter((id) => id !== taxId)
      : [...selected, taxId];
    setError(null);
    setBusy(true);
    try {
      await api.put(`/sales/rationed/${reg.record_id}/taxes`, { tax_rate_ids: next });
      register.reload();
    } catch (err) {
      setError(apiMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const removeLine = async (entry) => {
    if (
      !window.confirm(
        `حذف "${entry.product_name}" من سجل المواد المقننة؟ الفاتورة ` +
          `${entry.invoice_reference} لا تتأثر.`
      )
    ) {
      return;
    }
    setError(null);
    try {
      await api.delete(`/sales/rationed/lines/${entry.line_id}`);
      register.reload();
    } catch (err) {
      setError(apiMessage(err));
    }
  };

  const close = async () => {
    if (
      !window.confirm(
        "إقفال السجل؟ لن يمكن تعديله بعد ذلك، وسيُفتح للعميل سجل جديد فوراً."
      )
    ) {
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const { data: res } = await api.post(
        `/sales/rationed/${reg.record_id}/close`,
        { notes: notes || null }
      );
      setNotes("");
      setNotice(
        `تم إقفال السجل ق-${res.data.closed.record_id} وفتح سجل جديد للعميل.`
      );
      register.reload();
      history.reload();
    } catch (err) {
      setError(apiMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const print = (id) => window.open(`/print/rationed/${id}`, "_blank");

  return (
    <Modal open title={`المواد المقننة — ${customer.name}`} onClose={onClose} wide>
      <div className="space-y-4">
        <Alert>{error || register.error}</Alert>
        <Alert tone="success">{notice}</Alert>

        {register.loading || !reg ? (
          <Loading />
        ) : (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-indigo-200 dark:border-indigo-900 bg-indigo-50/60 dark:bg-indigo-950/30 p-3">
              <div className="flex flex-wrap items-center gap-2 text-sm font-bold text-indigo-900 dark:text-indigo-200">
                <span>سجل رقم ق-{reg.record_id}</span>
                {reg.is_open ? (
                  <Badge tone="green">مفتوح</Badge>
                ) : (
                  <Badge tone="slate">مقفل</Badge>
                )}
                <span className="text-indigo-700 dark:text-indigo-300">
                  فُتح: {reg.opened_at?.slice(0, 10)}
                  {reg.closed_at ? ` — أُقفل: ${reg.closed_at.slice(0, 10)}` : ""}
                </span>
                {reg.closed_by_name && (
                  <span className="text-xs">بواسطة {reg.closed_by_name}</span>
                )}
              </div>
              <div className="flex flex-wrap gap-2">
                {recordId && (
                  <Button variant="secondary" onClick={() => setRecordId(null)}>
                    ← السجل المفتوح
                  </Button>
                )}
                {canManage && (
                  <Button variant="secondary" onClick={() => print(reg.record_id)}>
                    🖨️ طباعة البيان
                  </Button>
                )}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="rounded-lg bg-slate-50 dark:bg-slate-800/60 p-3 text-center">
                <div className="text-xs font-bold text-slate-500 dark:text-slate-400">
                  عدد الأسطر
                </div>
                <div className="text-lg font-extrabold">{reg.line_count}</div>
              </div>
              <div className="rounded-lg bg-slate-50 dark:bg-slate-800/60 p-3 text-center">
                <div className="text-xs font-bold text-slate-500 dark:text-slate-400">
                  إجمالي الكميات
                </div>
                <div className="text-lg font-extrabold">{qty(reg.total_quantity)}</div>
              </div>
              <div className="rounded-lg bg-slate-50 dark:bg-slate-800/60 p-3 text-center">
                {/* "قيمة" and not "مستحق": these goods were already billed. */}
                <div className="text-xs font-bold text-slate-500 dark:text-slate-400">
                  قيمة المواد
                </div>
                <div className="text-lg font-extrabold">{money(reg.total_value)}</div>
              </div>
              <div className="rounded-lg bg-indigo-50 dark:bg-indigo-950/40 p-3 text-center">
                <div className="text-xs font-bold text-indigo-700 dark:text-indigo-300">
                  إجمالي البيان (مع الضرائب)
                </div>
                <div className="text-lg font-extrabold text-indigo-800 dark:text-indigo-200">
                  {money(reg.grand_total)}
                </div>
              </div>
            </div>

            <div className="rounded-lg border border-amber-200 dark:border-amber-900 bg-amber-50/70 dark:bg-amber-950/30 p-3 text-sm font-bold text-amber-800 dark:text-amber-300">
              هذا سجل وليس فاتورة: المواد أعلاه محسوبة ومحصّلة على فواتير البيع
              المذكورة أمام كل سطر، ولا يُرحّل هذا السجل محاسبياً.
            </div>

            {/* Which taxes the printed declaration shows. Stored on the register, so
                the choice made here is the choice that prints — today and on a
                reprint next year. */}
            <div>
              <span className="mb-1 block text-sm font-bold text-slate-600 dark:text-slate-400">
                الضرائب التي تظهر على البيان المطبوع
                {!reg.is_open && " (السجل مقفل — للعرض فقط)"}
              </span>
              <div className="flex flex-wrap gap-3 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 p-3">
                {(taxRates.data ?? []).length === 0 && (
                  <span className="text-sm text-slate-400 dark:text-slate-500">
                    لا توجد ضرائب مفعّلة.
                  </span>
                )}
                {(taxRates.data ?? []).map((t) => (
                  <label
                    key={t.id}
                    className="flex items-center gap-2 text-sm font-bold text-slate-700 dark:text-slate-300"
                  >
                    <input
                      type="checkbox"
                      checked={selected.includes(t.id)}
                      disabled={!canManage || !reg.is_open || busy}
                      onChange={() => toggleTax(t.id)}
                    />
                    {t.name} ({t.rate}%)
                  </label>
                ))}
              </div>
              {reg.taxes.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-4 text-sm font-bold">
                  {reg.taxes.map((tax) => (
                    <span key={tax.name}>
                      {tax.name} ({tax.rate}%): {money(tax.amount)}
                    </span>
                  ))}
                  <span>إجمالي الضرائب: {money(reg.tax_total)}</span>
                </div>
              )}
            </div>

            <Table
              columns={[
                { key: "product_name", label: "الصنف" },
                { key: "invoice_reference", label: "الفاتورة" },
                { key: "invoice_date", label: "تاريخ الفاتورة" },
                {
                  key: "net_quantity",
                  label: "الكمية",
                  render: (r) => (
                    <span>
                      {qty(r.net_quantity)}
                      {Number(r.returned_quantity) > 0 && (
                        <span className="text-xs text-rose-600 dark:text-rose-400">
                          {" "}
                          (مرتجع {qty(r.returned_quantity)})
                        </span>
                      )}
                    </span>
                  ),
                },
                { key: "unit_name", label: "الوحدة" },
                {
                  key: "unit_price",
                  label: "سعر الوحدة",
                  render: (r) => money(r.unit_price),
                },
                {
                  key: "net_total",
                  label: "الإجمالي",
                  render: (r) => money(r.net_total),
                },
                ...(canManage && reg.is_open
                  ? [
                      {
                        key: "actions",
                        label: "",
                        render: (r) => (
                          <Button variant="danger" onClick={() => removeLine(r)}>
                            حذف
                          </Button>
                        ),
                      },
                    ]
                  : []),
              ]}
              rows={reg.entries}
              empty="لم تُسجَّل مواد مقننة لهذا العميل بعد. تُحدَّد من داخل فاتورة البيع."
            />

            {canManage && reg.is_open && (
              <div className="rounded-lg border border-slate-300 dark:border-slate-600 p-3">
                <div className="mb-2 text-sm font-extrabold">
                  إقفال السجل وإصدار البيان
                </div>
                <div className="grid grid-cols-1 items-end gap-3 sm:grid-cols-[1fr_auto]">
                  <Input
                    label="ملاحظات تُطبع على البيان (اختياري)"
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                  />
                  <Button
                    variant="secondary"
                    onClick={close}
                    disabled={busy || !reg.line_count}
                  >
                    {busy ? "جارٍ الإقفال..." : "إقفال السجل"}
                  </Button>
                </div>
                {!reg.line_count && (
                  <div className="mt-1 text-xs font-bold text-slate-500 dark:text-slate-400">
                    لا يمكن إقفال سجل فارغ — بيان بلا أسطر سيظهر في التاريخ كشهر لم
                    يستلم فيه العميل شيئاً.
                  </div>
                )}
              </div>
            )}

            {(history.data ?? []).length > 0 && (
              <div>
                <div className="mb-2 text-sm font-bold text-slate-600 dark:text-slate-400">
                  السجلات المقفلة ({history.data.length})
                </div>
                <div className="flex flex-wrap gap-2">
                  {history.data.map((h) => (
                    <button
                      key={h.id}
                      type="button"
                      onClick={() => setRecordId(h.id)}
                      className={`rounded-lg border px-3 py-1.5 text-sm font-bold ${
                        recordId === h.id
                          ? "border-indigo-600 bg-indigo-600 text-white"
                          : "border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300"
                      }`}
                    >
                      ق-{h.id} — {h.closed_at?.slice(0, 10)}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </Modal>
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
  // The customer being edited, or null when the dialog is adding a new one. One form
  // serves both: the fields are identical, and a second copy of them is a second place
  // to forget a field the next time one is added.
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [formError, setFormError] = useState(null);
  const [statement, setStatement] = useState(null);
  // The regulated-goods register opens on its own dialog rather than inside the
  // statement: it is a separate document with its own tax choice and its own close
  // action, and burying it under the balance would suggest it belongs to it.
  const [rationed, setRationed] = useState(null);
  // Confirmation for the portal-access section below the list.
  const [notice, setNotice] = useState(null);
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  const startAdd = () => {
    setEditing(null);
    setForm(EMPTY_FORM);
    setFormError(null);
    setOpen(true);
  };

  const startEdit = (customer) => {
    setEditing(customer);
    setForm(formFrom(customer));
    setFormError(null);
    setOpen(true);
  };

  const submit = async (event) => {
    event.preventDefault();
    setFormError(null);
    const payload = { ...form, salesman_id: form.salesman_id || null };
    try {
      if (editing) {
        await api.patch(`/sales/customers/${editing.id}`, payload);
      } else {
        await api.post("/sales/customers", payload);
      }
      setOpen(false);
      setEditing(null);
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
        {canManage && <Button onClick={startAdd}>+ عميل جديد</Button>}
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
                      <Button variant="secondary" onClick={() => startEdit(r)}>
                        تعديل
                      </Button>
                    )}
                    <Button variant="secondary" onClick={() => showStatement(r)}>
                      كشف حساب
                    </Button>
                    {can("sales.rationed_view") && (
                      <Button variant="secondary" onClick={() => setRationed(r)}>
                        المواد المقننة
                      </Button>
                    )}
                  </div>
                ),
              },
            ]}
            rows={data}
          />
        )}
      </Card>

      <Modal
        open={open}
        title={editing ? `تعديل بيانات — ${editing.name}` : "إضافة عميل جديد"}
        onClose={() => setOpen(false)}
      >
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
          {/* Printed on the customer's المواد المقننة declaration, which is why they
              live on the customer file and not on the document: the numbers identify
              the shop, and every declaration it ever gets should carry the same ones. */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Input
              label="رقم التعريف الضريبي (NIF) — اختياري"
              value={form.tax_number}
              onChange={set("tax_number")}
              maxLength={50}
            />
            <Input
              label="رقم التعريف الإحصائي (NIS) — اختياري"
              value={form.statistical_number}
              onChange={set("statistical_number")}
              maxLength={50}
            />
          </div>
          <div className="flex justify-end gap-2">
            <CancelButton onClose={() => setOpen(false)} />
            <Button type="submit">{editing ? "حفظ التعديلات" : "حفظ العميل"}</Button>
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

      {rationed && (
        <RationedDialog customer={rationed} onClose={() => setRationed(null)} />
      )}

      {can("customers.portal_access") ? (
        <>
          <Alert tone="success">{notice}</Alert>
          <PortalAccounts onNotice={setNotice} />
        </>
      ) : null}
    </div>
  );
}
