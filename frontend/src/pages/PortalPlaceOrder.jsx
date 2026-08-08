// Review the cart and file the order. The customer picks quantities (already in
// the cart from the catalog), chooses pickup/delivery and optionally a
// warehouse, and adds a note. No prices appear anywhere.
import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { Alert, Button, Card, Input, Loading, Select, qty } from "../components/Ui";
import { useAuth } from "../context/AuthContext";
import { useCart } from "../components/PortalLayout";
import useFetch from "../hooks/useFetch";
import api, { apiMessage } from "../services/api";

export default function PortalPlaceOrder() {
  const navigate = useNavigate();
  const { cart, clear, count } = useCart();
  const { data, loading } = useFetch(() => api.get("/portal/catalog"));
  const [fulfillment, setFulfillment] = useState("delivery");
  const [warehouseId, setWarehouseId] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const catalog = data || [];
  // Warehouse choices the customer can point the order at (stock real warehouses).
  const warehouseOptions = [...new Map(
    catalog.filter((i) => i.warehouse_id).map((i) => [i.warehouse_id, i])
  ).values()];

  const byId = new Map(catalog.map((i) => [i.product_id, i]));
  const lines = Object.entries(cart)
    .map(([id, quantity]) => {
      const item = byId.get(Number(id));
      return { product_id: Number(id), product_name: item?.product_name || "", quantity, item };
    })
    .filter((line) => line.quantity > 0);

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.post("/portal/orders", {
        lines: lines.map(({ product_id, quantity }) => ({ product_id, quantity })),
        fulfillment,
        warehouse_id: warehouseId ? Number(warehouseId) : null,
        notes: notes || null,
      });
      clear();
      navigate("/portal/orders");
    } catch (err) {
      setError(apiMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (!count || loading) {
    return (
      <Card>
        {loading ? (
          <Loading />
        ) : (
          <div className="py-10 text-center text-sm text-slate-400">
            سلتك فارغة.{" "}
            <Link to="/portal/catalog" className="font-bold text-emerald-700 dark:text-emerald-400">
              تصفح الكتالوج واختر ما تحتاجه
            </Link>
          </div>
        )}
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-extrabold">تأكيد الطلب</h1>

      <Card title={`سلة الطلب (${count} قطعة)`}>
        <Alert>{error}</Alert>
        <ul className="divide-y divide-slate-100 dark:divide-slate-800">
          {lines.map((line) => (
            <li key={line.product_id} className="flex items-center justify-between gap-3 py-3">
              <div className="min-w-0">
                <div className="font-bold">{line.product_name}</div>
                <div className="text-xs text-slate-500 dark:text-slate-400">
                  {line.item?.sku} · الكمية المتوفرة: {qty(line.item?.available_quantity)}
                </div>
              </div>
              <span className="font-extrabold">{qty(line.quantity)}</span>
            </li>
          ))}
        </ul>
      </Card>

      <form onSubmit={submit} className="space-y-4">
        <Card title="تفاصيل التوصيل">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Select label="طريقة التوصيل" value={fulfillment} onChange={(e) => setFulfillment(e.target.value)}>
              <option value="delivery">توصيل إلى محلّي</option>
              <option value="pickup">استلام من المستودع</option>
            </Select>
            <Select label="المستودع (اختياري)" value={warehouseId} onChange={(e) => setWarehouseId(e.target.value)}>
              <option value="">— يحدده فريق المبيعات —</option>
              {warehouseOptions.map((w) => (
                <option key={w.warehouse_id} value={w.warehouse_id}>
                  {w.warehouse_name}
                </option>
              ))}
            </Select>
          </div>
          <div className="mt-4">
            <Input label="ملاحظات (اختياري)" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="مثال: التسليم قبل الساعة الثانية ظهراً" />
          </div>
        </Card>
        <div className="flex justify-end gap-2">
          <Link to="/portal/catalog">
            <Button type="button" variant="secondary">متابعة التسوق</Button>
          </Link>
          <Button type="submit" disabled={busy || lines.length === 0}>
            {busy ? "جارٍ إرسال الطلب..." : "إرسال الطلب"}
          </Button>
        </div>
      </form>
    </div>
  );
}