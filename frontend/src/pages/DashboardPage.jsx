import { useNavigate } from "react-router-dom";
import { Alert, Badge, Button, Card, Loading, Stat, Table, qty } from "../components/Ui";
import useFetch from "../hooks/useFetch";
import api from "../services/api";

// Severity drives the whole card: how loud it looks and how it sorts. The
// backend decides severity so the UI never has to re-derive urgency.
const SEVERITY = {
  critical: {
    label: "عاجل",
    tone: "red",
    card: "border-rose-300 bg-rose-50 dark:border-rose-900 dark:bg-rose-950/40",
    icon: "🚨",
  },
  warning: {
    label: "تحذير",
    tone: "amber",
    card: "border-amber-300 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/40",
    icon: "⚠️",
  },
  info: {
    label: "للمتابعة",
    tone: "blue",
    card: "border-sky-300 bg-sky-50 dark:border-sky-900 dark:bg-sky-950/40",
    icon: "ℹ️",
  },
};

function AlertCard({ group }) {
  const navigate = useNavigate();
  const style = SEVERITY[group.severity] ?? SEVERITY.info;
  // The group carries a preview, not the full list; say so when more remain.
  const hidden = group.count - group.items.length;

  return (
    <section className={`rounded-xl border p-4 shadow-sm ${style.card}`}>
      <header className="mb-2 flex flex-wrap items-start justify-between gap-2">
        <div className="flex items-start gap-2">
          <span aria-hidden="true">{style.icon}</span>
          <div>
            <h3 className="font-extrabold text-slate-800 dark:text-slate-100">
              {group.label}
            </h3>
            <p className="mt-0.5 text-xs font-bold text-slate-600 dark:text-slate-400">
              {group.hint}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Badge tone={style.tone}>{style.label}</Badge>
          <span className="text-2xl font-extrabold text-slate-800 dark:text-slate-100">
            {group.count}
          </span>
        </div>
      </header>

      <ul className="space-y-1 text-sm">
        {group.items.map((item, index) => (
          <li
            key={`${item.label}-${index}`}
            className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-200/70 pt-1 dark:border-slate-700/70"
          >
            <span className="font-bold text-slate-800 dark:text-slate-200">
              {item.label}
              <span className="ms-2 text-xs font-normal text-slate-600 dark:text-slate-400">
                {item.detail}
              </span>
            </span>
            {item.value && (
              <span className="text-xs font-extrabold text-slate-700 dark:text-slate-300">
                {item.value}
              </span>
            )}
          </li>
        ))}
      </ul>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        {hidden > 0 ? (
          <span className="text-xs font-bold text-slate-600 dark:text-slate-400">
            و{hidden} غيرها
          </span>
        ) : (
          <span />
        )}
        <Button variant="secondary" onClick={() => navigate(group.route)}>
          معالجة الآن ←
        </Button>
      </div>
    </section>
  );
}

export default function DashboardPage() {
  const alerts = useFetch(() => api.get("/alerts"));
  const levels = useFetch(() => api.get("/inventory/stock/levels"));
  const products = useFetch(() => api.get("/inventory/products"));

  if (alerts.loading || levels.loading || products.loading) return <Loading />;
  const error = alerts.error || levels.error || products.error;
  const data = alerts.data;
  const groups = data?.groups ?? [];

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-extrabold">لوحة التحكم</h1>
      <Alert>{error}</Alert>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="عدد الأصناف" value={products.data?.length ?? 0} />
        <Stat label="أرصدة مخزنية نشطة" value={levels.data?.length ?? 0} />
        <Stat
          label="تنبيهات عاجلة"
          value={data?.critical_count ?? 0}
          tone="rose"
          hint="تحتاج إجراءً اليوم"
        />
        <Stat
          label="تنبيهات تحذيرية"
          value={data?.warning_count ?? 0}
          tone="amber"
          hint="تحتاج متابعة قريبة"
        />
      </div>

      <Card title="ما يحتاج انتباهك الآن">
        {groups.length === 0 ? (
          <p className="py-8 text-center text-sm font-bold text-emerald-700 dark:text-emerald-400">
            لا توجد تنبيهات — كل شيء على ما يبدو سليم. 👌
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            {groups.map((group) => (
              <AlertCard key={group.key} group={group} />
            ))}
          </div>
        )}
      </Card>

      <Card title="أرصدة المخزون الحالية">
        <Table
          columns={[
            { key: "product_name", label: "الصنف" },
            { key: "warehouse_name", label: "المستودع" },
            {
              key: "total_quantity",
              label: "الرصيد",
              render: (r) => `${qty(r.total_quantity)} ${r.base_unit_name}`,
            },
          ]}
          rows={levels.data}
          keyField={(r) => `${r.product_id}-${r.warehouse_id}`}
          empty="المخزون فارغ حالياً."
        />
      </Card>
    </div>
  );
}
