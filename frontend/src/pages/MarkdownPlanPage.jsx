// The clearance plan: every batch running out of shelf life, and the one thing
// worth doing about each.
//
// The near-expiry worklist next door answers "what is at risk". This answers "so
// what do I do", and the difference is the discount depth — computed from how fast
// the batch actually sells and how much a price cut moves it, rather than typed as
// a round 20% because 20% is a familiar number.
//
// Two decisions shape this screen. First, the buckets are separate tabs, not a
// colour on one list: "leave it alone" and "write it off" are different jobs done by
// different people on different days, and mixing them produces a list nobody works.
// Second, the reasoning is printed on every row in plain Arabic. A manager who
// cannot see why a batch is getting 23% will not trust the number, and a discount
// nobody trusts is a discount that gets overridden by hand — which is the situation
// this feature exists to end.
import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Loading,
  Select,
  Stat,
  Table,
  money,
  qty,
} from "../components/Ui";
import { useAuth } from "../context/AuthContext";
import useFetch from "../hooks/useFetch";
import api, { apiMessage } from "../services/api";

const HORIZONS = [
  { value: 30, label: "خلال ٣٠ يوماً" },
  { value: 60, label: "خلال ٦٠ يوماً" },
  { value: 90, label: "خلال ٩٠ يوماً" },
];

// The ceiling on any single markdown lives in company settings, and the server
// clamps to it whatever this screen asks for. So the options are built from it: the
// policy ceiling, plus gentler steps for a manager who wants to try a lighter touch
// today. Offering a deeper one would be an option that silently does nothing.
const capOptions = (ceiling) => {
  const steps = [10, 15, 20, 25, 30, 40, 50]
    .filter((step) => step < ceiling)
    .map((step) => ({ value: step, label: `حتى ${step}%` }));
  return [
    { value: ceiling, label: `سقف الشركة (${ceiling}%)` },
    ...steps.reverse(),
  ];
};

const BUCKETS = [
  {
    id: "markdown",
    label: "خصم مقترح",
    tone: "amber",
    title: "يُباع، لكن ليس بالسرعة الكافية",
    blurb:
      "الفائض لن يُصرَّف قبل تاريخ الانتهاء بالسعر الحالي. الخصم المقترح محسوب ليغطي "
      + "الفارق بالضبط — لا أكثر.",
    empty: "لا يوجد صنف يحتاج خصماً في هذه المهلة.",
  },
  {
    id: "push",
    label: "يستحق اتصالاً",
    tone: "blue",
    title: "لا توجد مبيعات منتظمة، لكن هناك من اشتراه من قبل",
    blurb:
      "المشكلة هنا في الوصول لا في السعر؛ الخصم يمنح تنازلاً دون أن يجلب مشترياً. "
      + "اتصل بمن سبق أن اشترى.",
    empty: "لا يوجد صنف من هذا النوع.",
  },
  {
    id: "write_off",
    label: "خسارة مؤكدة",
    tone: "red",
    title: "لم يُبَع نهائياً ولا يوجد مشترٍ سابق",
    blurb:
      "لا يوجد خصم يصل بطلب معدوم إلى مشترٍ. الاعتراف بالخسارة الآن يوقف إعادة طلب "
      + "الصنف ويحرّر مساحة المستودع.",
    empty: "لا يوجد مخزون ميت في هذه المهلة.",
  },
  {
    id: "leave",
    label: "اتركه",
    tone: "green",
    title: "سينفد قبل انتهاء صلاحيته",
    blurb:
      "معروض هنا حتى لا يُخصَّم بالخطأ: هذه البضاعة ستُباع بسعرها الكامل، وأي خصم "
      + "عليها تنازل عن ربح لم يكن مهدداً.",
    empty: "لا يوجد صنف في هذه الحالة.",
  },
];

const urgency = (days) => (days <= 14 ? "red" : days <= 30 ? "amber" : "slate");

function Reason({ row }) {
  return (
    <div className="space-y-3">
      <p className="text-sm leading-relaxed text-slate-700 dark:text-slate-200">
        {row.reason}
      </p>
      <div className="grid gap-2 text-xs text-slate-500 sm:grid-cols-2 dark:text-slate-400">
        <span>
          التشغيلة {row.batch_number} · {row.warehouse_name}
        </span>
        <span>
          معدل البيع {qty(row.daily_rate)}/يوم · الفائض المتوقع {qty(row.surplus)}
        </span>
      </div>

      {row.buyers.length ? (
        <div className="space-y-1">
          <p className="text-sm font-bold text-slate-700 dark:text-slate-200">
            عملاء سبق أن اشتروا هذا الصنف:
          </p>
          <ul className="space-y-1">
            {row.buyers.map((buyer) => (
              <li
                key={buyer.customer_id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-slate-50 px-3 py-2 text-sm dark:bg-slate-800/60"
              >
                <span className="font-medium text-slate-700 dark:text-slate-200">
                  {buyer.name}
                  {buyer.phone ? (
                    <span className="text-xs text-slate-500 dark:text-slate-400">
                      {" · "}
                      {buyer.phone}
                    </span>
                  ) : null}
                </span>
                <span className="text-xs text-slate-500 dark:text-slate-400">
                  اشترى {qty(buyer.units)} · آخر مرة {buyer.last_bought}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export default function MarkdownPlanPage() {
  const { can } = useAuth();
  const canApply = can("products.offers");
  const [horizon, setHorizon] = useState(60);
  // Null until the company policy loads, so the first plan request carries no cap
  // at all and the server answers with its own — rather than this screen inventing
  // a number and then being corrected.
  const [cap, setCap] = useState(null);
  const [bucket, setBucket] = useState("markdown");
  const [picked, setPicked] = useState(() => new Set());
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);
  const [notes, setNotes] = useState([]);
  const [actionError, setActionError] = useState(null);

  const company = useFetch(() => api.get("/settings/company"));
  const ceiling = Number(company.data?.markdown_max_discount_percent ?? 0);

  const plan = useFetch(
    () =>
      api.get("/inventory/markdown-plan", {
        params: {
          horizon_days: horizon,
          ...(cap === null ? {} : { max_discount: cap }),
        },
      }),
    [horizon, cap]
  );

  const data = plan.data;
  const rows = useMemo(
    () => (data?.items ?? []).filter((item) => item.action === bucket),
    [data, bucket]
  );

  // Changing the horizon or the cap redraws the plan, and a batch selected under the
  // old one may not even be in the new list. Carrying the ticks over would mean
  // applying a discount the manager never saw.
  useEffect(() => {
    setPicked(new Set());
  }, [horizon, cap]);

  const counts = useMemo(() => {
    const tally = {};
    for (const item of data?.items ?? []) {
      tally[item.action] = (tally[item.action] ?? 0) + 1;
    }
    return tally;
  }, [data]);

  const toggle = (id) =>
    setPicked((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const apply = async () => {
    setBusy(true);
    setActionError(null);
    setNotice(null);
    setNotes([]);
    try {
      const response = await api.post(
        "/inventory/markdown-plan/apply",
        { batch_ids: [...picked] },
        {
          params: {
            horizon_days: horizon,
            ...(cap === null ? {} : { max_discount: cap }),
          },
        }
      );
      const result = response.data.data;
      setNotice(response.data.message);
      setNotes(result.notes ?? []);
      setPicked(new Set());
      plan.reload();
    } catch (err) {
      setActionError(apiMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const columns = [
    canApply && bucket === "markdown"
      ? {
          key: "pick",
          label: "",
          // A product already under a discount cannot take a second one, and the
          // depth beside it was computed from a sales rate the running offer is
          // already changing. Ticking it would only earn a rejection note.
          render: (row) =>
            row.active_offer_percent === null ? (
              <input
                type="checkbox"
                className="h-4 w-4 accent-emerald-600"
                checked={picked.has(row.batch_id)}
                onChange={() => toggle(row.batch_id)}
                aria-label={`اختيار ${row.name}`}
              />
            ) : null,
        }
      : null,
    {
      key: "name",
      label: "الصنف",
      render: (row) => (
        <span className="flex flex-col">
          <span>{row.name}</span>
          <span className="text-xs text-slate-500 dark:text-slate-400">{row.sku}</span>
        </span>
      ),
      search: (row) => `${row.name} ${row.sku} ${row.batch_number}`,
    },
    {
      key: "days_left",
      label: "المتبقي",
      render: (row) => <Badge tone={urgency(row.days_left)}>{row.days_left} يوم</Badge>,
      sortValue: (row) => row.days_left,
    },
    { key: "expiry_date", label: "ينتهي في" },
    { key: "quantity", label: "الكمية", render: (row) => qty(row.quantity) },
    {
      key: "surplus_value",
      label: "قيمة الفائض",
      render: (row) => money(row.surplus_value),
      sortValue: (row) => Number(row.surplus_value),
    },
    bucket === "markdown"
      ? {
          key: "discount_percent",
          label: "الخصم المقترح",
          render: (row) =>
            row.active_offer_percent !== null ? (
              <Badge tone="green">
                خصم ساري {qty(row.active_offer_percent)}%
              </Badge>
            ) : (
              <span className="flex flex-wrap items-center gap-2">
                <Badge tone="amber">{qty(row.discount_percent)}%</Badge>
                <span className="text-xs text-slate-500 dark:text-slate-400">
                  {money(row.price_before)} ← {money(row.price_now)}
                </span>
              </span>
            ),
          sortValue: (row) => Number(row.discount_percent),
        }
      : {
          key: "recovery_value",
          label: "قابل للاسترداد",
          render: (row) => money(row.recovery_value),
          sortValue: (row) => Number(row.recovery_value),
        },
  ].filter(Boolean);

  if (plan.loading) return <Loading />;
  const active = BUCKETS.find((b) => b.id === bucket);
  const measured = data?.elasticity_source === "measured";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold text-slate-800 dark:text-slate-100">
          خطة تصريف المخزون
        </h1>
        <div className="flex flex-wrap gap-2">
          <Select value={horizon} onChange={(e) => setHorizon(Number(e.target.value))}>
            {HORIZONS.map((h) => (
              <option key={h.value} value={h.value}>
                {h.label}
              </option>
            ))}
          </Select>
          {ceiling > 0 ? (
            <Select
              value={cap ?? ceiling}
              onChange={(e) => setCap(Number(e.target.value))}
            >
              {capOptions(ceiling).map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </Select>
          ) : null}
        </div>
      </div>

      <Alert>{plan.error ?? actionError}</Alert>
      <Alert tone="success">{notice}</Alert>
      {notes.length ? (
        // Not every tick becomes an offer — a batch may have sold out, or already
        // carry a discount. Saying which, and why, beats a silent partial success.
        <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/50 dark:text-amber-200">
          <ul className="list-inside list-disc space-y-1">
            {notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-3">
        <Stat
          label="مخزون مهدد"
          value={money(data?.stock_at_risk ?? 0)}
          hint={`${data?.items?.length ?? 0} تشغيلة تنتهي خلال ${horizon} يوماً`}
          tone="amber"
        />
        <Stat
          label="قابل للاسترداد"
          value={money(data?.recoverable_value ?? 0)}
          hint="لو نُفِّذت الخطة كاملة"
          tone="emerald"
        />
        <Stat
          label="خسارة مؤكدة"
          value={money(data?.write_off_value ?? 0)}
          hint="لا يوجد مشترٍ بأي سعر"
          tone="rose"
        />
      </div>

      {/* Where the discount depth comes from. An assumed elasticity is a defensible
          starting point and a measured one is better, but the buyer has to be able
          to tell which of the two set a 40% cut. */}
      <p className="text-xs text-slate-500 dark:text-slate-400">
        عمق الخصم محسوب على مرونة سعرية قدرها {qty(data?.elasticity ?? 0)}{" "}
        {measured
          ? `— مقاسة من ${data?.elasticity_observations} عرضاً سابقاً.`
          : "— مفترضة، إذ لا توجد عروض سابقة كافية لقياسها. ستُستبدل بالرقم الحقيقي فور توفره."}
      </p>

      <div className="flex flex-wrap gap-2">
        {BUCKETS.map((b) => (
          <Button
            key={b.id}
            variant={bucket === b.id ? "primary" : "secondary"}
            onClick={() => setBucket(b.id)}
          >
            {b.label} ({counts[b.id] ?? 0})
          </Button>
        ))}
      </div>

      <Card
        title={active.title}
        actions={
          canApply && bucket === "markdown" ? (
            <Button onClick={apply} disabled={busy || !picked.size}>
              {busy ? "جارٍ التفعيل…" : `تفعيل الخصم على ${picked.size} تشغيلة`}
            </Button>
          ) : null
        }
      >
        <p className="mb-3 text-sm text-slate-500 dark:text-slate-400">{active.blurb}</p>
        <Table
          columns={columns}
          rows={rows}
          keyField="batch_id"
          empty={active.empty}
          renderDetail={(row) => <Reason row={row} />}
        />
      </Card>
    </div>
  );
}
