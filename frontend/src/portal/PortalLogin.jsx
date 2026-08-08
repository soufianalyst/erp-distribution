// Signing a shop in, and making them replace the password we read out to them.
import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { Alert, Button, Input } from "../components/Ui";
import { usePortalAuth } from "../context/PortalAuthContext";
import portalApi, { portalMessage } from "../services/portalApi";

function Frame({ title, subtitle, children }) {
  return (
    <div
      dir="rtl"
      className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-10 dark:bg-slate-900"
    >
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100">
            {title}
          </h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{subtitle}</p>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-700 dark:bg-slate-800">
          {children}
        </div>
      </div>
    </div>
  );
}

export function PortalLogin() {
  const { customer, login } = usePortalAuth();
  const [loginId, setLoginId] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  if (customer) return <Navigate to="/portal" replace />;

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(loginId.trim(), password);
    } catch (err) {
      // The server answers every failure identically on purpose — unknown id,
      // wrong password, suspended account — so this shows whatever it said
      // rather than guessing at a more specific reason.
      setError(portalMessage(err));
      setBusy(false);
    }
  };

  return (
    <Frame title="بوابة العملاء" subtitle="ادخل لمتابعة حسابك وإرسال طلباتك">
      <form onSubmit={submit} className="space-y-4">
        <Input
          label="رقم الجوال أو البريد"
          value={loginId}
          onChange={(e) => setLoginId(e.target.value)}
          required
          autoFocus
          autoComplete="username"
          inputMode="email"
        />
        <Input
          label="كلمة المرور"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          autoComplete="current-password"
        />
        <Alert>{error}</Alert>
        <Button type="submit" className="w-full" disabled={busy}>
          {busy ? "جارٍ الدخول…" : "دخول"}
        </Button>
        <p className="text-center text-xs text-slate-500 dark:text-slate-400">
          لا تملك حساباً؟ تواصل مع الشركة لفتح حساب لك.
        </p>
      </form>
    </Frame>
  );
}

export function PortalChangePassword() {
  const { customer, refresh, logout } = usePortalAuth();
  const navigate = useNavigate();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  if (!customer) return <Navigate to="/portal/login" replace />;

  const submit = async (event) => {
    event.preventDefault();
    // Caught here rather than at the server: the mismatch is between two boxes on
    // this screen, and a round trip would tell them nothing extra.
    if (next !== confirm) {
      setError("كلمتا المرور غير متطابقتين.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await portalApi.post("/portal/auth/change-password", {
        current_password: current,
        new_password: next,
      });
      await refresh();
      navigate("/portal", { replace: true });
    } catch (err) {
      setError(portalMessage(err));
      setBusy(false);
    }
  };

  return (
    <Frame
      title="اختر كلمة مرور جديدة"
      subtitle="كلمة المرور التي سلّمتك إياها الشركة مؤقتة"
    >
      <form onSubmit={submit} className="space-y-4">
        <Input
          label="كلمة المرور المؤقتة"
          type="password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
          required
          autoFocus
          autoComplete="current-password"
        />
        <Input
          label="كلمة المرور الجديدة"
          type="password"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          required
          minLength={8}
          autoComplete="new-password"
        />
        <Input
          label="تأكيد كلمة المرور الجديدة"
          type="password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          required
          minLength={8}
          autoComplete="new-password"
        />
        <Alert>{error}</Alert>
        <Button type="submit" className="w-full" disabled={busy}>
          {busy ? "جارٍ الحفظ…" : "حفظ ومتابعة"}
        </Button>
        <button
          type="button"
          onClick={logout}
          className="w-full text-center text-xs font-bold text-slate-500 dark:text-slate-400"
        >
          خروج
        </button>
      </form>
    </Frame>
  );
}
