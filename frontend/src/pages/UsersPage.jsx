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
} from "../components/Ui";
import { ROLE_LABELS } from "../context/AuthContext";
import useFetch from "../hooks/useFetch";
import api, { apiMessage } from "../services/api";

const EMPTY_FORM = { username: "", full_name: "", password: "", role: "sales" };

function PermissionsEditor({ user, catalog, onSaved, onClose }) {
  const [selected, setSelected] = useState(new Set(user.effective_permissions));
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const isAdmin = user.role === "admin";

  const toggle = (code) => {
    const next = new Set(selected);
    if (next.has(code)) next.delete(code);
    else next.add(code);
    setSelected(next);
  };

  const toggleGroup = (group) => {
    const codes = group.permissions.map((p) => p.code);
    const allOn = codes.every((c) => selected.has(c));
    const next = new Set(selected);
    codes.forEach((c) => (allOn ? next.delete(c) : next.add(c)));
    setSelected(next);
  };

  const save = async (reset = false) => {
    setError(null);
    setBusy(true);
    try {
      await api.patch(
        `/auth/users/${user.id}`,
        reset ? { reset_permissions: true } : { permissions: [...selected] }
      );
      onSaved();
    } catch (err) {
      setError(apiMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (isAdmin) {
    return (
      <div className="space-y-4">
        <Alert tone="success">
          مدير النظام يمتلك جميع الصلاحيات دائماً ولا يمكن تقييده، لضمان عدم قفل النظام.
        </Alert>
        <div className="flex justify-end">
          <Button variant="secondary" onClick={onClose}>
            إغلاق
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <Alert>{error}</Alert>
      <div className="flex items-center justify-between text-sm">
        <span className="font-bold text-slate-600">
          الدور الأساسي: {ROLE_LABELS[user.role]}
          {user.permissions !== null && (
            <Badge tone="amber"> صلاحيات مخصصة</Badge>
          )}
        </span>
        <span className="text-slate-500">{selected.size} صلاحية مفعّلة</span>
      </div>

      <div className="max-h-96 space-y-4 overflow-y-auto pe-1">
        {catalog.map((group) => (
          <div key={group.group} className="rounded-lg border border-slate-200 p-3">
            <button
              type="button"
              onClick={() => toggleGroup(group)}
              className="mb-2 text-sm font-extrabold text-emerald-800 hover:underline"
            >
              {group.group}
            </button>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {group.permissions.map((perm) => (
                <label
                  key={perm.code}
                  className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-slate-50"
                >
                  <input
                    type="checkbox"
                    checked={selected.has(perm.code)}
                    onChange={() => toggle(perm.code)}
                  />
                  <span className="font-bold">{perm.label}</span>
                </label>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="flex items-center justify-between border-t border-slate-200 pt-3">
        <Button variant="secondary" onClick={() => save(true)} disabled={busy}>
          إعادة التعيين حسب الدور
        </Button>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            إلغاء
          </Button>
          <Button onClick={() => save(false)} disabled={busy}>
            حفظ الصلاحيات
          </Button>
        </div>
      </div>
    </div>
  );
}

export default function UsersPage() {
  const { data, loading, error, reload } = useFetch(() => api.get("/auth/users"));
  const catalog = useFetch(() => api.get("/auth/permissions"));
  const [open, setOpen] = useState(false);
  const [permUser, setPermUser] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [formError, setFormError] = useState(null);
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  const submit = async (event) => {
    event.preventDefault();
    setFormError(null);
    try {
      await api.post("/auth/users", form);
      setOpen(false);
      setForm(EMPTY_FORM);
      reload();
    } catch (err) {
      setFormError(apiMessage(err));
    }
  };

  const toggleActive = async (user) => {
    try {
      await api.patch(`/auth/users/${user.id}`, { is_active: !user.is_active });
      reload();
    } catch (err) {
      alert(apiMessage(err));
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-extrabold">المستخدمون والصلاحيات</h1>
        <Button onClick={() => setOpen(true)}>+ مستخدم جديد</Button>
      </div>
      <Card>
        <Alert>{error}</Alert>
        {loading ? (
          <Loading />
        ) : (
          <Table
            columns={[
              { key: "username", label: "اسم المستخدم" },
              { key: "full_name", label: "الاسم الكامل" },
              {
                key: "role",
                label: "الدور",
                render: (r) => <Badge tone="blue">{ROLE_LABELS[r.role]}</Badge>,
              },
              {
                key: "permissions",
                label: "الصلاحيات",
                render: (r) =>
                  r.role === "admin" ? (
                    <Badge tone="green">كاملة</Badge>
                  ) : r.permissions !== null ? (
                    <Badge tone="amber">مخصصة ({r.effective_permissions.length})</Badge>
                  ) : (
                    <Badge>حسب الدور ({r.effective_permissions.length})</Badge>
                  ),
              },
              {
                key: "is_active",
                label: "الحالة",
                render: (r) =>
                  r.is_active ? <Badge tone="green">نشط</Badge> : <Badge tone="red">معطل</Badge>,
              },
              {
                key: "actions",
                label: "",
                render: (r) => (
                  <div className="flex gap-2">
                    <Button variant="secondary" onClick={() => setPermUser(r)}>
                      🔐 الصلاحيات
                    </Button>
                    <Button
                      variant={r.is_active ? "danger" : "secondary"}
                      onClick={() => toggleActive(r)}
                    >
                      {r.is_active ? "تعطيل" : "تفعيل"}
                    </Button>
                  </div>
                ),
              },
            ]}
            rows={data}
          />
        )}
      </Card>

      <Modal open={open} title="إضافة مستخدم جديد" onClose={() => setOpen(false)}>
        <form onSubmit={submit} className="space-y-4">
          <Alert>{formError}</Alert>
          <Input label="اسم المستخدم (أحرف إنجليزية)" value={form.username} onChange={set("username")} required autoFocus />
          <Input label="الاسم الكامل" value={form.full_name} onChange={set("full_name")} required />
          <Input label="كلمة المرور (8 أحرف على الأقل)" type="password" value={form.password} onChange={set("password")} required minLength={8} />
          <Select label="الدور (قالب الصلاحيات الافتراضي)" value={form.role} onChange={set("role")}>
            <option value="sales">مندوب مبيعات</option>
            <option value="storekeeper">أمين مستودع</option>
            <option value="driver">سائق توصيل</option>
            <option value="cashier">أمين الصندوق</option>
            <option value="accountant">محاسب</option>
            <option value="admin">مدير النظام</option>
          </Select>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setOpen(false)}>
              إلغاء
            </Button>
            <Button type="submit">إنشاء المستخدم</Button>
          </div>
        </form>
      </Modal>

      <Modal
        open={!!permUser}
        title={permUser ? `صلاحيات — ${permUser.full_name}` : ""}
        onClose={() => setPermUser(null)}
        wide
      >
        {permUser && catalog.data && (
          <PermissionsEditor
            user={permUser}
            catalog={catalog.data}
            onClose={() => setPermUser(null)}
            onSaved={() => {
              setPermUser(null);
              reload();
            }}
          />
        )}
      </Modal>
    </div>
  );
}
