import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Input,
  Loading,
  Modal,
  PaginatedTable,
  Select,
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
  units: [],
  default_warehouse_id: "",
};

export default function ProductsPage() {
  const { can } = useAuth();
  const canManage = can("products.manage");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const { data, loading, error, reload } = useFetch(
    () => api.get("/inventory/products", { params: query ? { search: query } : {} }),
    [query]
  );
  const warehouses = useFetch(() => api.get("/inventory/warehouses"));

  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [editingId, setEditingId] = useState(null);
  const [formError, setFormError] = useState(null);
  const [saving, setSaving] = useState(false);
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  const setUnit = (index, key, value) => {
    const units = form.units.map((u, i) => (i === index ? { ...u, [key]: value } : u));
    setForm({ ...form, units });
  };

  const openCreate = () => {
    setForm(EMPTY_FORM);
    setEditingId(null);
    setFormError(null);
    setOpen(true);
  };

  const openEdit = (p) => {
    setForm({
      sku: p.sku,
      name: p.name,
      base_unit_name: p.base_unit_name,
      wholesale_price: String(p.wholesale_price),
      half_wholesale_price: String(p.half_wholesale_price),
      retail_price: String(p.retail_price),
      min_stock_level: String(p.min_stock_level),
      default_warehouse_id: p.default_warehouse_id ? String(p.default_warehouse_id) : "",
      units: p.units.map((u) => ({ name: u.name, factor: String(u.factor) })),
    });
    setEditingId(p.id);
    setFormError(null);
    setOpen(true);
  };

  const submit = async (event) => {
    event.preventDefault();
    setFormError(null);
    setSaving(true);
    try {
      const payload = {
        ...form,
        units: form.units.filter((u) => u.name && u.factor),
        default_warehouse_id: form.default_warehouse_id ? parseInt(form.default_warehouse_id) : null,
      };
      if (editingId) {
        await api.patch(`/inventory/products/${editingId}`, payload);
      } else {
        await api.post("/inventory/products", payload);
      }
      setOpen(false);
      setEditingId(null);
      setForm(EMPTY_FORM);
      reload();
    } catch (err) {
      setFormError(apiMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (p) => {
    if (!window.confirm(`هل أنت متأكد من حذف الصنف "${p.name}"؟`)) return;
    try {
      await api.delete(`/inventory/products/${p.id}`);
      reload();
    } catch (err) {
      alert(apiMessage(err));
    }
  };

  const toggleActive = async (p) => {
    try {
      await api.patch(`/inventory/products/${p.id}`, { is_active: !p.is_active });
      reload();
    } catch (err) {
      alert(apiMessage(err));
    }
  };

  const products = data || [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-extrabold">الأصناف</h1>
        {canManage && <Button onClick={openCreate}>+ صنف جديد</Button>}
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
          <PaginatedTable
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
                key: "default_warehouse_id",
                label: "المستودع الافتراضي",
                render: (r) => {
                  if (!r.default_warehouse_id) return <span className="text-slate-400">—</span>;
                  const w = warehouses.data?.find((wh) => wh.id === r.default_warehouse_id);
                  return w ? <Badge tone="blue">{w.name}</Badge> : r.default_warehouse_id;
                },
              },
              {
                key: "is_active",
                label: "الحالة",
                render: (r) =>
                  r.is_active ? <Badge tone="green">نشط</Badge> : <Badge tone="red">موقوف</Badge>,
              },
              ...(canManage
                ? [
                    {
                      key: "actions",
                      label: "",
                      render: (r) => (
                        <div className="flex gap-1">
                          <Button variant="secondary" onClick={() => openEdit(r)}>تعديل</Button>
                          <Button
                            variant={r.is_active ? "danger" : "primary"}
                            onClick={() => toggleActive(r)}
                          >
                            {r.is_active ? "إيقاف" : "تفعيل"}
                          </Button>
                        </div>
                      ),
                    },
                  ]
                : []),
            ]}
            rows={products}
          />
        )}
      </Card>

      <Modal open={open} title={editingId ? "تعديل الصنف" : "إضافة صنف جديد"} onClose={() => setOpen(false)} wide>
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
              <div key={index} className="mb-2 grid grid-cols-3 gap-4">
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
                <Button
                  type="button"
                  variant="danger"
                  onClick={() => setForm({ ...form, units: form.units.filter((_, i) => i !== index) })}
                >
                  حذف
                </Button>
              </div>
            ))}
          </div>

          <Select
            label="المستودع الافتراضي"
            value={form.default_warehouse_id}
            onChange={set("default_warehouse_id")}
          >
            <option value="">— بدون مستودع —</option>
            {warehouses.data?.map((w) => (
              <option key={w.id} value={w.id}>{w.name}</option>
            ))}
          </Select>

          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setOpen(false)}>
              إلغاء
            </Button>
            <Button type="submit" disabled={saving}>
              {saving ? "جاري الحفظ..." : editingId ? "تحديث" : "حفظ الصنف"}
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
