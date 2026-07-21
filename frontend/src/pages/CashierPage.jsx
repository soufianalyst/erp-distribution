import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Loading,
  Modal,
  PaginatedTable,
  money,
} from "../components/Ui";
import useFetch from "../hooks/useFetch";
import api, { apiMessage } from "../services/api";

const TYPE_COLORS = {
  sales: "green",
  purchase: "blue",
  expense: "amber",
};

/** Shared columns for both receivables and payables tables. */
function buildColumns(tab, onAction) {
  const actionLabel = tab === "receivables" ? "تحصيل" : "صرف";
  const actionVariant = tab === "receivables" ? "primary" : "danger";
  return [
    { key: "type", label: "النوع", render: (r) => <Badge tone={TYPE_COLORS[r.type] || "slate"}>{r.type_label}</Badge>, searchable: (r) => r.type_label },
    { key: "id", label: "#", searchable: (r) => String(r.id) },
    { key: "date", label: "التاريخ" },
    { key: "party_name", label: "الطرف" },
    { key: "payment_method", label: "الدفع", render: (r) => r.payment_method === "cash" ? <Badge tone="green">نقدي</Badge> : <Badge tone="blue">بطاقة</Badge> },
    { key: "total", label: "الإجمالي", render: (r) => money(r.total) },
    { key: "paid_amount", label: "المدفوع", render: (r) => money(r.paid_amount) },
    { key: "remaining", label: "المتبقي", render: (r) => <b className="text-rose-600">{money(r.remaining)}</b> },
    { key: "actions", label: "", render: (r) => <Button variant={actionVariant} onClick={() => onAction(r)}>{actionLabel}</Button> },
  ];
}

export default function CashierPage() {
  const [tab, setTab] = useState("receivables");
  const [notice, setNotice] = useState(null);
  const [payTarget, setPayTarget] = useState(null);
  const [payAmount, setPayAmount] = useState("");
  const [paying, setPaying] = useState(false);

  const receivables = useFetch(() => api.get("/cashier/receivables"));
  const payables = useFetch(() => api.get("/cashier/payables"));
  const summary = useFetch(() => api.get("/cashier/daily-summary"));

  const openPayDialog = (item) => {
    setPayTarget(item);
    setPayAmount(String(item.remaining));
  };

  const submitPayment = async () => {
    if (!payTarget) return;
    const amt = parseFloat(payAmount);
    if (!amt || amt <= 0) {
      alert("أدخل مبلغ صحيح أكبر من صفر.");
      return;
    }
    setPaying(true);
    try {
      const { data } = await api.post("/cashier/pay", {
        reference_type: payTarget.type,
        reference_id: payTarget.id,
        amount: amt,
      });
      const result = data.data;
      const isReceivable = payTarget.type === "sales";
      const verb = isReceivable ? "تحصيل" : "صرف";
      if (parseFloat(result.paid_amount) >= parseFloat(result.total)) {
        setNotice(`تم ${verb} ${money(amt)} من ${payTarget.type_label} رقم ${payTarget.id} — مسدّد بالكامل.`);
      } else {
        setNotice(`تم ${verb} ${money(amt)} من ${payTarget.type_label} رقم ${payTarget.id}. المتبقي: ${money(result.remaining)}.`);
      }
      setPayTarget(null);
      receivables.reload();
      payables.reload();
      summary.reload();
    } catch (err) {
      alert(apiMessage(err));
    } finally {
      setPaying(false);
    }
  };

  if (receivables.loading || payables.loading || summary.loading) return <Loading />;

  const currentData = tab === "receivables" ? receivables.data : payables.data;
  const currentError = tab === "receivables" ? receivables.error : payables.error;
  const actionLabel = tab === "receivables" ? "تحصيل" : "صرف";

  // Summary totals
  const receivablesTotal = receivables.data?.reduce((s, r) => s + parseFloat(r.remaining), 0) || 0;
  const payablesTotal = payables.data?.reduce((s, r) => s + parseFloat(r.remaining), 0) || 0;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-extrabold">الصندوق</h1>
        <div className="flex gap-2">
          {receivables.data?.length > 0 && (
            <Badge tone="green">{receivables.data.length} ذمم مدينة</Badge>
          )}
          {payables.data?.length > 0 && (
            <Badge tone="red">{payables.data.length} ذمم دائنة</Badge>
          )}
        </div>
      </div>

      {notice && <Alert>{notice}</Alert>}

      {/* Tab buttons */}
      <div className="flex gap-2">
        <Button
          variant={tab === "receivables" ? "primary" : "secondary"}
          onClick={() => setTab("receivables")}
        >
          الذمم المدينة (المبيعات)
        </Button>
        <Button
          variant={tab === "payables" ? "primary" : "secondary"}
          onClick={() => setTab("payables")}
        >
          الذمم الدائنة (المشتريات والمصاريف)
        </Button>
        <Button
          variant={tab === "summary" ? "primary" : "secondary"}
          onClick={() => { setTab("summary"); summary.reload(); }}
        >
          تسوية نهاية اليوم
        </Button>
      </div>

      {/* Receivables / Payables tab */}
      {(tab === "receivables" || tab === "payables") && (
        <Card>
          {/* GL account info bar */}
          <div className={`mb-4 flex items-center justify-between rounded-lg p-3 text-sm font-bold ${
            tab === "receivables"
              ? "border border-emerald-200 bg-emerald-50 text-emerald-800"
              : "border border-rose-200 bg-rose-50 text-rose-800"
          }`}>
            <span>
              {tab === "receivables"
                ? "ذمم العملاء (1020) — المستحق لنا من العملاء"
                : "ذمم الموردين (2010) — المستحق منا للموردين والمصروفات"}
            </span>
            <span className="text-lg">
              {tab === "receivables" ? money(receivablesTotal) : money(payablesTotal)}
            </span>
          </div>

          <Alert>{currentError}</Alert>
          <PaginatedTable
            columns={buildColumns(tab, openPayDialog)}
            rows={currentData || []}
            empty={tab === "receivables" ? "لا توجد فواتير مبيعات معلقة." : "لا توجد فواتير مشتريات أو مصاريف معلقة."}
            searchable
            searchPlaceholder="بحث..."
            dateFromField="date"
            dateToField="date"
            amountField="total"
            amountLabel="الإجمالي"
          />
        </Card>
      )}

      {/* Daily Summary tab */}
      {tab === "summary" && (
        <div className="space-y-6">
          <Card>
            <h2 className="mb-4 text-lg font-bold">
              ملخص حركات الصندوق — {summary.data?.date}
            </h2>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4 mb-6">
              {/* Total collections */}
              <div className="rounded-lg border bg-emerald-50 p-4 text-center">
                <div className="text-sm text-emerald-700">إجمالي التحصيلات (مدخل)</div>
                <div className="text-2xl font-extrabold text-emerald-800">
                  {money(summary.data?.by_type?.sales?.total || 0)}
                </div>
                <div className="text-xs text-emerald-600">
                  {summary.data?.by_type?.sales?.count || 0} دفعة — ذمم مدينة
                </div>
              </div>
              {/* Total payments */}
              <div className="rounded-lg border bg-rose-50 p-4 text-center">
                <div className="text-sm text-rose-700">إجمالي الصرف (مدرج)</div>
                <div className="text-2xl font-extrabold text-rose-800">
                  {money(
                    (parseFloat(summary.data?.by_type?.purchase?.total || 0)) +
                    (parseFloat(summary.data?.by_type?.expense?.total || 0))
                  )}
                </div>
                <div className="text-xs text-rose-600">
                  {(summary.data?.by_type?.purchase?.count || 0) + (summary.data?.by_type?.expense?.count || 0)} دفعة — ذمم دائنة
                </div>
              </div>
              {/* Count */}
              <div className="rounded-lg border bg-blue-50 p-4 text-center">
                <div className="text-sm text-blue-700">عدد الدفعات</div>
                <div className="text-2xl font-extrabold text-blue-800">
                  {summary.data?.total_count || 0}
                </div>
              </div>
              {/* Cash flow */}
              <div className="rounded-lg border bg-violet-50 p-4 text-center">
                <div className="text-sm text-violet-700">صافي التدفق النقدي</div>
                <div className="text-2xl font-extrabold text-violet-800">
                  {money(
                    (parseFloat(summary.data?.by_type?.sales?.total || 0)) -
                    (parseFloat(summary.data?.by_type?.purchase?.total || 0)) -
                    (parseFloat(summary.data?.by_type?.expense?.total || 0))
                  )}
                </div>
              </div>
            </div>

            {/* By method breakdown */}
            <div className="mb-6">
              <h3 className="mb-2 text-sm font-bold text-slate-600">حسب طريقة الدفع</h3>
              <div className="flex gap-4">
                {Object.entries(summary.data?.by_method || {}).map(([method, total]) => (
                  <div key={method} className="rounded-lg border bg-slate-50 px-4 py-2">
                    <span className="text-sm text-slate-600">{method === "cash" ? "نقدي" : method === "credit_card" ? "بطاقة ائتمان" : method}: </span>
                    <span className="font-bold">{money(total)}</span>
                  </div>
                ))}
              </div>
            </div>

            <PaginatedTable
              columns={[
                { key: "id", label: "#", searchable: (r) => String(r.id) },
                {
                  key: "reference_type",
                  label: "النوع",
                  render: (r) => (
                    <Badge tone={r.reference_type === "sales" ? "green" : "red"}>
                      {r.reference_type === "sales" ? "تحصيل (مدينة)" : r.reference_type === "purchase" ? "صرف (دائنة)" : "صرف (دائنة)"}
                    </Badge>
                  ),
                  searchable: (r) => r.reference_type,
                },
                {
                  key: "reference_id",
                  label: "رقم المصدر",
                  searchable: (r) => String(r.reference_id),
                },
                {
                  key: "payment_method",
                  label: "الدفع",
                  render: (r) =>
                    r.payment_method === "cash" ? (
                      <Badge tone="green">نقدي</Badge>
                    ) : (
                      <Badge tone="blue">بطاقة</Badge>
                    ),
                },
                {
                  key: "amount",
                  label: "المبلغ",
                  render: (r) => (
                    <b className={r.reference_type === "sales" ? "text-emerald-700" : "text-rose-700"}>
                      {r.reference_type === "sales" ? "+" : "-"}{money(r.amount)}
                    </b>
                  ),
                },
              ]}
              rows={summary.data?.payments || []}
              empty="لا توجد حركات اليوم."
              searchable
              searchPlaceholder="بحث..."
            />
          </Card>
        </div>
      )}

      {/* Payment Dialog */}
      <Modal
        open={!!payTarget}
        title={`${payTarget?.type === "sales" ? "تحصيل" : "صرف"} — ${payTarget?.type_label || ""} رقم ${payTarget?.id || ""}`}
        onClose={() => setPayTarget(null)}
      >
        {payTarget && (
          <div className="space-y-4">
            <div className={`rounded-lg p-4 text-sm space-y-1 ${
              payTarget.type === "sales" ? "bg-emerald-50 border border-emerald-200" : "bg-rose-50 border border-rose-200"
            }`}>
              <div>
                <span className="text-slate-500">النوع: </span>
                <Badge tone={TYPE_COLORS[payTarget.type]}>{payTarget.type_label}</Badge>
              </div>
              <div>
                <span className="text-slate-500">الحساب: </span>
                <span className="font-bold">{payTarget.account_label}</span>
              </div>
              <div>
                <span className="text-slate-500">الطرف: </span>
                <span className="font-bold">{payTarget.party_name}</span>
              </div>
              <div>
                <span className="text-slate-500">الإجمالي: </span>
                <span className="font-bold">{money(payTarget.total)}</span>
              </div>
              <div>
                <span className="text-slate-500">المدفوع سابقاً: </span>
                <span className="font-bold text-emerald-600">{money(payTarget.paid_amount)}</span>
              </div>
              <div>
                <span className="text-slate-500">المتبقي: </span>
                <span className="font-bold text-rose-600">{money(payTarget.remaining)}</span>
              </div>
            </div>

            <div className={`rounded-lg p-3 text-xs font-bold ${
              payTarget.type === "sales"
                ? "bg-emerald-100 text-emerald-700"
                : "bg-rose-100 text-rose-700"
            }`}>
              {payTarget.type === "sales"
                ? "القيد: مدين الصندوق / البنك، دائن ذمم العملاء (1020)"
                : "القيد: مدين ذمم الموردين (2010)، دائن الصندوق / البنك"}
            </div>

            <div>
              <label className="mb-1 block text-sm font-bold text-slate-700">
                {payTarget.type === "sales" ? "مبلغ التحصيل" : "مبلغ الصرف"}
              </label>
              <input
                type="number"
                min="0.01"
                step="0.01"
                max={payTarget.remaining}
                value={payAmount}
                onChange={(e) => setPayAmount(e.target.value)}
                className="w-full rounded-lg border px-3 py-2 text-lg font-bold focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
                autoFocus
              />
            </div>

            <div className="flex gap-2">
              <Button variant={payTarget.type === "sales" ? "primary" : "danger"} onClick={submitPayment} disabled={paying}>
                {paying ? "جاري التسجيل..." : payTarget.type === "sales" ? "تسجيل التحصيل" : "تسجيل الصرف"}
              </Button>
              <Button onClick={() => setPayTarget(null)}>إلغاء</Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
