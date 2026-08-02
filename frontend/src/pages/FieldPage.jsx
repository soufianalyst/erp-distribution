// The salesman's round, built to work with no signal.
//
// Everything here reads from the cached snapshot and writes to the outbound
// queue; nothing waits on the network. What the customer receives at the door is
// a provisional reference, because the real invoice number only exists once the
// round reaches the server.

import { useMemo, useState } from "react";
import { Alert, Badge, Button, Card, Input, Loading, Select, money, qty } from "../components/Ui";
import { useAuth } from "../context/AuthContext";
import useFieldSync from "../hooks/useFieldSync";
import { enqueue, newClientUuid, provisionalReference } from "../services/offlineStore";

const TIER_PRICE_FIELD = {
  wholesale: "wholesale_price",
  half_wholesale: "half_wholesale_price",
  retail: "retail_price",
};

const round2 = (n) => Math.round((Number(n) + Number.EPSILON) * 100) / 100;

function ConnectionBar({ online, cacheAvailable, pending, syncing, onSync, snapshot }) {
  const failed = pending.filter((d) => d.last_error).length;
  return (
    <div className="sticky top-0 z-20 -mx-4 mb-4 flex flex-wrap items-center justify-between gap-2 bg-slate-900 px-4 py-3 text-slate-100 sm:-mx-6 sm:px-6">
      <div className="flex flex-wrap items-center gap-2 text-sm font-bold">
        <Badge tone={online ? "green" : "amber"}>
          {online ? "متصل" : "بدون اتصال"}
        </Badge>
        {pending.length > 0 && (
          <Badge tone={failed ? "red" : "blue"}>
            {pending.length} بانتظار الرفع{failed ? ` (${failed} مرفوض)` : ""}
          </Badge>
        )}
        {pending.length === 0 && online && cacheAvailable && (
          <span className="text-xs">كل شيء مرفوع ✓</span>
        )}
        {/* Without local storage the round cannot survive losing signal, so say
            so plainly rather than let it fail silently out in the field. */}
        {!cacheAvailable && (
          <Badge tone="red">التخزين المحلي غير متاح — العمل بدون اتصال معطّل</Badge>
        )}
      </div>
      <div className="flex items-center gap-2">
        {snapshot?.saved_at && (
          <span className="text-xs text-slate-400">
            بيانات محدّثة: {snapshot.saved_at.slice(11, 16)}
          </span>
        )}
        <Button onClick={onSync} disabled={!online || syncing || !pending.length}>
          {syncing ? "جارٍ الرفع..." : "رفع الجولة"}
        </Button>
      </div>
    </div>
  );
}

function NewCustomerForm({ onQueued, onCancel }) {
  const [form, setForm] = useState({ name: "", phone: "", address: "", price_tier: "wholesale" });
  const [error, setError] = useState(null);
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  const submit = async (event) => {
    event.preventDefault();
    if (form.name.trim().length < 2) {
      setError("اكتب اسم المحل.");
      return;
    }
    const client_uuid = newClientUuid();
    await enqueue({ kind: "customer", client_uuid, ...form, name: form.name.trim() });
    onQueued({ client_uuid, ...form, name: form.name.trim() });
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <Alert>{error}</Alert>
      <p className="text-xs font-bold text-slate-600 dark:text-slate-400">
        يُسجَّل المحل على جولتك ويُرفع مع بقية الجولة عند عودة الاتصال.
      </p>
      <Input label="اسم المحل" value={form.name} onChange={set("name")} required autoFocus />
      <Input label="الهاتف" value={form.phone} onChange={set("phone")} />
      <Input label="العنوان" value={form.address} onChange={set("address")} />
      <Select label="فئة السعر" value={form.price_tier} onChange={set("price_tier")}>
        <option value="wholesale">جملة</option>
        <option value="half_wholesale">نصف جملة</option>
        <option value="retail">تجزئة</option>
      </Select>
      <div className="flex gap-2">
        <Button type="submit">حفظ المحل</Button>
        <Button type="button" variant="secondary" onClick={onCancel}>
          إلغاء
        </Button>
      </div>
    </form>
  );
}

export default function FieldPage() {
  const { user } = useAuth();
  const {
    online,
    cacheAvailable,
    snapshot,
    pending,
    syncing,
    lastResult,
    error,
    sync,
    refreshPending,
  } = useFieldSync();

  const [kind, setKind] = useState("van_sale");
  // A customer is either an existing one (id) or one queued on this device (uuid).
  const [buyer, setBuyer] = useState(null);
  const [addingCustomer, setAddingCustomer] = useState(false);
  const [lines, setLines] = useState([]);
  const [receipt, setReceipt] = useState(null);
  const [formError, setFormError] = useState(null);

  const products = snapshot?.products ?? [];
  const van = snapshot?.van ?? null;
  const taxRateIds = (snapshot?.taxRates ?? []).filter((t) => t.is_default).map((t) => t.id);

  // Locally-queued customers are selectable immediately; they have no id yet.
  const queuedCustomers = pending.filter((d) => d.kind === "customer");
  const allCustomers = useMemo(
    () => [
      ...(snapshot?.customers ?? []).map((c) => ({
        key: `id:${c.id}`,
        label: c.name,
        customer_id: c.id,
        price_tier: c.price_tier,
      })),
      ...queuedCustomers.map((c) => ({
        key: `uuid:${c.client_uuid}`,
        label: `${c.name} (جديد — لم يُرفع بعد)`,
        customer_uuid: c.client_uuid,
        price_tier: c.price_tier,
      })),
    ],
    [snapshot?.customers, queuedCustomers]
  );

  // What the van holds, minus anything already queued but not yet synced — so
  // two sales in a row cannot promise the same carton twice.
  const vanAvailable = useMemo(() => {
    const available = new Map(
      (van?.lines ?? []).map((l) => [l.product_id, Number(l.quantity)])
    );
    for (const doc of pending) {
      if (doc.kind !== "van_sale") continue;
      for (const line of doc.lines ?? []) {
        available.set(
          line.product_id,
          (available.get(line.product_id) ?? 0) - Number(line.quantity)
        );
      }
    }
    return available;
  }, [van, pending]);

  const priceFor = (product) =>
    Number(product[TIER_PRICE_FIELD[buyer?.price_tier ?? "wholesale"]] ?? 0);

  const total = lines.reduce(
    (sum, l) => sum + round2(Number(l.quantity || 0) * priceFor(l.product)),
    0
  );

  const addLine = (productId) => {
    const product = products.find((p) => String(p.id) === String(productId));
    if (!product) return;
    setLines((current) =>
      current.some((l) => l.product.id === product.id)
        ? current
        : [...current, { product, quantity: "1" }]
    );
  };

  const submit = async () => {
    setFormError(null);
    if (!buyer) {
      setFormError("اختر المحل أولاً.");
      return;
    }
    const usable = lines.filter((l) => Number(l.quantity) > 0);
    if (!usable.length) {
      setFormError("أضف صنفاً واحداً على الأقل.");
      return;
    }
    if (kind === "van_sale") {
      const short = usable.find(
        (l) => Number(l.quantity) > (vanAvailable.get(l.product.id) ?? 0)
      );
      if (short) {
        setFormError(
          `الكمية المطلوبة من (${short.product.name}) أكبر مما تحمله السيارة.`
        );
        return;
      }
    }

    const client_uuid = newClientUuid();
    const document = {
      kind,
      client_uuid,
      customer_id: buyer.customer_id,
      customer_uuid: buyer.customer_uuid,
      payment_method: "cash",
      tax_rate_ids: taxRateIds,
      lines: usable.map((l) => ({
        product_id: l.product.id,
        quantity: String(l.quantity),
      })),
      provisional_reference: provisionalReference(client_uuid),
    };
    await enqueue(document);
    await refreshPending();
    setReceipt({
      reference: document.provisional_reference,
      kind,
      customer: buyer.label,
      total,
      lines: usable.map((l) => ({
        name: l.product.name,
        quantity: l.quantity,
        unit: l.product.base_unit_name,
        line_total: round2(Number(l.quantity) * priceFor(l.product)),
      })),
    });
    setLines([]);
    setBuyer(null);
    // Opportunistic: if there is signal it goes now, otherwise it waits.
    sync();
  };

  if (!snapshot) {
    return (
      <div className="space-y-4">
        <Loading />
        <Alert>
          {error ||
            "لم تُحمّل بيانات الجولة بعد. افتح التطبيق مرة واحدة وأنت متصل بالإنترنت قبل الخروج."}
        </Alert>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <ConnectionBar
        online={online}
        cacheAvailable={cacheAvailable}
        pending={pending}
        syncing={syncing}
        onSync={sync}
        snapshot={snapshot}
      />

      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-extrabold">جولة {user.full_name}</h1>
        {van ? (
          <Badge tone="blue">السيارة: {van.warehouse_name}</Badge>
        ) : (
          <Badge tone="slate">لا توجد سيارة مسندة — الطلبات فقط</Badge>
        )}
      </div>

      {lastResult && (
        <Alert tone={lastResult.failed_count ? "error" : "success"}>
          {`تم رفع ${lastResult.created_count}` +
            (lastResult.duplicate_count ? `، و${lastResult.duplicate_count} مرفوع مسبقاً` : "") +
            (lastResult.failed_count ? `، وتعذّر رفع ${lastResult.failed_count}` : "") +
            "."}
        </Alert>
      )}
      <Alert>{error}</Alert>

      {receipt && (
        <Card title="إيصال مبدئي — سلّمه للعميل">
          <div className="space-y-2 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <b className="text-lg">{receipt.reference}</b>
              <Badge tone="amber">رقم مبدئي — الرقم النهائي بعد الرفع</Badge>
            </div>
            <div>العميل: {receipt.customer}</div>
            <div>النوع: {receipt.kind === "van_sale" ? "بيع من السيارة" : "طلب للتجهيز"}</div>
            <table className="w-full text-right">
              <tbody>
                {receipt.lines.map((l, i) => (
                  <tr key={i} className="border-t border-slate-200 dark:border-slate-700">
                    <td className="py-1">{l.name}</td>
                    <td>
                      {qty(l.quantity)} {l.unit}
                    </td>
                    <td>{money(l.line_total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="text-left font-extrabold text-emerald-700 dark:text-emerald-400">
              الإجمالي قبل الضريبة: {money(receipt.total)}
            </div>
            <div className="flex gap-2 pt-2">
              <Button variant="secondary" onClick={() => window.print()}>
                🖨️ طباعة
              </Button>
              <Button variant="secondary" onClick={() => setReceipt(null)}>
                زيارة جديدة
              </Button>
            </div>
          </div>
        </Card>
      )}

      <Card title="زيارة جديدة">
        <div className="space-y-4">
          <Alert>{formError}</Alert>

          <div className="flex flex-wrap gap-2">
            <Button
              variant={kind === "van_sale" ? "primary" : "secondary"}
              onClick={() => setKind("van_sale")}
              disabled={!van}
            >
              بيع من السيارة
            </Button>
            <Button
              variant={kind === "order" ? "primary" : "secondary"}
              onClick={() => setKind("order")}
            >
              طلب للتجهيز
            </Button>
          </div>

          {addingCustomer ? (
            <NewCustomerForm
              onCancel={() => setAddingCustomer(false)}
              onQueued={async (customer) => {
                await refreshPending();
                setBuyer({
                  key: `uuid:${customer.client_uuid}`,
                  label: customer.name,
                  customer_uuid: customer.client_uuid,
                  price_tier: customer.price_tier,
                });
                setAddingCustomer(false);
              }}
            />
          ) : (
            <div className="flex flex-wrap items-end gap-2">
              <div className="min-w-[14rem] flex-1">
                <Select
                  label="المحل"
                  value={buyer?.key ?? ""}
                  onChange={(e) =>
                    setBuyer(allCustomers.find((c) => c.key === e.target.value) ?? null)
                  }
                >
                  <option value="">— اختر المحل —</option>
                  {allCustomers.map((c) => (
                    <option key={c.key} value={c.key}>
                      {c.label}
                    </option>
                  ))}
                </Select>
              </div>
              <Button variant="secondary" onClick={() => setAddingCustomer(true)}>
                + محل جديد
              </Button>
            </div>
          )}

          <Select
            label="أضف صنفاً"
            value=""
            onChange={(e) => addLine(e.target.value)}
          >
            <option value="">— اختر الصنف —</option>
            {products.map((p) => {
              const onVan = vanAvailable.get(p.id) ?? 0;
              return (
                <option key={p.id} value={p.id}>
                  {p.name}
                  {kind === "van_sale" ? ` — بالسيارة ${qty(onVan)}` : ""}
                </option>
              );
            })}
          </Select>

          {lines.map((line, index) => {
            const onVan = vanAvailable.get(line.product.id) ?? 0;
            const over = kind === "van_sale" && Number(line.quantity) > onVan;
            return (
              <div
                key={line.product.id}
                className="flex flex-wrap items-end gap-2 rounded-lg border border-slate-200 p-2 dark:border-slate-700"
              >
                <div className="min-w-[9rem] flex-1 text-sm font-bold">
                  {line.product.name}
                  <div className="text-xs font-normal text-slate-500 dark:text-slate-400">
                    {money(priceFor(line.product))} / {line.product.base_unit_name}
                    {kind === "van_sale" && ` — بالسيارة ${qty(onVan)}`}
                  </div>
                </div>
                <div className="w-28">
                  <Input
                    label="الكمية"
                    type="number"
                    step="any"
                    min="0"
                    value={line.quantity}
                    onChange={(e) =>
                      setLines(
                        lines.map((l, i) =>
                          i === index ? { ...l, quantity: e.target.value } : l
                        )
                      )
                    }
                  />
                </div>
                <div className="w-24 text-sm font-bold">
                  {money(round2(Number(line.quantity || 0) * priceFor(line.product)))}
                </div>
                <Button
                  variant="danger"
                  onClick={() => setLines(lines.filter((_, i) => i !== index))}
                >
                  ×
                </Button>
                {over && (
                  <span className="w-full text-xs font-bold text-rose-700 dark:text-rose-400">
                    أكبر مما تحمله السيارة.
                  </span>
                )}
              </div>
            );
          })}

          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-200 pt-3 dark:border-slate-700">
            <span className="font-extrabold">
              الإجمالي قبل الضريبة: {money(total)}
            </span>
            <Button onClick={submit} disabled={!lines.length}>
              {kind === "van_sale" ? "إتمام البيع وإصدار إيصال" : "تسجيل الطلب"}
            </Button>
          </div>
        </div>
      </Card>

      {pending.length > 0 && (
        <Card title={`بانتظار الرفع (${pending.length})`}>
          <div className="space-y-2 text-sm">
            {pending.map((doc) => (
              <div
                key={doc.client_uuid}
                className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-2 last:border-0 dark:border-slate-800"
              >
                <span className="font-bold">
                  {doc.kind === "customer"
                    ? `محل جديد: ${doc.name}`
                    : `${doc.kind === "van_sale" ? "بيع" : "طلب"} ${
                        doc.provisional_reference ?? ""
                      }`}
                </span>
                {doc.last_error ? (
                  <span className="text-xs font-bold text-rose-700 dark:text-rose-400">
                    {doc.last_error}
                  </span>
                ) : (
                  <Badge tone="blue">بانتظار الاتصال</Badge>
                )}
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
