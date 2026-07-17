import { useState } from "react";
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
  money,
} from "../components/Ui";
import { useAuth } from "../context/AuthContext";
import useFetch from "../hooks/useFetch";
import api, { apiMessage } from "../services/api";

const EMPTY_FORM = {
  sku: "",
  name: "",
  base_unit_name: "",
  wholesale_price: "",
  half_wholesale_price: "",
  retail_price: "",
  min_stock_level: "0",
  warehouse_id: "",
  units: [],
};

// Inline "home warehouse" picker for a product row — auto-saves on change.
function WarehouseCell({ product, warehouses, canManage, onChanged }) {
  const [saving, setSaving] = useState(false);
  const assign = async (e) => {
    const warehouse_id = e.target.value;
    if (!warehouse_id) return;
    setSaving(true);
    try {
      await api.patch(`/inventory/products/${product.id}`, {
        warehouse_id: Number(warehouse_id),
      });
      onChanged();
    } finally {
      setSaving(false);
    }
  };

  if (!canManage) {
    return warehouses.find((w) => w.id === product.warehouse_id)?.name ?? "—";
  }
  return (
    <select
      className="rounded border border-slate-300 px-2 py-1 text-sm"
      value={product.warehouse_id ?? ""}
      onChange={assign}
      disabled={saving}
    >
      <option value="" disabled>
        {product.warehouse_id ? "" : "⚠️ غير محدد"}
      </option>
      {warehouses.map((w) => (
        <option key={w.id} value={w.id}>
          {w.name}
        </option>
      ))}
    </select>
  );
}

export default function ProductsPage() {
  const { can } = useAuth();
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const { data, loading, error, reload } = useFetch(
    () => api.get("/inventory/products", { params: query ? { search: query } : {} }),
    [query]
  );
  const warehouses = useFetch(() => api.get("/inventory/warehouses"));

  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [formError, setFormError] = useState(null);
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  const setUnit = (index, key, value) => {
    const units = form.units.map((u, i) => (i === index ? { ...u, [key]: value } : u));
    setForm({ ...form, units });
  };

  const submit = async (event) => {
    event.preventDefault();
    setFormError(null);
    try {
      await api.post("/inventory/products", {
        ...form,
        units: form.units.filter((u) => u.name && u.factor),
      });
      setOpen(false);
      setForm(EMPTY_FORM);
      reload();
    } catch (err) {
      setFormError(apiMessage(err));
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-extrabold">الأصناف</h1>
        {can("products.manage") && <Button onClick={() => setOpen(true)}>+ صنف جديد</Button>}
      </div>

      <Card>
        <form
          className="mb-4 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            setQuery(search);
          }}
        >
          <Input
            placeholder="بحث بالاسم أو رمز الصنف..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <Button type="submit" variant="secondary">
            بحث
          </Button>
        </form>
        <Alert>{error}</Alert>
        {loading ? (
          <Loading />
        ) : (
          <Table
            columns={[
              { key: "sku", label: "الرمز" },
              { key: "name", label: "اسم الصنف" },
              { key: "base_unit_name", label: "الوحدة الأساسية" },
              {
                key: "units",
                label: "وحدات إضافية",
                render: (r) =>
                  r.units.length
                    ? r.units.map((u) => `${u.name} (${Number(u.factor)})`).join("، ")
                    : "—",
              },
              { key: "wholesale_price", label: "سعر الجملة", render: (r) => money(r.wholesale_price) },
              { key: "half_wholesale_price", label: "نصف الجملة", render: (r) => money(r.half_wholesale_price) },
              { key: "retail_price", label: "التجزئة", render: (r) => money(r.retail_price) },
              {
                key: "warehouse_id",
                label: "المستودع",
                render: (r) => (
                  <WarehouseCell
                    product={r}
                    warehouses={warehouses.data || []}
                    canManage={can("products.manage")}
                    onChanged={reload}
                  />
                ),
              },
              {
                key: "is_active",
                label: "الحالة",
                render: (r) =>
                  r.is_active ? <Badge tone="green">نشط</Badge> : <Badge tone="red">موقوف</Badge>,
              },
            ]}
            rows={data}
          />
        )}
      </Card>

      <Modal open={open} title="إضافة صنف جديد" onClose={() => setOpen(false)} wide>
        <form onSubmit={submit} className="space-y-4">
          <Alert>{formError}</Alert>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Input label="رمز الصنف (SKU)" value={form.sku} onChange={set("sku")} required autoFocus />
            <div className="sm:col-span-2">
              <Input label="اسم الصنف" value={form.name} onChange={set("name")} required />
            </div>
            <Input
              label="الوحدة الأساسية (مثال: حبة)"
              value={form.base_unit_name}
              onChange={set("base_unit_name")}
              required
            />
            <Input
              label="الحد الأدنى للمخزون"
              type="number"
              step="any"
              min="0"
              value={form.min_stock_level}
              onChange={set("min_stock_level")}
            />
            <Select
              label="المستودع (يُستخدم تلقائياً عند البيع)"
              value={form.warehouse_id}
              onChange={set("warehouse_id")}
              required
            >
              <option value="">— اختر المستودع —</option>
              {(warehouses.data || []).map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </Select>
          </div>
          <div className="grid grid-cols-3 gap-4">
            <Input label="سعر الجملة" type="number" step="0.01" min="0" value={form.wholesale_price} onChange={set("wholesale_price")} required />
            <Input label="سعر نصف الجملة" type="number" step="0.01" min="0" value={form.half_wholesale_price} onChange={set("half_wholesale_price")} required />
            <Input label="سعر التجزئة" type="number" step="0.01" min="0" value={form.retail_price} onChange={set("retail_price")} required />
          </div>

          <div>
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-bold text-slate-600">وحدات القياس الإضافية</span>
              <Button
                type="button"
                variant="secondary"
                onClick={() => setForm({ ...form, units: [...form.units, { name: "", factor: "" }] })}
              >
                + وحدة
              </Button>
            </div>
            {form.units.map((unit, index) => (
              <div key={index} className="mb-2 grid grid-cols-2 gap-4">
                <Input
                  placeholder="اسم الوحدة (مثال: كرتونة)"
                  value={unit.name}
                  onChange={(e) => setUnit(index, "name", e.target.value)}
                />
                <Input
                  placeholder="عدد الوحدات الأساسية فيها"
                  type="number"
                  step="any"
                  min="0.001"
                  value={unit.factor}
                  onChange={(e) => setUnit(index, "factor", e.target.value)}
                />
              </div>
            ))}
          </div>

          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setOpen(false)}>
              إلغاء
            </Button>
            <Button type="submit">حفظ الصنف</Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
