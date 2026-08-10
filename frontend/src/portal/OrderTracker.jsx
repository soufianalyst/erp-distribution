// A shop following its own order.
//
// The same idea as the office tracker but a different reader, and the difference
// matters. Staff want the operational truth — which round, whether the till has the
// money. A shop wants one thing: is it coming, and when. So the steps are plainer,
// the wording is theirs, and nothing about how we run the warehouse appears.
//
// Deliberately its own component rather than a shared one with the office card.
// Sharing would mean the day someone adds a field for staff, it appears in a
// customer's browser too — which is the same reason the portal keeps its own
// schemas on the server.
import { Alert, Loading } from "../components/Ui";
import useFetch from "../hooks/useFetch";
import portalApi from "../services/portalApi";

const ICONS = {
  placed: "📝",
  confirmed: "👍",
  prepared: "📦",
  ready: "🚚",
  completed: "🎉",
  cancelled: "✖️",
};

const CIRCLE = {
  done: "bg-emerald-500 text-white ring-4 ring-emerald-100 dark:ring-emerald-900/40",
  current: "bg-amber-400 text-white ring-4 ring-amber-100 dark:ring-amber-900/40",
  pending: "bg-slate-200 text-slate-400 dark:bg-slate-700 dark:text-slate-500",
  failed: "bg-rose-500 text-white ring-4 ring-rose-100 dark:ring-rose-900/40",
};

const LABEL = {
  done: "text-slate-700 dark:text-slate-200",
  current: "font-extrabold text-slate-900 dark:text-white",
  pending: "text-slate-400 dark:text-slate-500",
  failed: "font-extrabold text-rose-700 dark:text-rose-400",
};

export default function OrderTracker({ orderId }) {
  const tracker = useFetch(
    () => portalApi.get(`/portal/orders/${orderId}/timeline`),
    [orderId]
  );

  if (tracker.loading) return <Loading />;
  if (tracker.error) return <Alert>{tracker.error}</Alert>;
  const data = tracker.data;
  if (!data) return null;

  return (
    <div className="overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-slate-200 dark:bg-slate-800 dark:ring-slate-700">
      <div className="bg-teal-500 px-5 py-3 dark:bg-teal-600">
        <div className="text-sm font-bold text-white">
          تتبّع الطلب رقم {data.order_id}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-4 bg-teal-400/90 px-5 py-3 dark:bg-teal-700/80">
        <div>
          <div className="text-[11px] font-bold uppercase tracking-wide text-white/70">
            الحالة
          </div>
          <div className="truncate text-sm font-bold text-white">
            {data.status_label}
          </div>
        </div>
        <div>
          <div className="text-[11px] font-bold uppercase tracking-wide text-white/70">
            {data.fulfillment === "pickup" ? "طريقة الاستلام" : "موعد التوصيل"}
          </div>
          <div className="truncate text-sm font-bold text-white">
            {data.fulfillment === "pickup"
              ? "استلام من المستودع"
              : data.expected || "سنحدده قريباً"}
          </div>
        </div>
      </div>

      <div className="px-4 py-7">
        {/* Wide screens get the horizontal line; phones get the same steps
            stacked, because a shop opens this on a phone behind the counter and
            five circles across 320px is unreadable. */}
        <div className="hidden items-start sm:flex">
          {data.steps.map((step, index) => (
            <div key={step.key} className="flex flex-1 items-start">
              <div className="flex min-w-0 flex-1 flex-col items-center gap-2 px-1 text-center">
                <span
                  className={`flex h-12 w-12 items-center justify-center rounded-full text-lg ${CIRCLE[step.state]}`}
                >
                  {ICONS[step.key] || "•"}
                </span>
                <span className={`text-sm ${LABEL[step.state]}`}>{step.label}</span>
                {step.detail && (
                  <span className="text-[11px] leading-snug text-slate-400 dark:text-slate-500">
                    {step.detail}
                  </span>
                )}
              </div>
              {index < data.steps.length - 1 && (
                <div className="mx-1 mt-6 h-1 flex-1 rounded-full bg-slate-200 dark:bg-slate-700">
                  {(step.state === "done" || step.state === "failed") && (
                    <div
                      className={`h-1 rounded-full ${
                        step.state === "failed" ? "bg-rose-400" : "bg-emerald-400"
                      }`}
                    />
                  )}
                </div>
              )}
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
                  <div className="text-xs text-slate-500 dark:text-slate-400">{step.detail}</div>
                )}
              </div>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
