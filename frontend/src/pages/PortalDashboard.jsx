// Portal home for the customer: the essential numbers at a glance — balance,
// and the latest invoices and orders — plus a straight path to ordering.
import { Link } from "react-router-dom";
import { Alert, Badge, Button, Card, Loading, Stat, money } from "../components/Ui";
import { useAuth } from "../context/AuthContext";
import useFetch from "../hooks/useFetch";
import api from "../services/api";

const ORDER_STATUS_LABELS = {
  pending: { label: "قيد الانتظار", tone: "amber" },
  confirmed: { label: "تم التأكيد", tone: "blue" },
  invoiced: { label: "تم الفوترة", tone: "green" },
  cancelled: { label: "ملغي", tone: "red" },
};

export default function PortalDashboard() {
  const { user } = useAuth();
  const statement = useFetch(() => api.get("/portal/statement"));
  const invoices = useFetch(() => api.get("/portal/invoices"));
  const orders = useFetch(() => api.get("/portal/orders"));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold">مرحباً {user.full_name.replace(/^عميل:\s*/, "")}</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          تصفح الكتالوج، اطلب بضاعتك، وتابع فواتيرك من هنا.
        </p>
      </div>

      <Alert>{statement.error}</Alert>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat
          label="الرصيد المستحق"
          value={money(statement.data?.balance)}
          hint={statement.data ? "أحدث كشف حساب" : "جارٍ التحميل..."}
          tone={Number(statement.data?.balance) > 0 ? "rose" : "emerald"}
        />
        <Stat
          label="عدد الفواتير"
          value={invoices.data?.length ?? "—"}
          hint="آخر الحركات على حسابك"
        />
        <Stat
          label="الطلبات الجارية"
          value={
            orders.data?.filter((o) => o.status === "pending" || o.status === "confirmed").length ?? "—"
          }
          hint="قيد الانتظار أو التأكيد"
          tone="sky"
        />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-extrabold">آخر الفواتير</h2>
        <Link to="/portal/statement">
          <Button variant="secondary">كشف الحساب الكامل</Button>
        </Link>
      </div>

      {invoices.loading ? (
        <Loading />
      ) : (
        <Card>
          {invoices.data?.length ? (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {invoices.data.slice(0, 5).map((inv) => (
                <li key={inv.id} className="flex items-center justify-between gap-3 py-3">
                  <div className="min-w-0">
                    <div className="font-bold">فاتورة #{inv.id}</div>
                    <div className="text-xs text-slate-500 dark:text-slate-400">
                      {inv.invoice_date}
                    </div>
                  </div>
                  <div className="font-extrabold">{money(inv.total)}</div>
                </li>
              ))}
            </ul>
          ) : (
            <div className="py-6 text-center text-sm text-slate-400">لا توجد فواتير بعد.</div>
          )}
        </Card>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-extrabold">أحدث طلباتك</h2>
        <Link to="/portal/orders">
          <Button variant="secondary">كل الطلبات</Button>
        </Link>
      </div>

      {orders.loading ? (
        <Loading />
      ) : (
        <Card>
          {orders.data?.length ? (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {orders.data.slice(0, 5).map((order) => {
                const meta = ORDER_STATUS_LABELS[order.status] ?? ORDER_STATUS_LABELS.pending;
                return (
                  <li key={order.id} className="flex items-center justify-between gap-3 py-3">
                    <div className="min-w-0">
                      <div className="font-bold">طلب #{order.id}</div>
                      <div className="text-xs text-slate-500 dark:text-slate-400">
                        {order.order_date} · {order.total_quantity} لقطعة
                      </div>
                    </div>
                    <Badge tone={meta.tone}>{meta.label}</Badge>
                  </li>
                );
              })}
            </ul>
          ) : (
            <div className="py-6 text-center text-sm text-slate-400">
              لا توجد طلبات بعد.{" "}
              <Link to="/portal/catalog" className="text-emerald-700 font-bold dark:text-emerald-400">
                ابدأ طلبك الأول الآن
              </Link>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}