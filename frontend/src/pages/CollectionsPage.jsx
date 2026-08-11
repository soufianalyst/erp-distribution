// Who to ring today about money, and what they said last time.
//
// The aging report next door is a list of facts. This is a list of calls, ordered by
// what putting each one off actually costs — the overdue amount weighted by how long
// it has sat. A big debt three weeks past due is a call that still works; a small one
// two years old is a write-off waiting to be admitted, and it belongs at the bottom
// however alarming its age looks.
//
// Three things are on every row for a reason. The phone number, because a collections
// screen that makes you go and look one up is a screen nobody uses. The reason line,
// written by the server, because "why am I ringing this shop" has to survive being
// read aloud. And the promise, because the single most useful fact in collections is
// whether the last thing this customer said turned out to be true.
import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  CancelButton,
  Card,
  Input,
  Loading,
  Modal,
  Select,
  Stat,
  Table,
  money,
  todayStr,
} from "../components/Ui";
import useFetch from "../hooks/useFetch";
import api, { apiMessage } from "../services/api";

const OUTCOMES = [
  { value: "promised", label: "وعد بالسداد" },
  { value: "paid", label: "سدّد الآن" },
  { value: "no_answer", label: "لم يرد" },
  { value: "refused", label: "رفض السداد" },
  { value: "disputed", label: "يعترض على الفاتورة" },
  { value: "note", label: "ملاحظة فقط" },
];

const OUTCOME_LABEL = Object.fromEntries(OUTCOMES.map((o) => [o.value, o.label]));

const PROMISE_TONE = { open: "blue", kept: "green", broken: "red" };
const PROMISE_LABEL = { open: "وعد قائم", kept: "أوفى بوعده", broken: "أخلف وعده" };

// How overdue the oldest invoice is, as a colour. Ninety days is where a debt stops
// being late and starts being doubtful.
const ageTone = (days) => (days > 90 ? "red" : days > 60 ? "amber" : "slate");

function LogDialog({ debtor, onClose, onDone }) {
  const [outcome, setOutcome] = useState("promised");
  const [amount, setAmount] = useState(debtor.overdue);
  const [dueOn, setDueOn] = useState(todayStr());
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const promising = outcome === "promised";

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post(`/sales/customers/${debtor.customer_id}/collections`, {
        outcome,
        // Sent only for a promise. The server drops them otherwise anyway, but
        // sending a date with "no answer" would be describing a promise nobody made.
        promised_amount: promising ? amount : null,
        promised_on: promising ? dueOn : null,
        note: note.trim() || null,
      });
      onDone(`تم تسجيل المتابعة مع ${debtor.name}.`);
    } catch (err) {
      setError(apiMessage(err));
      setBusy(false);
    }
  };

  return (
    <Modal open title={`متابعة تحصيل — ${debtor.name}`} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <div className="rounded-lg bg-slate-50 p-3 text-sm dark:bg-slate-800/60">
          <div className="flex justify-between">
            <span className="text-slate-500 dark:text-slate-400">المتأخر</span>
            <span className="font-bold text-rose-700 dark:text-rose-400">
              {money(debtor.overdue)}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-500 dark:text-slate-400">أقدم فاتورة</span>
            <span>{debtor.oldest_days} يوماً</span>
          </div>
          {debtor.phone ? (
            <div className="flex justify-between">
              <span className="text-slate-500 dark:text-slate-400">الهاتف</span>
              <span className="font-bold">{debtor.phone}</span>
            </div>
          ) : null}
        </div>

        <Select
          label="نتيجة المتابعة"
          value={outcome}
          onChange={(e) => setOutcome(e.target.value)}
        >
          {OUTCOMES.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </Select>

        {promising ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Input
              label="المبلغ الموعود"
              type="number"
              step="0.01"
              min="0.01"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              required
              autoFocus
            />
            <Input
              label="بحلول تاريخ"
              type="date"
              min={todayStr()}
              value={dueOn}
              onChange={(e) => setDueOn(e.target.value)}
              required
            />
          </div>
        ) : null}

        <Input
          label="ملاحظة"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={500}
        />

        {promising ? (
          <p className="text-xs text-slate-500 dark:text-slate-400">
            سيُقارَن هذا الوعد بالدفعات الفعلية؛ لا يُعلَّم «أُوفي به» يدوياً.
          </p>
        ) : null}

        <Alert>{error}</Alert>
        <div className="flex justify-end gap-2">
          <CancelButton onClose={onClose} />
          <Button type="submit" disabled={busy}>
            {busy ? "جارٍ الحفظ…" : "تسجيل المتابعة"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function History({ customerId }) {
  const history = useFetch(
    () => api.get(`/sales/customers/${customerId}/collections`),
    [customerId]
  );

  if (history.loading) return <Loading />;
  const rows = history.data ?? [];
  if (!rows.length) {
    return (
      <p className="text-sm text-slate-500 dark:text-slate-400">
        لا توجد متابعات سابقة مع هذا العميل.
      </p>
    );
  }
  return (
    <ul className="space-y-2">
      {rows.map((row) => (
        <li
          key={row.id}
          className="rounded-lg bg-slate-50 px-3 py-2 text-sm dark:bg-slate-800/60"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-bold text-slate-700 dark:text-slate-200">
              {OUTCOME_LABEL[row.outcome] ?? row.outcome}
            </span>
            <span className="text-xs text-slate-500 dark:text-slate-400">
              {String(row.created_at).slice(0, 10)}
            </span>
          </div>
          {row.promised_amount ? (
            <div className="text-xs text-slate-600 dark:text-slate-300">
              وعد بـ {money(row.promised_amount)} بحلول {row.promised_on}
            </div>
          ) : null}
          {row.note ? (
            <div className="text-xs text-slate-500 dark:text-slate-400">{row.note}</div>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

export default function CollectionsPage() {
  const [minDays, setMinDays] = useState(30);
  const [logging, setLogging] = useState(null);
  const [notice, setNotice] = useState(null);

  const worklist = useFetch(
    () => api.get("/sales/collections/worklist", { params: { min_days: minDays } }),
    [minDays]
  );

  const data = worklist.data;

  const columns = [
    {
      key: "name",
      label: "العميل",
      render: (row) => (
        <span className="flex flex-col">
          <span className="font-bold">{row.name}</span>
          <span className="text-xs text-slate-500 dark:text-slate-400">
            {row.phone || "لا يوجد هاتف"}
            {row.salesman_name ? ` · ${row.salesman_name}` : ""}
          </span>
        </span>
      ),
      search: (row) => `${row.name} ${row.phone ?? ""} ${row.salesman_name ?? ""}`,
    },
    {
      key: "overdue",
      label: "المتأخر",
      render: (row) => (
        <span className="font-bold text-rose-700 dark:text-rose-400">
          {money(row.overdue)}
        </span>
      ),
      sortValue: (row) => Number(row.overdue),
    },
    {
      key: "balance",
      label: "إجمالي الرصيد",
      render: (row) => money(row.balance),
      sortValue: (row) => Number(row.balance),
    },
    {
      key: "oldest_days",
      label: "أقدم فاتورة",
      render: (row) => <Badge tone={ageTone(row.oldest_days)}>{row.oldest_days} يوم</Badge>,
      sortValue: (row) => row.oldest_days,
    },
    {
      key: "promise",
      label: "الوعد",
      render: (row) =>
        row.promise ? (
          <span className="flex flex-col gap-1">
            <Badge tone={PROMISE_TONE[row.promise.state]}>
              {PROMISE_LABEL[row.promise.state]}
            </Badge>
            <span className="text-xs text-slate-500 dark:text-slate-400">
              {money(row.promise.amount)} · {row.promise.due_on}
            </span>
          </span>
        ) : (
          <span className="text-xs text-slate-400 dark:text-slate-500">—</span>
        ),
      sortValue: (row) => row.promise?.state ?? "",
    },
    {
      key: "last_contact",
      label: "آخر متابعة",
      render: (row) =>
        row.last_contact ? (
          <span className="text-xs">
            {String(row.last_contact).slice(0, 10)}
            <span className="block text-slate-500 dark:text-slate-400">
              {OUTCOME_LABEL[row.last_outcome] ?? row.last_outcome}
            </span>
          </span>
        ) : (
          // Not a blank cell: never contacted is the finding, not missing data.
          <Badge tone="amber">لم يُتصل به</Badge>
        ),
    },
    {
      key: "actions",
      label: "",
      render: (row) => <Button onClick={() => setLogging(row)}>تسجيل متابعة</Button>,
    },
  ];

  const detail = (row) => (
    <div className="space-y-3">
      <p className="text-sm leading-relaxed text-slate-700 dark:text-slate-200">
        {row.reason}
      </p>
      <div className="grid gap-2 text-xs text-slate-500 sm:grid-cols-4 dark:text-slate-400">
        <span>حتى ٣٠ يوماً: {money(row.buckets.current)}</span>
        <span>٣١–٦٠: {money(row.buckets.d31_60)}</span>
        <span>٦١–٩٠: {money(row.buckets.d61_90)}</span>
        <span className="font-bold text-rose-700 dark:text-rose-400">
          أكثر من ٩٠: {money(row.buckets.d90_plus)}
        </span>
      </div>
      <div className="text-xs text-slate-500 dark:text-slate-400">
        {row.invoice_count} فاتورة غير مسددة · الحد الائتماني {money(row.credit_limit)}
      </div>
      <History customerId={row.customer_id} />
    </div>
  );

  if (worklist.loading) return <Loading />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold text-slate-800 dark:text-slate-100">
          متابعة التحصيل
        </h1>
        <Select value={minDays} onChange={(e) => setMinDays(Number(e.target.value))}>
          <option value={30}>متأخر أكثر من ٣٠ يوماً</option>
          <option value={60}>متأخر أكثر من ٦٠ يوماً</option>
          <option value={90}>متأخر أكثر من ٩٠ يوماً</option>
        </Select>
      </div>

      <Alert>{worklist.error}</Alert>
      <Alert tone="success">{notice}</Alert>

      <div className="grid gap-3 sm:grid-cols-4">
        <Stat label="إجمالي الذمم" value={money(data?.total_outstanding ?? 0)} />
        <Stat
          label="المتأخر"
          value={money(data?.total_overdue ?? 0)}
          hint={`${data?.items?.length ?? 0} عميلاً`}
          tone="rose"
        />
        <Stat
          label="وعود مُخلَفة"
          value={data?.broken_promises ?? 0}
          hint="قالوا سيدفعون ولم يفعلوا"
          tone="amber"
        />
        <Stat
          label="لم يُتصل بهم إطلاقاً"
          value={data?.never_contacted ?? 0}
          hint="لا توجد أي متابعة مسجلة"
          tone="amber"
        />
      </div>

      <Card title="مرتبة بحسب كلفة التأجيل — المبلغ المتأخر مرجّحاً بعمره">
        <p className="mb-3 text-sm text-slate-500 dark:text-slate-400">
          ليس بالمبلغ وحده ولا بالعمر وحده: دينٌ كبير متأخر ثلاثة أسابيع مكالمة لا تزال
          مجدية، ودينٌ صغير عمره سنتان اعترافٌ بالخسارة مؤجَّل. افتح التفاصيل لترى
          الشرائح وسجل المتابعات.
        </p>
        <Table
          columns={columns}
          rows={data?.items ?? []}
          keyField="customer_id"
          empty="لا توجد ذمم متأخرة في هذه الفترة."
          renderDetail={detail}
        />
      </Card>

      {logging ? (
        <LogDialog
          debtor={logging}
          onClose={() => setLogging(null)}
          onDone={(message) => {
            setLogging(null);
            setNotice(message);
            worklist.reload();
          }}
        />
      ) : null}
    </div>
  );
}
