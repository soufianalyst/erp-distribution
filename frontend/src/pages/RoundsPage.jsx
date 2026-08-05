// Closing a salesman's day (تسوية جولة المندوب).
//
// A van leaves loaded and comes back with cash, an emptier hold, and a stack of
// invoices. Every one of those was already recorded somewhere — but nothing said
// whether a given day had actually been *checked and signed off*. That absence
// was invisible: a round nobody closed looked exactly like a round with no sales.
//
// This screen is that sign-off. It shows a van's live position, refuses to close
// while cash is still outstanding, and makes a stock difference impossible to
// wave through in silence.
import { useState } from "react";
import { Alert, Badge, Button, CancelButton, Card, Input, Modal, Select, Stat, Table, money, qty, todayStr } from "../components/Ui";
import useFetch from "../hooks/useFetch";
import api, { apiMessage } from "../services/api";

const STATUS_LABELS = { open: "مفتوحة", settled: "مسوّاة", cancelled: "ملغاة" };
const STATUS_TONES = { open: "amber", settled: "green", cancelled: "slate" };
const METHOD_LABELS = { cash: "نقدي", card: "بطاقة", credit: "آجل" };
const METHOD_TONES = { cash: "green", card: "blue", credit: "amber" };

// Arabic counts its nouns by number: one is "فاتورة", two "فاتورتان", three to
// ten take the plural "فواتير", and eleven upwards returns to the singular.
// "3 فاتورة" is wrong the way "3 invoice" is wrong in English, and reads as
// broken software to people who see this screen every day.
const invoiceCount = (n) => {
  const count = Number(n) || 0;
  if (count === 1) return "فاتورة واحدة";
  if (count === 2) return "فاتورتان";
  if (count >= 3 && count <= 10) return `${count} فواتير`;
  return `${count} فاتورة`;
};

export default function RoundsPage() {
  const [vanId, setVanId] = useState("");
  const [day, setDay] = useState(todayStr());
  const [settling, setSettling] = useState(false);
  const [notes, setNotes] = useState("");
  const [dialogError, setDialogError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [error, setError] = useState(null);

  const warehouses = useFetch(() => api.get("/inventory/warehouses"));
  const history = useFetch(() => api.get("/sales/rounds"));

  // Only vans, and only ones with a salesman: a round belongs to a person, and
  // the backend rejects an unassigned vehicle anyway.
  const vans = (warehouses.data ?? []).filter((w) => w.is_vehicle && w.assigned_to_id);
  const selectedVan = vanId || (vans.length ? String(vans[0].id) : "");

  const position = useFetch(
    () =>
      selectedVan
        ? api.get("/sales/rounds/position", {
            params: { warehouse_id: selectedVan, round_date: day },
          })
        : Promise.resolve({ data: { data: null } }),
    [selectedVan, day]
  );

  const pos = position.data;

  const openSettleDialog = () => {
    setDialogError(null);
    setNotes("");
    setSettling(true);
  };

  const submitSettle = async () => {
    setDialogError(null);
    try {
      await api.post("/sales/rounds/settle-van", {
        warehouse_id: Number(selectedVan),
        round_date: day,
        notes: notes.trim() || null,
      });
      setSettling(false);
      setNotice("تمت تسوية الجولة وإقفالها.");
      position.reload();
      history.reload();
    } catch (err) {
      setDialogError(apiMessage(err));
    }
  };

  const cancelRound = async (round) => {
    if (!window.confirm(`إلغاء الجولة رقم ${round.id}؟`)) return;
    setError(null);
    try {
      await api.post(`/sales/rounds/${round.id}/cancel`);
      setNotice("تم إلغاء الجولة.");
      position.reload();
      history.reload();
    } catch (err) {
      setError(apiMessage(err));
    }
  };

  if (warehouses.loading) return null;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-extrabold">تسوية جولات المناديب</h1>
        <div className="flex flex-wrap items-end gap-2">
          <Select
            label="المركبة"
            value={selectedVan}
            onChange={(e) => setVanId(e.target.value)}
          >
            {vans.map((van) => (
              <option key={van.id} value={van.id}>
                {van.name}
              </option>
            ))}
          </Select>
          <Input label="التاريخ" type="date" value={day} onChange={(e) => setDay(e.target.value)} />
        </div>
      </div>

      <Alert tone="success">{notice}</Alert>
      {/* warehouses.error is surfaced too, not just the round's own errors: a
          failed warehouse load leaves `vans` empty, which would otherwise render
          the "no vans configured" panel below and blame the user's setup for what
          is actually a broken request. */}
      <Alert>{error || warehouses.error || history.error || position.error}</Alert>

      {!vans.length && !warehouses.error && (
        <Card title="لا توجد مركبات مسندة">
          <p className="text-sm text-slate-500 dark:text-slate-400">
            التسوية تخصّ جولات المناديب. حدّد مستودعاً كمركبة وأسنده لمندوب من صفحة
            المستودعات أولاً.
          </p>
        </Card>
      )}

      {pos && (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Stat label="عدد الفواتير" value={pos.invoice_count} tone="sky" />
            <Stat label="إجمالي المبيعات" value={money(pos.total_sales)} tone="emerald" />
            <Stat
              label="المحصَّل في الصندوق"
              value={money(pos.cash_collected_total)}
              tone="emerald"
              hint="نقدي وبطاقة"
            />
            <Stat
              label="غير محصَّل"
              value={money(pos.cash_outstanding_total)}
              // Zero outstanding is the good outcome, so it should not glow red.
              tone={Number(pos.cash_outstanding_total) > 0 ? "rose" : "slate"}
              // The hint is a warning, so it only appears when there is
              // something to warn about; "يمنع الإقفال" under a zero reads as
              // if the round were blocked when it is in fact ready.
              hint={Number(pos.cash_outstanding_total) > 0 ? "يمنع الإقفال" : "مكتمل"}
            />
          </div>

          <Card
            title={`موقف ${pos.warehouse_name} — ${pos.salesman_name}`}
            actions={
              <Button onClick={openSettleDialog} disabled={!pos.can_settle}>
                إقفال الجولة
              </Button>
            }
          >
            {/* The blockers list comes from the service, so the screen can never
                disagree with what the API will actually allow. */}
            {pos.blockers.length > 0 && (
              <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 dark:border-amber-900 dark:bg-amber-950/50">
                <div className="text-sm font-extrabold text-amber-800 dark:text-amber-200">
                  ما يمنع الإقفال الآن
                </div>
                <ul className="mt-2 list-inside list-disc space-y-1 text-sm text-amber-800 dark:text-amber-200">
                  {pos.blockers.map((blocker) => (
                    <li key={blocker}>{blocker}</li>
                  ))}
                </ul>
              </div>
            )}

            <div className="mb-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
              <Figure label="نقدي" value={money(pos.cash_sales_total)} />
              <Figure label="بطاقة" value={money(pos.card_sales_total)} />
              <Figure label="آجل" value={money(pos.credit_sales_total)} />
              <Figure
                label="فرق المخزون"
                // Quantity first: the value is priced at the batch's cost and
                // reads 0.00 when that cost is unknown, so money alone can make a
                // genuine shortfall look like a balanced round.
                value={
                  pos.has_stock_variance
                    ? `${qty(pos.stock_variance_qty)} وحدة (${money(pos.stock_variance_value)})`
                    : pos.stocktake_id
                      ? "مطابق"
                      : "لا يوجد جرد"
                }
                tone={pos.has_stock_variance ? "rose" : "slate"}
              />
            </div>

            <Table
              columns={[
                { key: "id", label: "الفاتورة", render: (r) => `#${r.id}` },
                { key: "customer_name", label: "العميل" },
                {
                  key: "payment_method",
                  label: "طريقة الدفع",
                  render: (r) => (
                    <Badge tone={METHOD_TONES[r.payment_method]}>
                      {METHOD_LABELS[r.payment_method] ?? r.payment_method}
                    </Badge>
                  ),
                },
                { key: "total", label: "الإجمالي", render: (r) => money(r.total) },
                { key: "collected", label: "المحصَّل", render: (r) => money(r.collected) },
                {
                  key: "outstanding",
                  label: "المتبقي",
                  render: (r) =>
                    Number(r.outstanding) > 0 ? (
                      <Badge tone="red">{money(r.outstanding)}</Badge>
                    ) : (
                      <Badge tone="green">محصَّلة</Badge>
                    ),
                },
              ]}
              rows={pos.invoices}
              empty="لا توجد فواتير على هذه المركبة في هذا التاريخ."
            />
          </Card>
        </>
      )}

      <Card title="سجل التسويات">
        <Table
          columns={[
            { key: "id", label: "الرقم", render: (r) => `#${r.id}` },
            { key: "round_date", label: "التاريخ" },
            { key: "warehouse_name", label: "المركبة" },
            { key: "salesman_name", label: "المندوب" },
            {
              key: "status",
              label: "الحالة",
              render: (r) => (
                <Badge tone={STATUS_TONES[r.status]}>{STATUS_LABELS[r.status] ?? r.status}</Badge>
              ),
            },
            { key: "invoice_count", label: "الفواتير" },
            { key: "total_sales", label: "المبيعات", render: (r) => money(r.total_sales) },
            {
              key: "is_balanced",
              label: "المطابقة",
              render: (r) =>
                r.status !== "settled" ? (
                  <span className="text-slate-400">—</span>
                ) : r.is_balanced ? (
                  <Badge tone="green">مطابقة</Badge>
                ) : (
                  <Badge tone="red">
                    فرق {qty(r.stock_variance_qty)} وحدة
                  </Badge>
                ),
            },
            { key: "notes", label: "الملاحظات" },
            {
              key: "actions",
              label: "",
              render: (r) =>
                r.status === "open" ? (
                  <Button variant="danger" onClick={() => cancelRound(r)}>
                    إلغاء
                  </Button>
                ) : null,
            },
          ]}
          rows={history.data ?? []}
          empty="لم تُسجّل أي تسوية بعد."
        />
      </Card>

      <Modal
        open={settling}
        title="إقفال الجولة"
        onClose={() => setSettling(false)}
        // The dialog holds a note, not a record being edited; the confirmation
        // itself is the guard, so it opts out of the unsaved-changes prompt.
        guardUnsaved={false}
      >
        <Alert>{dialogError}</Alert>
          <p className="mb-4 text-sm text-slate-600 dark:text-slate-300">
            سيُثبَّت موقف الجولة كما هو الآن: {invoiceCount(pos?.invoice_count)} بإجمالي{" "}
            {money(pos?.total_sales ?? 0)}.
          </p>
          {pos?.has_stock_variance && (
            <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-bold text-rose-800 dark:border-rose-900 dark:bg-rose-950/50 dark:text-rose-200">
              الجولة بها فرق مخزون {qty(pos.stock_variance_qty)} وحدة — اكتب سبب الفرق،
              وهو إلزامي.
              {pos.variance_needs_approval && (
                <div className="mt-1 font-extrabold">
                  الفرق يتجاوز حدّ الإقرار ({money(pos.variance_approval_limit)}) ويحتاج صلاحية
                  إقرار الفروقات.
                </div>
              )}
            </div>
          )}
          <Input
            label={pos?.has_stock_variance ? "سبب الفرق (إلزامي)" : "ملاحظات (اختياري)"}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            maxLength={500}
            autoFocus
          />
          <div className="mt-5 flex justify-end gap-2">
            <CancelButton onClose={() => setSettling(false)} />
            <Button onClick={submitSettle}>تأكيد الإقفال</Button>
          </div>
        </Modal>
    </div>
  );
}

// A labelled figure inside a card — smaller than a Stat, which is for the
// headline row at the top of the page.
function Figure({ label, value, tone = "slate" }) {
  const tones = {
    slate: "text-slate-800 dark:text-slate-100",
    rose: "text-rose-700 dark:text-rose-400",
  };
  return (
    <div className="rounded-lg bg-slate-50 px-3 py-2 dark:bg-slate-800/50">
      <div className="text-xs font-bold text-slate-500 dark:text-slate-400">{label}</div>
      <div className={`mt-0.5 font-extrabold ${tones[tone]}`}>{value}</div>
    </div>
  );
}
