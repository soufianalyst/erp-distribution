import { useState } from "react";
import { Alert, Badge, Button, Card, Input, Loading, PaginatedTable, Select, Table, money } from "../components/Ui";
import useFetch from "../hooks/useFetch";
import api, { apiMessage } from "../services/api";

const TYPE_LABELS = {
  asset: "أصول",
  liability: "التزامات",
  equity: "حقوق ملكية",
  revenue: "إيرادات",
  expense: "مصاريف",
};

const REFERENCE_LABELS = {
  purchase_invoice: "فاتورة شراء",
  supplier_payment: "سند صرف",
  sales_invoice: "فاتورة مبيعات",
  sales_return: "مرتجع مبيعات",
  customer_payment: "سند قبض",
  manual: "قيد يدوي",
};

const EMPTY_ITEM = { account_code: "", debit: "", credit: "" };

function ManualEntryForm({ accounts, onCreated }) {
  const [description, setDescription] = useState("");
  const [items, setItems] = useState([{ ...EMPTY_ITEM }, { ...EMPTY_ITEM }]);
  const [error, setError] = useState(null);
  const setItem = (index, key, value) =>
    setItems(items.map((item, i) => (i === index ? { ...item, [key]: value } : item)));

  const totalDebit = items.reduce((sum, i) => sum + Number(i.debit || 0), 0);
  const totalCredit = items.reduce((sum, i) => sum + Number(i.credit || 0), 0);
  const balanced = totalDebit === totalCredit && totalDebit > 0;

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    try {
      await api.post("/accounting/journal-entries", {
        description,
        items: items
          .filter((i) => i.account_code && (Number(i.debit) > 0 || Number(i.credit) > 0))
          .map((i) => ({
            account_code: i.account_code,
            debit: i.debit || "0",
            credit: i.credit || "0",
          })),
      });
      setDescription("");
      setItems([{ ...EMPTY_ITEM }, { ...EMPTY_ITEM }]);
      onCreated();
    } catch (err) {
      setError(apiMessage(err));
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <Alert>{error}</Alert>
      <Input
        label="البيان (وصف القيد)"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        required
        minLength={3}
      />
      <div>
        <div className="mb-2 flex items-center justify-between">
          <span className="text-sm font-bold text-slate-600">أطراف القيد</span>
          <Button type="button" variant="secondary" onClick={() => setItems([...items, { ...EMPTY_ITEM }])}>
            + طرف
          </Button>
        </div>
        {items.map((item, index) => (
          <div key={index} className="mb-2 grid grid-cols-12 items-end gap-2">
            <div className="col-span-6">
              <Select
                label={index === 0 ? "الحساب" : undefined}
                value={item.account_code}
                onChange={(e) => setItem(index, "account_code", e.target.value)}
                required
              >
                <option value="">— اختر الحساب —</option>
                {accounts.map((a) => (
                  <option key={a.code} value={a.code}>
                    {a.code} — {a.name}
                  </option>
                ))}
              </Select>
            </div>
            <div className="col-span-2">
              <Input
                label={index === 0 ? "مدين" : undefined}
                type="number"
                step="0.01"
                min="0"
                value={item.debit}
                onChange={(e) => setItem(index, "debit", e.target.value)}
                disabled={Number(item.credit) > 0}
              />
            </div>
            <div className="col-span-2">
              <Input
                label={index === 0 ? "دائن" : undefined}
                type="number"
                step="0.01"
                min="0"
                value={item.credit}
                onChange={(e) => setItem(index, "credit", e.target.value)}
                disabled={Number(item.debit) > 0}
              />
            </div>
            <div className="col-span-2">
              {items.length > 2 && (
                <Button type="button" variant="danger" onClick={() => setItems(items.filter((_, i) => i !== index))}>
                  ×
                </Button>
              )}
            </div>
          </div>
        ))}
      </div>
      <div className="flex items-center justify-between rounded-lg bg-slate-50 px-4 py-3 text-sm font-bold">
        <span>مجموع المدين: {money(totalDebit)}</span>
        <span>مجموع الدائن: {money(totalCredit)}</span>
        {balanced ? <Badge tone="green">متوازن ✓</Badge> : <Badge tone="red">غير متوازن</Badge>}
      </div>
      <Button type="submit" disabled={!balanced}>
        تسجيل القيد
      </Button>
    </form>
  );
}

function JournalEntriesList({ entries }) {
  const [page, setPage] = useState(0);
  const [term, setTerm] = useState("");
  const PAGE = 15;

  const filtered = entries.filter((e) => {
    if (!term.trim()) return true;
    const t = term.trim().toLowerCase();
    return (
      (e.description || "").toLowerCase().includes(t) ||
      (e.entry_date || "").includes(t) ||
      String(e.id).includes(t) ||
      (REFERENCE_LABELS[e.reference_type] || "").includes(t)
    );
  });

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE));
  const safePage = Math.min(page, totalPages - 1);
  const pageEntries = filtered.slice(safePage * PAGE, (safePage + 1) * PAGE);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input
          className="w-full max-w-xs rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-emerald-600"
          placeholder="بحث بالوصف أو التاريخ أو رقم القيد..."
          value={term}
          onChange={(e) => { setTerm(e.target.value); setPage(0); }}
        />
      </div>
      {pageEntries.length === 0 ? (
        <div className="py-10 text-center text-sm text-slate-400">لا توجد قيود بعد.</div>
      ) : (
        <div className="space-y-4">
          {pageEntries.map((entry) => (
            <div key={entry.id} className="rounded-lg border border-slate-200 p-4">
              <div className="mb-2 flex items-center justify-between">
                <div className="font-bold">{entry.description}</div>
                <div className="flex items-center gap-2 text-xs text-slate-500">
                  <Badge tone="blue">{REFERENCE_LABELS[entry.reference_type] || "—"}</Badge>
                  <span>{entry.entry_date}</span>
                  <span>قيد #{entry.id}</span>
                </div>
              </div>
              <Table
                columns={[
                  { key: "account", label: "الحساب", render: (r) => `${r.account.code} — ${r.account.name}` },
                  { key: "debit", label: "مدين", render: (r) => (Number(r.debit) ? money(r.debit) : "") },
                  { key: "credit", label: "دائن", render: (r) => (Number(r.credit) ? money(r.credit) : "") },
                ]}
                rows={entry.items}
              />
            </div>
          ))}
        </div>
      )}
      {filtered.length > PAGE && (
        <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
          <span>
            عرض {safePage * PAGE + 1}–{Math.min((safePage + 1) * PAGE, filtered.length)}{" "}
            من {filtered.length}
          </span>
          <div className="flex gap-1">
            <button onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={safePage === 0} className="rounded border border-slate-300 px-2 py-1 hover:bg-slate-50 disabled:opacity-40">← التالي</button>
            {Array.from({ length: totalPages }, (_, i) => i)
              .filter((i) => i === 0 || i === totalPages - 1 || Math.abs(i - safePage) <= 2)
              .reduce((acc, i, idx, arr) => { if (idx > 0 && i - arr[idx - 1] > 1) acc.push("..."); acc.push(i); return acc; }, [])
              .map((item, idx) =>
                item === "..." ? (
                  <span key={`e${idx}`} className="px-1 py-1">...</span>
                ) : (
                  <button key={item} onClick={() => setPage(item)} className={`rounded border px-2 py-1 ${item === safePage ? "border-emerald-600 bg-emerald-700 text-white" : "border-slate-300 hover:bg-slate-50"}`}>{item + 1}</button>
                )
              )}
            <button onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))} disabled={safePage >= totalPages - 1} className="rounded border border-slate-300 px-2 py-1 hover:bg-slate-50 disabled:opacity-40">السابق →</button>
          </div>
        </div>
      )}
    </div>
  );
}

export default function AccountingPage() {
  const [tab, setTab] = useState("journal");
  const accounts = useFetch(() => api.get("/accounting/accounts"));
  const entries = useFetch(() => api.get("/accounting/journal-entries"));
  const trialBalance = useFetch(() => api.get("/accounting/reports/trial-balance"));

  const TABS = [
    { id: "journal", label: "قيود اليومية" },
    { id: "manual", label: "+ قيد يدوي" },
    { id: "trial", label: "ميزان المراجعة" },
    { id: "chart", label: "دليل الحسابات" },
  ];

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-extrabold">الحسابات</h1>
      <div className="flex gap-2">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`rounded-lg px-4 py-2 text-sm font-bold ${
              tab === t.id ? "bg-emerald-700 text-white" : "bg-white text-slate-600 hover:bg-slate-50"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "journal" && (
        <Card title="قيود اليومية — تتولد تلقائياً من الفواتير والسندات">
          <Alert>{entries.error}</Alert>
          {entries.loading ? (
            <Loading />
          ) : (
            <JournalEntriesList entries={entries.data || []} />
          )}
        </Card>
      )}

      {tab === "manual" && (
        <Card title="قيد يومية يدوي — يجب أن يتساوى المدين مع الدائن">
          {accounts.loading ? (
            <Loading />
          ) : (
            <ManualEntryForm
              accounts={accounts.data || []}
              onCreated={() => {
                entries.reload();
                trialBalance.reload();
                setTab("journal");
              }}
            />
          )}
        </Card>
      )}

      {tab === "trial" && (
        <Card
          title="ميزان المراجعة"
          actions={
            trialBalance.data &&
            (trialBalance.data.is_balanced ? (
              <Badge tone="green">متوازن ✓</Badge>
            ) : (
              <Badge tone="red">غير متوازن!</Badge>
            ))
          }
        >
          <Alert>{trialBalance.error}</Alert>
          {trialBalance.loading ? (
            <Loading />
          ) : (
            <>
              <PaginatedTable
                columns={[
                  { key: "account_code", label: "الرقم" },
                  { key: "account_name", label: "الحساب" },
                  { key: "account_type", label: "النوع", render: (r) => TYPE_LABELS[r.account_type] },
                  { key: "total_debit", label: "مدين", render: (r) => money(r.total_debit) },
                  { key: "total_credit", label: "دائن", render: (r) => money(r.total_credit) },
                ]}
                rows={trialBalance.data?.rows}
                keyField="account_code"
                empty="لا توجد حركات محاسبية بعد."
                searchable
                searchPlaceholder="بحث بالحساب..."
                amountField="total_debit"
                amountLabel="المدين"
              />
              {trialBalance.data?.rows?.length > 0 && (
                <div className="mt-3 flex justify-end gap-8 border-t-2 border-slate-300 pt-3 font-extrabold">
                  <span>مجموع المدين: {money(trialBalance.data.total_debit)}</span>
                  <span>مجموع الدائن: {money(trialBalance.data.total_credit)}</span>
                </div>
              )}
            </>
          )}
        </Card>
      )}

      {tab === "chart" && (
        <Card title="دليل الحسابات">
          <Alert>{accounts.error}</Alert>
          {accounts.loading ? (
            <Loading />
          ) : (
            <PaginatedTable
              columns={[
                { key: "code", label: "الرقم" },
                { key: "name", label: "اسم الحساب" },
                { key: "type", label: "النوع", render: (r) => <Badge tone="blue">{TYPE_LABELS[r.type]}</Badge> },
                {
                  key: "is_system",
                  label: "",
                  render: (r) => (r.is_system ? <Badge>حساب نظام</Badge> : null),
                },
              ]}
              rows={accounts.data}
              searchable
              searchPlaceholder="بحث بالرقم أو اسم الحساب..."
            />
          )}
        </Card>
      )}
    </div>
  );
}
