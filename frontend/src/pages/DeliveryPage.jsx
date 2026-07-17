import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  Badge,
  Button,
  Card,
  Input,
  Loading,
  Modal,
  Select,
  Table,
  qty,
} from "../components/Ui";
import { useAuth } from "../context/AuthContext";
import useFetch from "../hooks/useFetch";
import api, { apiMessage } from "../services/api";

export const TRIP_STATUS = {
  planned: { label: "قيد التجهيز", tone: "amber" },
  in_transit: { label: "قيد التوصيل", tone: "blue" },
  completed: { label: "مكتملة", tone: "green" },
};

export const STOP_STATUS = {
  pending: { label: "بانتظار التسليم", tone: "slate" },
  delivered: { label: "تم التسليم", tone: "green" },
  failed: { label: "تعذر التسليم", tone: "red" },
};

function TripDetails({ trip, invoices, canManage, onChanged, onError }) {
  const navigate = useNavigate();
  const [invoiceToAdd, setInvoiceToAdd] = useState("");

  const invoiceOf = (invoiceId) => invoices.find((i) => i.id === invoiceId);
  const itemsText = (invoiceId) =>
    (invoiceOf(invoiceId)?.items || [])
      .map((item) => `${item.product_name} ×${qty(item.quantity)}`)
      .join("، ");

  // Delivery-type invoices from the trip's warehouse not already on this trip.
  const assignedIds = new Set(trip.stops.map((s) => s.invoice_id));
  const candidates = invoices.filter(
    (i) =>
      i.warehouse_id === trip.warehouse_id &&
      i.fulfillment !== "pickup" &&
      !assignedIds.has(i.id)
  );

  const call = async (fn) => {
    try {
      await fn();
      onChanged();
    } catch (err) {
      onError(apiMessage(err));
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between text-sm font-bold text-slate-600">
        <span>
          السائق: {trip.driver_name}
          {trip.vehicle ? ` — ${trip.vehicle}` : ""} | التاريخ: {trip.trip_date}
        </span>
        <div className="flex items-center gap-2">
          <Badge tone={TRIP_STATUS[trip.status].tone}>{TRIP_STATUS[trip.status].label}</Badge>
          <Button variant="secondary" onClick={() => navigate(`/print/picking/${trip.id}`)}>
            🖨️ قائمة التجهيز
          </Button>
        </div>
      </div>

      <Table
        columns={[
          { key: "sequence", label: "#" },
          {
            key: "invoice_id",
            label: "الفاتورة",
            render: (s) => `فاتورة ${s.invoice_id}`,
          },
          {
            key: "customer",
            label: "العميل",
            render: (s) => invoiceOf(s.invoice_id)?.customer_name ?? "—",
          },
          {
            key: "items",
            label: "الأصناف والكميات",
            render: (s) => itemsText(s.invoice_id) || "—",
          },
          {
            key: "status",
            label: "الحالة",
            render: (s) => (
              <Badge tone={STOP_STATUS[s.status].tone}>{STOP_STATUS[s.status].label}</Badge>
            ),
          },
          {
            key: "actions",
            label: "",
            render: (s) =>
              canManage && (
                <div className="flex gap-1">
                  {trip.status === "planned" && (
                    <Button
                      variant="danger"
                      onClick={() =>
                        call(() => api.delete(`/delivery/trips/${trip.id}/stops/${s.id}`))
                      }
                    >
                      إزالة
                    </Button>
                  )}
                  {trip.status === "in_transit" && s.status === "pending" && (
                    <>
                      <Button
                        onClick={() =>
                          call(() =>
                            api.post(`/delivery/trips/${trip.id}/stops/${s.id}/status`, {
                              status: "delivered",
                            })
                          )
                        }
                      >
                        ✓ تم التسليم
                      </Button>
                      <Button
                        variant="danger"
                        onClick={() =>
                          call(() =>
                            api.post(`/delivery/trips/${trip.id}/stops/${s.id}/status`, {
                              status: "failed",
                              notes: "تعذر التسليم",
                            })
                          )
                        }
                      >
                        ✗ تعذر
                      </Button>
                    </>
                  )}
                </div>
              ),
          },
        ]}
        rows={trip.stops}
        empty="لا توجد طلبيات على هذه الرحلة بعد."
      />

      {canManage && trip.status === "planned" && (
        <div className="flex items-end gap-2 rounded-lg border border-slate-200 bg-slate-50 p-3">
          <div className="flex-1">
            <Select
              label="إضافة فاتورة للرحلة"
              value={invoiceToAdd}
              onChange={(e) => setInvoiceToAdd(e.target.value)}
            >
              <option value="">— اختر فاتورة —</option>
              {candidates.map((i) => (
                <option key={i.id} value={i.id}>
                  فاتورة {i.id} — {i.customer_name}
                </option>
              ))}
            </Select>
          </div>
          <Button
            disabled={!invoiceToAdd}
            onClick={() =>
              call(async () => {
                await api.post(`/delivery/trips/${trip.id}/invoices`, {
                  invoice_id: Number(invoiceToAdd),
                });
                setInvoiceToAdd("");
              })
            }
          >
            + إضافة
          </Button>
        </div>
      )}

      {canManage && (
        <div className="flex justify-end gap-2 border-t border-slate-200 pt-3">
          {trip.status === "planned" && (
            <Button
              onClick={() => call(() => api.post(`/delivery/trips/${trip.id}/dispatch`))}
              disabled={!trip.stops.length}
            >
              🚚 إطلاق الرحلة
            </Button>
          )}
          {trip.status === "in_transit" && (
            <Button onClick={() => call(() => api.post(`/delivery/trips/${trip.id}/complete`))}>
              إنهاء الرحلة
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

function PickupQueue({ invoices, canManage, onChanged, onError }) {
  const navigate = useNavigate();
  // Pickup invoices, the ones still awaiting handover first.
  const pickups = invoices
    .filter((i) => i.fulfillment === "pickup")
    .sort((a, b) => (a.picked_up_at ? 1 : 0) - (b.picked_up_at ? 1 : 0));

  const handOver = async (invoice) => {
    try {
      await api.post(`/sales/invoices/${invoice.id}/pickup`);
      onChanged();
    } catch (err) {
      onError(apiMessage(err));
    }
  };

  return (
    <Card title="استلام من المستودع — طلبيات تُسلَّم للعميل عند محلنا">
      <Table
        columns={[
          { key: "id", label: "الفاتورة", render: (r) => `فاتورة ${r.id}` },
          { key: "customer_name", label: "العميل" },
          { key: "invoice_date", label: "التاريخ" },
          {
            key: "items",
            label: "الأصناف والكميات",
            render: (r) =>
              (r.items || [])
                .map((item) => `${item.product_name} ×${qty(item.quantity)}`)
                .join("، ") || "—",
          },
          {
            key: "payment_method",
            label: "الدفع",
            render: (r) =>
              r.payment_method === "cash" ? <Badge tone="green">نقدي</Badge> : <Badge tone="amber">آجل</Badge>,
          },
          {
            key: "status",
            label: "الحالة",
            render: (r) =>
              r.picked_up_at ? (
                <Badge tone="green">تم الاستلام — {r.picked_up_at.slice(0, 10)}</Badge>
              ) : (
                <Badge tone="amber">بانتظار الاستلام</Badge>
              ),
          },
          {
            key: "actions",
            label: "",
            render: (r) => (
              <div className="flex gap-1">
                <Button variant="secondary" onClick={() => navigate(`/print/pickup/${r.id}`)}>
                  🖨️ قسيمة تجهيز
                </Button>
                {canManage && !r.picked_up_at && (
                  <Button onClick={() => handOver(r)}>✓ تسليم البضاعة</Button>
                )}
              </div>
            ),
          },
        ]}
        rows={pickups}
        empty="لا توجد طلبيات استلام من المستودع."
      />
    </Card>
  );
}

export default function DeliveryPage() {
  const { can } = useAuth();
  const canManage = can("delivery.manage");
  const [tab, setTab] = useState("trips");
  const trips = useFetch(() => api.get("/delivery/trips"));
  // Price-free summaries: items, quantities, and destination only.
  const invoices = useFetch(() => api.get("/delivery/invoices"));
  const warehouses = useFetch(() => api.get("/inventory/warehouses"));

  const [open, setOpen] = useState(false);
  const [viewingId, setViewingId] = useState(null);
  const [form, setForm] = useState({ driver_name: "", vehicle: "", warehouse_id: "" });
  const [error, setError] = useState(null);
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    try {
      const { data } = await api.post("/delivery/trips", form);
      setOpen(false);
      setForm({ driver_name: "", vehicle: "", warehouse_id: "" });
      trips.reload();
      setViewingId(data.data.id);
    } catch (err) {
      setError(apiMessage(err));
    }
  };

  if (trips.loading || invoices.loading || warehouses.loading) {
    return <Loading />;
  }

  const viewing = trips.data?.find((t) => t.id === viewingId);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-extrabold">التوزيع والتسليم</h1>
        <div className="flex gap-2">
          <Button variant={tab === "trips" ? "primary" : "secondary"} onClick={() => setTab("trips")}>
            🚛 رحلات التوصيل
          </Button>
          <Button variant={tab === "pickup" ? "primary" : "secondary"} onClick={() => setTab("pickup")}>
            🏬 استلام من المستودع
          </Button>
          {canManage && tab === "trips" && (
            <Button onClick={() => setOpen(true)}>+ رحلة جديدة</Button>
          )}
        </div>
      </div>

      <Alert>{error}</Alert>

      {tab === "pickup" && (
        <PickupQueue
          invoices={invoices.data || []}
          canManage={canManage}
          onChanged={() => invoices.reload()}
          onError={setError}
        />
      )}

      {tab === "trips" && (
      <Card>
        <Alert>{trips.error}</Alert>
        <Table
          columns={[
            { key: "id", label: "#" },
            { key: "trip_date", label: "التاريخ" },
            { key: "driver_name", label: "السائق" },
            { key: "vehicle", label: "المركبة", render: (t) => t.vehicle || "—" },
            {
              key: "warehouse_id",
              label: "المستودع",
              render: (t) => (warehouses.data || []).find((w) => w.id === t.warehouse_id)?.name ?? "—",
            },
            { key: "stops", label: "الطلبيات", render: (t) => t.stops.length },
            {
              key: "status",
              label: "الحالة",
              render: (t) => (
                <Badge tone={TRIP_STATUS[t.status].tone}>{TRIP_STATUS[t.status].label}</Badge>
              ),
            },
            {
              key: "view",
              label: "",
              render: (t) => (
                <Button variant="secondary" onClick={() => setViewingId(t.id)}>
                  إدارة
                </Button>
              ),
            },
          ]}
          rows={trips.data}
          empty="لا توجد رحلات توزيع بعد."
        />
      </Card>
      )}

      <Modal open={open} title="رحلة توزيع جديدة" onClose={() => setOpen(false)}>
        <form onSubmit={submit} className="space-y-4">
          <Input label="اسم السائق" value={form.driver_name} onChange={set("driver_name")} required autoFocus />
          <Input label="المركبة (اختياري)" value={form.vehicle} onChange={set("vehicle")} />
          <Select label="مستودع التحميل" value={form.warehouse_id} onChange={set("warehouse_id")} required>
            <option value="">— اختر المستودع —</option>
            {(warehouses.data || []).map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </Select>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setOpen(false)}>
              إلغاء
            </Button>
            <Button type="submit">إنشاء الرحلة</Button>
          </div>
        </form>
      </Modal>

      <Modal
        open={!!viewing}
        title={viewing ? `رحلة التوزيع رقم ${viewing.id}` : ""}
        onClose={() => setViewingId(null)}
        wide
      >
        {viewing && (
          <TripDetails
            trip={viewing}
            invoices={invoices.data || []}
            canManage={canManage}
            onChanged={() => trips.reload()}
            onError={setError}
          />
        )}
      </Modal>
    </div>
  );
}
