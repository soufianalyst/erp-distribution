// Where an invoice has got to, drawn as the journey it actually took.
//
// A stepper is worth more than a status word because it shows two things at once:
// where the invoice is, and what is still ahead of it. Someone asking "where is my
// order" is really asking "what happens next and when" — a badge reading "in
// transit" answers neither.
//
// The shape of the line changes with the invoice. A counter collection has three
// stops; a delivery has five. A cash sale waits at the till before the goods may
// move; an account sale walks straight past it. The backend decides all of that —
// this only draws what it is given, so the picture can never disagree with the
// warehouse.
import { useState } from "react";
import { Alert, Loading, money } from "./Ui";
import useFetch from "../hooks/useFetch";
import api from "../services/api";

const ICONS = {
  raised: "🧾",
  payment: "💵",
  handover: "📦",
  scheduled: "🗓️",
  transit: "🚚",
  delivered: "✅",
};

// Done is settled and calm; current is the one to look at, so it is the only warm
// colour on the card; failed shouts. Pending stays deliberately quiet — greyed, so
// the eye lands on where the invoice is rather than on everything it is not.
const CIRCLE = {
  done: "bg-emerald-500 text-white ring-4 ring-emerald-100 dark:ring-emerald-900/40",
  current: "bg-amber-400 text-white ring-4 ring-amber-100 dark:ring-amber-900/40",
  pending:
    "bg-slate-200 text-slate-400 dark:bg-slate-700 dark:text-slate-500",
  failed: "bg-rose-500 text-white ring-4 ring-rose-100 dark:ring-rose-900/40",
};

const LABEL = {
  done: "text-slate-700 dark:text-slate-200",
  current: "font-extrabold text-slate-900 dark:text-white",
  pending: "text-slate-400 dark:text-slate-500",
  failed: "font-extrabold text-rose-700 dark:text-rose-400",
};

/** The bar between two circles: coloured only where the invoice has already been. */
function Connector({ from }) {
  const filled = from === "done";
  const failed = from === "failed";
  return (
    <div className="relative mx-1 mt-6 h-1 flex-1 rounded-full bg-slate-200 dark:bg-slate-700">
      {(filled || failed) && (
        <div
          className={`absolute inset-0 rounded-full ${
            failed ? "bg-rose-400" : "bg-emerald-400"
          }`}
        />
      )}
    </div>
  );
}

function HeaderFact({ label, value }) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] font-bold uppercase tracking-wide text-white/70">
        {label}
      </div>
      <div className="truncate text-sm font-bold text-white">{value}</div>
    </div>
  );
}

export default function InvoiceTracker({ invoiceId }) {
  const tracker = useFetch(
    () => api.get(`/sales/invoices/${invoiceId}/timeline`),
    [invoiceId]
  );
  // Which step's detail is open. Every step carries a sentence — the driver's
  // name, what is still owed — but showing five at once turns the card into a
  // paragraph, so they open one at a time.
  const [open, setOpen] = useState(null);

  if (tracker.loading) return <Loading />;
  if (tracker.error) return <Alert>{tracker.error}</Alert>;
  const data = tracker.data;
  if (!data) return null;

  return (
    <div className="overflow-hidden rounded-xl shadow-sm ring-1 ring-slate-200 dark:ring-slate-700">
      <div className="bg-teal-500 px-5 py-3 dark:bg-teal-600">
        <div className="text-sm font-bold text-white">
          تتبّع الفاتورة — {data.reference}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-4 bg-teal-400/90 px-5 py-3 sm:grid-cols-4 dark:bg-teal-700/80">
        <HeaderFact label="العميل" value={data.customer_name} />
        <HeaderFact label="طريقة التسليم" value={data.shipped_via} />
        <HeaderFact label="الحالة" value={data.status_label} />
        <HeaderFact
          label={data.fulfillment === "pickup" ? "المتبقي" : "التاريخ المتوقع"}
          value={
            data.fulfillment === "pickup"
              ? money(data.amount_due)
              : data.expected || "—"
          }
        />
      </div>

      <div className="bg-white px-4 py-8 dark:bg-slate-800">
        {/* Horizontal on anything wider than a phone; on a phone the same steps
            stack, because five circles across 320px is unreadable. */}
        <div className="hidden items-start sm:flex">
          {data.steps.map((step, index) => (
            <div key={step.key} className="flex flex-1 items-start">
              <button
                type="button"
                onClick={() => setOpen(open === step.key ? null : step.key)}
                className="flex min-w-0 flex-1 flex-col items-center gap-2 text-center"
                title={step.detail || step.label}
              >
                <span
                  className={`flex h-12 w-12 items-center justify-center rounded-full text-lg transition ${CIRCLE[step.state]}`}
                >
                  {ICONS[step.key] || "•"}
                </span>
                <span className={`px-1 text-sm ${LABEL[step.state]}`}>
                  {step.label}
                </span>
                {step.at && (
                  <span className="text-[11px] text-slate-400 dark:text-slate-500">
                    {step.at.slice(0, 10)}
                  </span>
                )}
              </button>
              {index < data.steps.length - 1 && <Connector from={step.state} />}
            </div>
          ))}
        </div>

        <ol className="space-y-4 sm:hidden">
          {data.steps.map((step) => (
            <li key={step.key} className="flex items-start gap-3">
              <span
                className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${CIRCLE[step.state]}`}
              >
                {ICONS[step.key] || "•"}
              </span>
              <div className="min-w-0 pt-1">
                <div className={`text-sm ${LABEL[step.state]}`}>{step.label}</div>
                {step.detail && (
                  <div className="text-xs text-slate-500 dark:text-slate-400">
                    {step.detail}
                  </div>
                )}
                {step.at && (
                  <div className="text-[11px] text-slate-400 dark:text-slate-500">
                    {step.at.slice(0, 10)}
                  </div>
                )}
              </div>
            </li>
          ))}
        </ol>

        {open && (
          <div className="mt-6 hidden rounded-lg bg-slate-50 px-4 py-3 text-sm text-slate-600 sm:block dark:bg-slate-700/40 dark:text-slate-300">
            {data.steps.find((s) => s.key === open)?.detail ||
              "لا توجد تفاصيل إضافية لهذه المرحلة."}
          </div>
        )}

        {Number(data.returned_total) > 0 && (
          <div className="mt-4 rounded-lg bg-amber-50 px-4 py-2 text-sm font-bold text-amber-800 dark:bg-amber-900/30 dark:text-amber-200">
            يوجد مرتجع على هذه الفاتورة بقيمة {money(data.returned_total)}
          </div>
        )}
      </div>
    </div>
  );
}
