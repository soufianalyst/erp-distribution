// User accounts, roles and permissions.
//
// Roles are only templates: giving a user an explicit permission list overrides
// their role entirely, which is why a new permission added to a role does not
// reach users who already have their own list. The editor makes that explicit
// rather than hiding it.
//
// Salesmen also carry their commission rate here, used by the commission report.
import { useState } from "react";
import {
  CancelButton,
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
import { ROLE_LABELS, useAuth } from "../context/AuthContext";
import useFetch from "../hooks/useFetch";
import api, { apiMessage } from "../services/api";

const EMPTY_FORM = {
  username: "",
  full_name: "",
  password: "",
  role: "sales",
  commission_rate: "0",
};

// Inline commission-rate editor for a user row — auto-saves on blur.
/** Inline edit of a salesman's commission percentage, used by the commission report. */
function CommissionRateCell({ user, canManage, onChanged }) {
  const [value, setValue] = useState(user.commission_rate);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const save = async () => {
    if (value === user.commission_rate) return;
    setSaving(true);
    setError(null);
    try {
      await api.patch(`/auth/users/${user.id}`, { commission_rate: value || "0" });
      onChanged();
    } catch (err) {
      setError(apiMessage(err));
      setValue(user.commission_rate);
    } finally {
      setSaving(false);
    }
  };

  if (!canManage) return `${user.commission_rate}%`;
  return (
    <div>
      <div className="flex items-center gap-1">
        <input
          type="number"
          step="0.01"
          min="0"
          max="100"
          className="w-20 rounded border border-slate-300 dark:border-slate-600 px-2 py-1 text-sm"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onBlur={save}
          onKeyDown={(e) => e.key === "Enter" && e.target.blur()}
          disabled={saving}
        />
        <span className="text-xs text-slate-500 dark:text-slate-400">%</span>
      </div>
      {error && <div className="mt-1 text-xs text-red-600">{error}</div>}
    </div>
  );
}

/**
 * Per-user permission override.
 *
 * Saving an explicit list detaches the user from their role's defaults entirely
 * — so a permission added to the role later will not reach them. That is the
 * intended behaviour, but it surprises people, which is why the field app's
 * permission had to be granted by hand to an existing salesman.
 */
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
        <span className="font-bold text-slate-600 dark:text-slate-400">
          الدور الأساسي: {ROLE_LABELS[user.role]}
          {user.permissions !== null && (
            <Badge tone="amber"> صلاحيات مخصصة</Badge>
          )}
        </span>
        <span className="text-slate-500 dark:text-slate-400">{selected.size} صلاحية مفعّلة</span>
      </div>

      <div className="max-h-96 space-y-4 overflow-y-auto pe-1">
        {catalog.map((group) => (
          <div key={group.group} className="rounded-lg border border-slate-200 dark:border-slate-700 p-3">
            <button
              type="button"
              onClick={() => toggleGroup(group)}
              className="mb-2 text-sm font-extrabold text-emerald-800 dark:text-emerald-300 hover:underline"
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

      <div className="flex items-center justify-between border-t border-slate-200 dark:border-slate-700 pt-3">
        <Button variant="secondary" onClick={() => save(true)} disabled={busy}>
          إعادة التعيين حسب الدور
        </Button>
        <div className="flex flex-wrap gap-2">
          <CancelButton onClose={onClose} disabled={busy} />
          <Button onClick={() => save(false)} disabled={busy}>
            حفظ الصلاحيات
          </Button>
        </div>
      </div>
    </div>
  );
}


function PasswordDialog({ user, onClose, onDone }) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async (event) => {
    event.preventDefault();
    if (password !== confirm) {
      setError("كلمتا المرور غير متطابقتين.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.patch(`/auth/users/${user.id}`, { password });
      onDone(`تم تغيير كلمة مرور ${user.full_name}.`);
    } catch (err) {
      setError(apiMessage(err));
      setBusy(false);
    }
  };

  return (
    <Modal open title={`كلمة مرور جديدة — ${user.full_name}`} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <Input
          label="كلمة المرور الجديدة (8 أحرف على الأقل)"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          minLength={8}
          autoFocus
        />
        <Input
          label="تأكيد كلمة المرور"
          type="password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          required
          minLength={8}
        />
        <p className="text-sm text-slate-500 dark:text-slate-400">
          سلّم الموظف كلمة المرور بنفسك؛ لن تظهر في أي شاشة بعد الحفظ.
        </p>
        <Alert>{error}</Alert>
        <div className="flex justify-end gap-2">
          <CancelButton onClose={onClose} />
          <Button type="submit" disabled={busy}>
            {busy ? "جارٍ الحفظ…" : "حفظ"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export default function UsersPage() {
  const { can } = useAuth();
  const { data, loading, error, reload } = useFetch(() => api.get("/auth/users"));
  const catalog = useFetch(() => api.get("/auth/permissions"));
  const [open, setOpen] = useState(false);
  const [permUser, setPermUser] = useState(null);
  const [passwordUser, setPasswordUser] = useState(null);
  // Separate from useFetch's `error`, which reports the list failing to load.
  const [actionError, setActionError] = useState(null);
  const [notice, setNotice] = useState(null);
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
      setActionError(apiMessage(err));
    }
  };

  const removeUser = async (user) => {
    // Only accounts with no history can go, and the server decides that — this
    // confirmation says what will happen, not what the caller hopes will.
    if (
      !window.confirm(
        `حذف حساب «${user.full_name}» نهائياً؟\n\n` +
          "الحذف متاح فقط لحساب لم تُسجَّل عليه أي عملية. " +
          "إن كان له سجل، عطّله بدل حذفه."
      )
    )
      return;
    try {
      await api.delete(`/auth/users/${user.id}`);
      setNotice("تم حذف الحساب.");
      reload();
    } catch (err) {
      setActionError(apiMessage(err));
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-extrabold">المستخدمون والصلاحيات</h1>
        <Button onClick={() => setOpen(true)}>+ مستخدم جديد</Button>
      </div>
      <Card>
        <Alert>{error ?? actionError}</Alert>
        <Alert tone="success">{notice}</Alert>
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
                key: "commission_rate",
                label: "نسبة العمولة",
                render: (r) => (
                  <CommissionRateCell user={r} canManage={true} onChanged={reload} />
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
                  <div className="flex flex-wrap gap-2">
                    <Button variant="secondary" onClick={() => setPermUser(r)}>
                      🔐 الصلاحيات
                    </Button>
                    <Button variant="secondary" onClick={() => setPasswordUser(r)}>
                      🔑 كلمة المرور
                    </Button>
                    <Button
                      variant={r.is_active ? "danger" : "secondary"}
                      onClick={() => toggleActive(r)}
                    >
                      {r.is_active ? "تعطيل" : "تفعيل"}
                    </Button>
                    {can("users.delete") ? (
                      <Button variant="danger" onClick={() => removeUser(r)}>
                        حذف
                      </Button>
                    ) : null}
                  </div>
                ),
              },
            ]}
            rows={data}
          />
        )}
      </Card>

      {passwordUser ? (
        <PasswordDialog
          user={passwordUser}
          onClose={() => setPasswordUser(null)}
          onDone={(message) => {
            setPasswordUser(null);
            setNotice(message);
          }}
        />
      ) : null}

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
          <Input
            label="نسبة العمولة % (تُطبّق فقط على مندوبي المبيعات)"
            type="number"
            step="0.01"
            min="0"
            max="100"
            value={form.commission_rate}
            onChange={set("commission_rate")}
          />
          <div className="flex justify-end gap-2">
            <CancelButton onClose={() => setOpen(false)} />
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
