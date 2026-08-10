// The accountant's workspace: the chart of accounts, the automatic journal
// entries every module posts, the trial balance, income statement and balance
// sheet, and bank reconciliation.
//
// Nothing here creates business activity — sales, purchases and stock movements
// post their own entries. This page is where those postings are reviewed,
// where a manual correcting entry can be made, and where the books are checked
// against the bank.
import { useState } from "react";
import { Alert, Badge, Button, Card, Input, Loading, Modal, Select, Stat, Table, money } from "../components/Ui";
import useDebouncedValue from "../hooks/useDebouncedValue";
import useFetch from "../hooks/useFetch";
import api, { apiMessage } from "../services/api";

// Matches the shared Table's own page size, so the pager and the server agree on
// what "a page" means.
const JOURNAL_PAGE_SIZE = 15;

const TYPE_LABELS = {
  asset: "أصول",
  liability: "التزامات",
  equity: "حقوق ملكية",
  revenue: "إيرادات",
  expense: "مصاريف",
};

// Every reference_type the backend posts an entry under. It had drifted to four of
// the seventeen, so most rows in the journal read "—" and you could not tell a
// collection from a stocktake. `referenceLabel` falls back to the raw type rather
// than a dash, so the next one added upstream degrades to something readable.
const REFERENCE_LABELS = {
  sales_invoice: "فاتورة مبيعات",
  sales_invoice_payment: "تحصيل فاتورة مبيعات",
  sales_return: "مرتجع مبيعات",
  sales_return_cancel: "إلغاء مرتجع مبيعات",
  customer_payment: "سند قبض",
  customer_credit: "رصيد دائن لعميل",
  purchase_invoice: "فاتورة شراء",
  purchase_invoice_payment: "سداد فاتورة شراء",
  purchase_return: "مرتجع مشتريات",
  supplier_payment: "سند صرف",
  expense: "مصروف",
  expense_payment: "سداد مصروف",
  stock_receipt: "استلام مخزون",
  stock_adjustment: "تعديل/إتلاف مخزون",
  stock_adjustment_cancel: "إلغاء تعديل مخزون",
  stocktake: "ترحيل جرد",
  manual: "قيد يدوي",
};

const referenceLabel = (type) => REFERENCE_LABELS[type] || type || "—";

// A balanced entry's debits equal its credits, so either side is "the amount".
const entryTotal = (entry) =>
  (entry.items || []).reduce((sum, item) => sum + Number(item.debit || 0), 0);

const DIRECTION_LABELS = { in: "وارد", out: "صادر" };

const EMPTY_BANK_LINE = { line_date: "", description: "", amount: "", direction: "in" };

/**
 * Bank reconciliation: the bank's statement on one side, our own bank-account
 * journal items on the other, matched one to one.
 *
 * Both sides must be unmatched before they can be tied together, so one bank
 * movement can never be reconciled against two entries.
 */
function BankReconciliationTab() {
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [notice, setNotice] = useState(null);
  const [matchingLine, setMatchingLine] = useState(null);
  const [form, setForm] = useState({ ...EMPTY_BANK_LINE });
  const [formError, setFormError] = useState(null);

  const lines = useFetch(
    () =>
      api.get("/accounting/bank-reconciliation/lines", {
        params: { date_from: dateFrom || undefined, date_to: dateTo || undefined },
      }),
    [dateFrom, dateTo]
  );
  const unmatched = useFetch(() => api.get("/accounting/bank-reconciliation/unmatched-entries"));
  const summary = useFetch(
    () =>
      api.get("/accounting/bank-reconciliation/summary", {
        params: { date_from: dateFrom || undefined, date_to: dateTo || undefined },
      }),
    [dateFrom, dateTo]
  );

  const reloadAll = () => {
    lines.reload();
    unmatched.reload();
    summary.reload();
  };

  const submitLine = async (event) => {
    event.preventDefault();
    setFormError(null);
    try {
      await api.post("/accounting/bank-reconciliation/lines", form);
      setForm({ ...EMPTY_BANK_LINE });
      setNotice("تم إضافة بند كشف الحساب بنجاح.");
      reloadAll();
    } catch (err) {
      setFormError(apiMessage(err));
    }
  };

  const confirmMatch = async (journalItemId) => {
    try {
      await api.post(`/accounting/bank-reconciliation/lines/${matchingLine.id}/match`, {
        journal_item_id: journalItemId,
      });
      setMatchingLine(null);
      setNotice("تمت المطابقة بنجاح.");
      reloadAll();
    } catch (err) {
      alert(apiMessage(err));
    }
  };

  const unmatchLine = async (line) => {
    try {
      await api.post(`/accounting/bank-reconciliation/lines/${line.id}/unmatch`);
      setNotice("تم التراجع عن المطابقة.");
      reloadAll();
    } catch (err) {
      alert(apiMessage(err));
    }
  };

  return (
    <div className="space-y-6">
      <Card title="إضافة بند من كشف الحساب البنكي">
        <form onSubmit={submitLine} className="space-y-4">
          <Alert>{formError}</Alert>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
            <Input
              label="التاريخ"
              type="date"
              value={form.line_date}
              onChange={(e) => setForm({ ...form, line_date: e.target.value })}
              required
            />
            <Input
              label="الوصف"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              required
            />
            <Input
              label="المبلغ"
              type="number"
              step="0.01"
              min="0.01"
              value={form.amount}
              onChange={(e) => setForm({ ...form, amount: e.target.value })}
              required
            />
            <Select
              label="الاتجاه"
              value={form.direction}
              onChange={(e) => setForm({ ...form, direction: e.target.value })}
            >
              <option value="in">وارد (إيداع)</option>
              <option value="out">صادر (سحب)</option>
            </Select>
          </div>
          <Button type="submit">إضافة البند</Button>
        </form>
      </Card>

      <Card title="ملخص المطابقة">
        <div className="mb-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Input label="من تاريخ" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          <Input label="إلى تاريخ" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </div>
        {summary.data && (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
            <Stat label="إجمالي البنود" value={summary.data.total_lines} />
            <Stat label="مطابقة" value={summary.data.matched_count} tone="emerald" />
            <Stat label="غير مطابقة" value={summary.data.unmatched_count} tone="amber" />
            <Stat label="إجمالي الوارد" value={money(summary.data.total_in)} />
            <Stat label="إجمالي الصادر" value={money(summary.data.total_out)} />
          </div>
        )}
      </Card>

      <Card title="بنود كشف الحساب">
        <Alert tone="success">{notice}</Alert>
        <Alert>{lines.error}</Alert>
        {lines.loading ? (
          <Loading />
        ) : (
          <Table
            columns={[
              { key: "line_date", label: "التاريخ" },
              { key: "description", label: "الوصف" },
              {
                key: "direction",
                label: "الاتجاه",
                render: (r) => (
                  <Badge tone={r.direction === "in" ? "green" : "red"}>
                    {DIRECTION_LABELS[r.direction]}
                  </Badge>
                ),
              },
              { key: "amount", label: "المبلغ", render: (r) => money(r.amount) },
              {
                key: "matched",
                label: "حالة المطابقة",
                render: (r) =>
                  r.matched_journal_item_id ? (
                    <Badge tone="green">مطابق</Badge>
                  ) : (
                    <Badge tone="amber">غير مطابق</Badge>
                  ),
              },
              {
                key: "matched_journal_item",
                label: "الحركة المطابقة",
                render: (r) =>
                  r.matched_journal_item
                    ? `${r.matched_journal_item.description} (${r.matched_journal_item.entry_date})`
                    : "—",
              },
              {
                key: "actions",
                label: "",
                render: (r) =>
                  r.matched_journal_item_id ? (
                    <Button variant="secondary" onClick={() => unmatchLine(r)}>
                      إلغاء المطابقة
                    </Button>
                  ) : (
                    <Button variant="secondary" onClick={() => setMatchingLine(r)}>
                      مطابقة
                    </Button>
                  ),
              },
            ]}
            rows={lines.data}
            empty="لا توجد بنود كشف حساب بعد."
          />
        )}
      </Card>

      <Modal
        open={!!matchingLine}
        title={matchingLine ? `مطابقة: ${matchingLine.description} (${money(matchingLine.amount)})` : ""}
        onClose={() => setMatchingLine(null)}
        wide
      >
        {matchingLine &&
          (unmatched.loading ? (
            <Loading />
          ) : (
            <Table
              columns={[
                { key: "entry_date", label: "التاريخ" },
                { key: "description", label: "الوصف" },
                { key: "debit", label: "مدين", render: (r) => (Number(r.debit) ? money(r.debit) : "") },
                { key: "credit", label: "دائن", render: (r) => (Number(r.credit) ? money(r.credit) : "") },
                {
                  key: "action",
                  label: "",
                  render: (r) => <Button onClick={() => confirmMatch(r.id)}>اختيار</Button>,
                },
              ]}
              rows={unmatched.data}
              empty="لا توجد حركات بنكية غير مطابقة."
            />
          ))}
      </Modal>
    </div>
  );
}

const EMPTY_ITEM = { account_code: "", debit: "", credit: "" };

/**
 * A hand-written journal entry, for corrections and opening balances that no
 * module produces. Refuses to submit unless debits equal credits.
 */
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
          <span className="text-sm font-bold text-slate-600 dark:text-slate-400">أطراف القيد</span>
          <Button type="button" variant="secondary" onClick={() => setItems([...items, { ...EMPTY_ITEM }])}>
            + طرف
          </Button>
        </div>
        {items.map((item, index) => (
          <div key={index} className={`line-row ${index === 0 ? "line-row-first" : ""} mb-2 grid grid-cols-12 items-end gap-2 max-sm:grid-cols-1 max-sm:[&>*]:col-span-1`}>
            <div className="col-span-6">
              <Select
                label="الحساب"
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
                label="مدين"
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
                label="دائن"
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
      <div className="flex items-center justify-between rounded-lg bg-slate-50 dark:bg-slate-800/60 px-4 py-3 text-sm font-bold">
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

export default function AccountingPage() {
  const [tab, setTab] = useState("journal");
  const accounts = useFetch(() => api.get("/accounting/accounts"));
  // The journal is fetched one page at a time. It is the fastest-growing table in
  // the system — every invoice, payment, return and expense posts an entry — and it
  // was 2 MB and 3,408 rows after a single year, to fill a screen showing fifteen.
  const [journalPage, setJournalPage] = useState(1);
  const [journalQuery, setJournalQuery] = useState("");
  const journalSearch = useDebouncedValue(journalQuery);
  const entries = useFetch(
    () =>
      api.get("/accounting/journal-entries", {
        params: {
          limit: JOURNAL_PAGE_SIZE,
          offset: (journalPage - 1) * JOURNAL_PAGE_SIZE,
          ...(journalSearch.trim() ? { search: journalSearch.trim() } : {}),
        },
      }),
    [journalPage, journalSearch]
  );
  // A new search must start from page one, or a query matching three entries while
  // sitting on page 40 asks for rows 585-600 of three and the screen reads as
  // "nothing found".
  //
  // Done here, synchronously with the keystroke, rather than in an effect watching
  // the debounced value: an effect runs *after* useFetch's own effect in the same
  // commit, so the first request still went out carrying the old page. Batching both
  // setStates means the page is already 1 by the time the debounced search fires.
  const searchJournal = (value) => {
    setJournalQuery(value);
    setJournalPage(1);
  };
  const trialBalance = useFetch(() => api.get("/accounting/reports/trial-balance"));
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const taxSummary = useFetch(
    () =>
      api.get("/accounting/reports/tax-summary", {
        params: { date_from: dateFrom || undefined, date_to: dateTo || undefined },
      }),
    [dateFrom, dateTo]
  );
  const [incomeDateFrom, setIncomeDateFrom] = useState("");
  const [incomeDateTo, setIncomeDateTo] = useState("");
  const incomeStatement = useFetch(
    () =>
      api.get("/accounting/reports/income-statement", {
        params: {
          date_from: incomeDateFrom || undefined,
          date_to: incomeDateTo || undefined,
        },
      }),
    [incomeDateFrom, incomeDateTo]
  );
  const [asOf, setAsOf] = useState("");
  const balanceSheet = useFetch(
    () =>
      api.get("/accounting/reports/balance-sheet", {
        params: { as_of: asOf || undefined },
      }),
    [asOf]
  );

  const TABS = [
    { id: "journal", label: "قيود اليومية" },
    { id: "manual", label: "+ قيد يدوي" },
    { id: "trial", label: "ميزان المراجعة" },
    { id: "tax", label: "تقرير الضرائب" },
    { id: "income", label: "قائمة الدخل" },
    { id: "balance", label: "الميزانية العمومية" },
    { id: "bank", label: "المطابقة البنكية" },
    { id: "chart", label: "دليل الحسابات" },
  ];

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-extrabold">الحسابات</h1>
      <div className="flex flex-wrap gap-2">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`rounded-lg px-4 py-2 text-sm font-bold ${
              tab === t.id ? "bg-emerald-700 text-white" : "bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-50"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "journal" && (
        <Card title="قيود اليومية — تتولد تلقائياً من الفواتير والسندات">
          <Alert>{entries.error}</Alert>
          {/* Only blank the table on the first load. Replacing it on every page
              change would make the pager jump out from under the pointer. */}
          {entries.loading && !entries.data ? (
            <Loading />
          ) : (
            // One row per entry, its double-entry lines behind the detail toggle.
            // Previously every entry was a stacked card with its own inner table, so
            // the list itself could not paginate and a year of trading arrived on a
            // single page — and there was no way to search it either.
            <Table
              columns={[
                { key: "id", label: "القيد", render: (r) => `#${r.id}` },
                { key: "entry_date", label: "التاريخ" },
                { key: "description", label: "البيان" },
                {
                  key: "reference_type",
                  label: "المستند",
                  render: (r) => (
                    <Badge tone="blue">{referenceLabel(r.reference_type)}</Badge>
                  ),
                  search: (r) => referenceLabel(r.reference_type),
                },
                {
                  key: "total",
                  label: "المبلغ",
                  render: (r) => money(entryTotal(r)),
                  sortValue: (r) => Number(entryTotal(r)),
                },
              ]}
              rows={entries.data?.items || []}
              serverPaged={{
                total: entries.data?.total || 0,
                page: journalPage,
                onPageChange: setJournalPage,
                onSearchChange: searchJournal,
              }}
              empty="لا توجد قيود بعد."
              searchPlaceholder="بحث بالبيان أو التاريخ..."
              renderDetail={(entry) => (
                <Table
                  columns={[
                    {
                      key: "account",
                      label: "الحساب",
                      render: (r) => `${r.account.code} — ${r.account.name}`,
                    },
                    { key: "debit", label: "مدين", render: (r) => (Number(r.debit) ? money(r.debit) : "") },
                    { key: "credit", label: "دائن", render: (r) => (Number(r.credit) ? money(r.credit) : "") },
                  ]}
                  rows={entry.items}
                  searchable={false}
                />
              )}
            />
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
              <Table
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
              />
              {trialBalance.data?.rows?.length > 0 && (
                <div className="mt-3 flex justify-end gap-8 border-t-2 border-slate-300 dark:border-slate-600 pt-3 font-extrabold">
                  <span>مجموع المدين: {money(trialBalance.data.total_debit)}</span>
                  <span>مجموع الدائن: {money(trialBalance.data.total_credit)}</span>
                </div>
              )}
            </>
          )}
        </Card>
      )}

      {tab === "tax" && (
        <Card title="تقرير الضرائب — الضريبة المحصلة على المبيعات مقابل الضريبة المدفوعة في المشتريات">
          <div className="mb-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
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
          </div>
          <Alert>{taxSummary.error}</Alert>
          {taxSummary.loading ? (
            <Loading />
          ) : (
            <>
              <Table
                columns={[
                  { key: "name", label: "نوع الضريبة" },
                  { key: "rate", label: "النسبة", render: (r) => `${r.rate}%` },
                  { key: "collected", label: "المحصّلة (مبيعات)", render: (r) => money(r.collected) },
                  { key: "paid", label: "المدفوعة (مشتريات)", render: (r) => money(r.paid) },
                  {
                    key: "net",
                    label: "الصافي المستحق",
                    render: (r) => (
                      <span className={Number(r.net) >= 0 ? "text-emerald-700 dark:text-emerald-400" : "text-red-700"}>
                        {money(r.net)}
                      </span>
                    ),
                  },
                ]}
                rows={taxSummary.data?.rows}
                keyField={(r) => `${r.name}-${r.rate}`}
                empty="لا توجد حركات ضريبية في هذه الفترة."
              />
              {taxSummary.data?.rows?.length > 0 && (
                <div className="mt-3 flex flex-wrap justify-end gap-8 border-t-2 border-slate-300 dark:border-slate-600 pt-3 font-extrabold">
                  <span>إجمالي المحصّلة: {money(taxSummary.data.total_collected)}</span>
                  <span>إجمالي المدفوعة: {money(taxSummary.data.total_paid)}</span>
                  <span>الصافي المستحق: {money(taxSummary.data.total_net)}</span>
                </div>
              )}
            </>
          )}
        </Card>
      )}

      {tab === "income" && (
        <Card
          title="قائمة الدخل — الإيرادات ناقص تكلفة البضاعة المباعة ناقص المصاريف"
          actions={
            incomeStatement.data && (
              <Badge tone={Number(incomeStatement.data.net_profit) >= 0 ? "green" : "red"}>
                صافي الربح: {money(incomeStatement.data.net_profit)}
              </Badge>
            )
          }
        >
          <div className="mb-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Input
              label="من تاريخ"
              type="date"
              value={incomeDateFrom}
              onChange={(e) => setIncomeDateFrom(e.target.value)}
            />
            <Input
              label="إلى تاريخ"
              type="date"
              value={incomeDateTo}
              onChange={(e) => setIncomeDateTo(e.target.value)}
            />
          </div>
          <Alert>{incomeStatement.error}</Alert>
          {incomeStatement.loading ? (
            <Loading />
          ) : (
            <div className="space-y-6">
              <div>
                <div className="mb-2 text-sm font-bold text-slate-600 dark:text-slate-400">الإيرادات</div>
                <Table
                  columns={[
                    { key: "account_code", label: "الرقم" },
                    { key: "account_name", label: "الحساب" },
                    { key: "amount", label: "المبلغ", render: (r) => money(r.amount) },
                  ]}
                  rows={incomeStatement.data?.revenue_rows}
                  keyField="account_code"
                  empty="لا توجد إيرادات في هذه الفترة."
                />
                <div className="mt-2 flex justify-end font-extrabold">
                  <span>إجمالي الإيرادات: {money(incomeStatement.data?.total_revenue)}</span>
                </div>
              </div>

              <div>
                <div className="mb-2 text-sm font-bold text-slate-600 dark:text-slate-400">تكلفة البضاعة المباعة</div>
                <Table
                  columns={[
                    { key: "account_code", label: "الرقم" },
                    { key: "account_name", label: "الحساب" },
                    { key: "amount", label: "المبلغ", render: (r) => money(r.amount) },
                  ]}
                  rows={incomeStatement.data?.cogs_rows}
                  keyField="account_code"
                  empty="لا توجد تكلفة بضاعة مباعة في هذه الفترة."
                />
                <div className="mt-2 flex justify-end font-extrabold">
                  <span>إجمالي التكلفة: {money(incomeStatement.data?.total_cogs)}</span>
                </div>
              </div>

              <div className="flex justify-end border-t-2 border-slate-300 dark:border-slate-600 pt-3 text-emerald-700 dark:text-emerald-400">
                <span className="font-extrabold">
                  مجمل الربح: {money(incomeStatement.data?.gross_profit)}
                </span>
              </div>

              <div>
                <div className="mb-2 text-sm font-bold text-slate-600 dark:text-slate-400">المصاريف التشغيلية</div>
                <Table
                  columns={[
                    { key: "account_code", label: "الرقم" },
                    { key: "account_name", label: "الحساب" },
                    { key: "amount", label: "المبلغ", render: (r) => money(r.amount) },
                  ]}
                  rows={incomeStatement.data?.expense_rows}
                  keyField="account_code"
                  empty="لا توجد مصاريف تشغيلية في هذه الفترة."
                />
                <div className="mt-2 flex justify-end font-extrabold">
                  <span>إجمالي المصاريف: {money(incomeStatement.data?.total_expenses)}</span>
                </div>
              </div>

              <div
                className={`flex justify-end border-t-2 border-slate-300 dark:border-slate-600 pt-3 text-lg font-extrabold ${
                  Number(incomeStatement.data?.net_profit) >= 0 ? "text-emerald-700 dark:text-emerald-400" : "text-red-700"
                }`}
              >
                <span>صافي الربح: {money(incomeStatement.data?.net_profit)}</span>
              </div>
            </div>
          )}
        </Card>
      )}

      {tab === "balance" && (
        <Card
          title="الميزانية العمومية — الأصول = الالتزامات + حقوق الملكية"
          actions={
            balanceSheet.data &&
            (balanceSheet.data.is_balanced ? (
              <Badge tone="green">متوازنة ✓</Badge>
            ) : (
              <Badge tone="red">غير متوازنة!</Badge>
            ))
          }
        >
          <div className="mb-4 max-w-xs">
            <Input label="حتى تاريخ" type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
          </div>
          <Alert>{balanceSheet.error}</Alert>
          {balanceSheet.loading ? (
            <Loading />
          ) : (
            <div className="space-y-6">
              <div>
                <div className="mb-2 text-sm font-bold text-slate-600 dark:text-slate-400">الأصول</div>
                <Table
                  columns={[
                    { key: "account_code", label: "الرقم" },
                    { key: "account_name", label: "الحساب" },
                    { key: "amount", label: "المبلغ", render: (r) => money(r.amount) },
                  ]}
                  rows={balanceSheet.data?.asset_rows}
                  keyField="account_code"
                  empty="لا توجد أصول بعد."
                />
                <div className="mt-2 flex justify-end font-extrabold">
                  <span>إجمالي الأصول: {money(balanceSheet.data?.total_assets)}</span>
                </div>
              </div>

              <div>
                <div className="mb-2 text-sm font-bold text-slate-600 dark:text-slate-400">الالتزامات</div>
                <Table
                  columns={[
                    { key: "account_code", label: "الرقم" },
                    { key: "account_name", label: "الحساب" },
                    { key: "amount", label: "المبلغ", render: (r) => money(r.amount) },
                  ]}
                  rows={balanceSheet.data?.liability_rows}
                  keyField="account_code"
                  empty="لا توجد التزامات بعد."
                />
                <div className="mt-2 flex justify-end font-extrabold">
                  <span>إجمالي الالتزامات: {money(balanceSheet.data?.total_liabilities)}</span>
                </div>
              </div>

              <div>
                <div className="mb-2 text-sm font-bold text-slate-600 dark:text-slate-400">حقوق الملكية</div>
                <Table
                  columns={[
                    { key: "account_code", label: "الرقم" },
                    { key: "account_name", label: "الحساب" },
                    { key: "amount", label: "المبلغ", render: (r) => money(r.amount) },
                  ]}
                  rows={balanceSheet.data?.equity_rows}
                  keyField="account_code"
                  empty="لا توجد حقوق ملكية مسجلة بعد."
                />
                <div className="mt-1 flex justify-end text-sm text-slate-600 dark:text-slate-400">
                  <span>الأرباح المرحلة (غير الموزعة): {money(balanceSheet.data?.retained_earnings)}</span>
                </div>
                <div className="mt-2 flex justify-end font-extrabold">
                  <span>إجمالي حقوق الملكية: {money(balanceSheet.data?.total_equity)}</span>
                </div>
              </div>

              <div className="flex justify-end gap-8 border-t-2 border-slate-300 dark:border-slate-600 pt-3 text-lg font-extrabold">
                <span>إجمالي الأصول: {money(balanceSheet.data?.total_assets)}</span>
                <span>إجمالي الالتزامات وحقوق الملكية: {money(balanceSheet.data?.total_liabilities_and_equity)}</span>
              </div>
            </div>
          )}
        </Card>
      )}

      {tab === "bank" && <BankReconciliationTab />}

      {tab === "chart" && (
        <Card title="دليل الحسابات">
          <Alert>{accounts.error}</Alert>
          {accounts.loading ? (
            <Loading />
          ) : (
            <Table
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
            />
          )}
        </Card>
      )}
    </div>
  );
}
