import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  CancelButton,
  Card,
  Input,
  Loading,
  Modal,
  Select,
  Table,
} from "../components/Ui";
import { useAuth } from "../context/AuthContext";
import useFetch from "../hooks/useFetch";
import api, { apiMessage } from "../services/api";

const EMPTY = { name: "", location: "", is_vehicle: false, assigned_to_id: "" };

/**
 * Create or edit a warehouse. A warehouse marked as a vehicle is a salesman's
 * van: stock loaded onto it is sold from the field app, so it needs a driver.
 */
function WarehouseForm({ warehouse, salesmen, onSaved, onClose }) {
  const editing = !!warehouse;
  const [form, setForm] = useState(
    editing
      ? {
          name: warehouse.name,
          location: warehouse.location ?? "",
          is_vehicle: warehouse.is_vehicle,
          assigned_to_id: warehouse.assigned_to_id ?? "",
        }
      : EMPTY
  );
  const [error, setError] = useState(null);
  const set = (key) => (e) =>
    setForm({
      ...form,
      [key]: e.target.type === "checkbox" ? e.target.checked : e.target.value,
    });

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    const payload = {
      name: form.name,
      location: form.location || null,
      is_vehicle: form.is_vehicle,
      // Null unassigns; a fixed warehouse never carries a driver.
      assigned_to_id:
        form.is_vehicle && form.assigned_to_id ? Number(form.assigned_to_id) : null,
    };
    try {
      const { data } = editing
        ? await api.patch(`/inventory/warehouses/${warehouse.id}`, payload)
        : await api.post("/inventory/warehouses", payload);
      onSaved(data.data);
    } catch (err) {
      setError(apiMessage(err));
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <Alert>{error}</Alert>
      <Input label="اسم المستودع" value={form.name} onChange={set("name")} required autoFocus />
      <Input label="الموقع (اختياري)" value={form.location} onChange={set("location")} />

      <label className="flex items-start gap-2 text-sm font-bold text-slate-700 dark:text-slate-300">
        <input
          type="checkbox"
          className="mt-1"
          checked={form.is_vehicle}
          onChange={set("is_vehicle")}
        />
        <span>
          مركبة (سيارة مندوب)
          <span className="block text-xs font-normal text-slate-500 dark:text-slate-400">
            تُحمّل عليها البضاعة صباحاً بتحويل عادي، ويبيع منها المندوب من تطبيق
            الجولة، وتُسوّى بالجرد آخر اليوم.
          </span>
        </span>
      </label>

      {form.is_vehicle && (
        <Select
          label="المندوب المسؤول عن المركبة"
          value={form.assigned_to_id}
          onChange={set("assigned_to_id")}
        >
          <option value="">— بدون إسناد —</option>
          {salesmen.map((s) => (
            <option key={s.id} value={s.id}>
              {s.full_name}
            </option>
          ))}
        </Select>
      )}
      {form.is_vehicle && salesmen.length === 0 && (
        <Alert>
          لا يوجد موظفو مبيعات نشطون لإسناد المركبة إليهم؛ أضف مندوباً من صفحة
          المستخدمين أولاً.
        </Alert>
      )}

      <div className="flex justify-end gap-2">
        <CancelButton onClose={onClose} />
        <Button type="submit">{editing ? "حفظ التعديلات" : "حفظ"}</Button>
      </div>
    </form>
  );
}

export default function WarehousesPage() {
  const { can } = useAuth();
  const canManage = can("warehouses.manage");
  const warehouses = useFetch(() => api.get("/inventory/warehouses"));
  // Only a salesman may drive a van, so the picker offers exactly those.
  const users = useFetch(() => (canManage ? api.get("/auth/users") : Promise.resolve({ data: { data: [] } })));
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState(null);
  const [notice, setNotice] = useState(null);

  const salesmen = (users.data ?? []).filter((u) => u.role === "sales" && u.is_active);

  if (warehouses.loading || users.loading) return <Loading />;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-extrabold">المستودعات والمركبات</h1>
        {canManage && <Button onClick={() => setCreating(true)}>+ مستودع جديد</Button>}
      </div>
      <Alert tone="success">{notice}</Alert>
      <Card>
        <Alert>{warehouses.error}</Alert>
        <Table
          columns={[
            { key: "id", label: "#" },
            { key: "name", label: "الاسم" },
            {
              key: "is_vehicle",
              label: "النوع",
              render: (r) =>
                r.is_vehicle ? <Badge tone="blue">مركبة</Badge> : <Badge tone="slate">مستودع</Badge>,
              sortValue: (r) => (r.is_vehicle ? 1 : 0),
            },
            {
              key: "assigned_to_name",
              label: "المندوب",
              // A van with nobody assigned cannot be sold from — worth flagging.
              render: (r) =>
                !r.is_vehicle ? (
                  "—"
                ) : r.assigned_to_name ? (
                  r.assigned_to_name
                ) : (
                  <Badge tone="amber">بدون إسناد</Badge>
                ),
              search: (r) => r.assigned_to_name ?? "",
            },
            { key: "location", label: "الموقع", render: (r) => r.location || "—" },
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
                    sortable: false,
                    render: (r) => (
                      <Button variant="secondary" onClick={() => setEditing(r)}>
                        ✏️ تعديل
                      </Button>
                    ),
                  },
                ]
              : []),
          ]}
          rows={warehouses.data}
        />
      </Card>

      <Modal open={creating} title="إضافة مستودع أو مركبة" onClose={() => setCreating(false)}>
        {creating && (
          <WarehouseForm
            salesmen={salesmen}
            onClose={() => setCreating(false)}
            onSaved={(saved) => {
              setCreating(false);
              setNotice(`تم إنشاء (${saved.name}).`);
              warehouses.reload();
            }}
          />
        )}
      </Modal>

      <Modal
        open={!!editing}
        title={editing ? `تعديل ${editing.name}` : ""}
        onClose={() => setEditing(null)}
      >
        {editing && (
          <WarehouseForm
            warehouse={editing}
            salesmen={salesmen}
            onClose={() => setEditing(null)}
            onSaved={(saved) => {
              setEditing(null);
              setNotice(`تم تحديث (${saved.name}).`);
              warehouses.reload();
            }}
          />
        )}
      </Modal>
    </div>
  );
}
