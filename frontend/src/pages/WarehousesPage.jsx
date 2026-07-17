import { useState } from "react";
import { Alert, Badge, Button, Card, Input, Loading, Modal, Table } from "../components/Ui";
import { useAuth } from "../context/AuthContext";
import useFetch from "../hooks/useFetch";
import api, { apiMessage } from "../services/api";

export default function WarehousesPage() {
  const { can } = useAuth();
  const { data, loading, error, reload } = useFetch(() => api.get("/inventory/warehouses"));
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", location: "" });
  const [formError, setFormError] = useState(null);

  const submit = async (event) => {
    event.preventDefault();
    setFormError(null);
    try {
      await api.post("/inventory/warehouses", form);
      setOpen(false);
      setForm({ name: "", location: "" });
      reload();
    } catch (err) {
      setFormError(apiMessage(err));
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-extrabold">المستودعات</h1>
        {can("warehouses.manage") && <Button onClick={() => setOpen(true)}>+ مستودع جديد</Button>}
      </div>
      <Card>
        <Alert>{error}</Alert>
        {loading ? (
          <Loading />
        ) : (
          <Table
            columns={[
              { key: "id", label: "#" },
              { key: "name", label: "اسم المستودع" },
              { key: "location", label: "الموقع", render: (r) => r.location || "—" },
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

      <Modal open={open} title="إضافة مستودع" onClose={() => setOpen(false)}>
        <form onSubmit={submit} className="space-y-4">
          <Alert>{formError}</Alert>
          <Input
            label="اسم المستودع"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            required
            autoFocus
          />
          <Input
            label="الموقع (اختياري)"
            value={form.location}
            onChange={(e) => setForm({ ...form, location: e.target.value })}
          />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setOpen(false)}>
              إلغاء
            </Button>
            <Button type="submit">حفظ</Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
