import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Input,
  Modal,
  PaginatedTable,
  money,
} from "../components/Ui";
import { useAuth } from "../context/AuthContext";
import useFetch from "../hooks/useFetch";
import api, { apiMessage } from "../services/api";

const EMPTY_FORM = { name: "", rate: "0.16", accounting_code: "2020", is_active: true };

export default function TaxTypesPage() {
  const { can } = useAuth();
  const canManage = can("accounting.manual_entry");

  const { data, loading, error, reload } = useFetch(() => api.get("/tax-types/?active_only=false"));
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [editingId, setEditingId] = useState(null);
  const [formError, setFormError] = useState(null);
  const [saving, setSaving] = useState(false);

  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  const openCreate = () => {
    setForm(EMPTY_FORM);
    setEditingId(null);
    setFormError(null);
    setOpen(true);
  };

  const openEdit = (tt) => {
    setForm({ name: tt.name, rate: String(tt.rate), accounting_code: tt.accounting_code, is_active: tt.is_active });
    setEditingId(tt.id);
    setFormError(null);
    setOpen(true);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setFormError(null);
    setSaving(true);
    try {
      const payload = { ...form, rate: parseFloat(form.rate) };
      if (editingId) {
        await api.put(`/tax-types/${editingId}`, payload);
      } else {
        await api.post("/tax-types/", payload);
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

  const handleDelete = async (tt) => {
    if (!window.confirm(`هل أنت متأكد من حذف نوع الضريبة "${tt.name}"؟`)) return;
    try {
      await api.delete(`/tax-types/${tt.id}`);
      reload();
    } catch (err) {
      alert(apiMessage(err));
    }
  };

  const taxTypes = data || [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-extrabold">أنواع الضريبة</h1>
        {canManage && <Button onClick={openCreate}>+ نوع ضريبة جديد</Button>}
      </div>

      <Alert>{error}</Alert>

      <Card>
        <PaginatedTable
          columns={[
            { key: "id", label: "الرقم" },
            { key: "name", label: "الاسم" },
            {
              key: "rate",
              label: "النسبة",
              render: (r) => <Badge tone="blue">{(parseFloat(r.rate) * 100).toFixed(1)}%</Badge>,
            },
            { key: "accounting_code", label: "الحساب المحاسبي" },
            {
              key: "is_active",
              label: "الحالة",
              render: (r) => r.is_active ? <Badge tone="green">نشط</Badge> : <Badge tone="red">معطل</Badge>,
            },
            ...(canManage
              ? [
                  {
                    key: "actions",
                    label: "",
                    render: (r) => (
                      <div className="flex gap-1">
                        <Button variant="secondary" onClick={() => openEdit(r)}>تعديل</Button>
                        <Button variant="danger" onClick={() => handleDelete(r)}>حذف</Button>
                      </div>
                    ),
                  },
                ]
              : []),
          ]}
          rows={taxTypes}
          loading={loading}
          empty="لا توجد أنواع ضريبة."
          searchable
          searchPlaceholder="بحث بالاسم..."
          filterField="is_active"
          filterLabel="الحالة"
          filterOptions={[
            { value: "true", label: "نشط" },
            { value: "false", label: "معطل" },
          ]}
        />
      </Card>

      {/* Create / Edit Modal */}
      <Modal
        open={open}
        title={editingId ? "تعديل نوع الضريبة" : "إضافة نوع ضريبة جديد"}
        onClose={() => setOpen(false)}
      >
        <form onSubmit={handleSubmit} className="space-y-4">
          <Alert>{formError}</Alert>
          <Input label="الاسم" value={form.name} onChange={set("name")} required autoFocus />
          <div className="grid grid-cols-2 gap-4">
            <Input
              label="النسبة (0.16 = 16%)"
              type="number"
              step="0.0001"
              min="0"
              max="1"
              value={form.rate}
              onChange={set("rate")}
              required
            />
            <Input
              label="الحساب المحاسبي"
              value={form.accounting_code}
              onChange={set("accounting_code")}
              required
            />
          </div>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={form.is_active}
              onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
              className="rounded border-gray-300"
            />
            <span className="text-sm text-slate-700">نشط</span>
          </label>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setOpen(false)}>إلغاء</Button>
            <Button type="submit" disabled={saving}>
              {saving ? "جاري الحفظ..." : editingId ? "تحديث" : "حفظ"}
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
