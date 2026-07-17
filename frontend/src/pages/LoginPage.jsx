import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Alert, Button, Input } from "../components/Ui";
import { useAuth } from "../context/AuthContext";
import { apiMessage } from "../services/api";

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(username, password);
      navigate("/", { replace: true });
    } catch (err) {
      setError(apiMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-900 p-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-2xl bg-white p-8 shadow-2xl">
        <h1 className="text-center text-2xl font-extrabold text-slate-800">
          نظام إدارة التوزيع
        </h1>
        <p className="mb-6 mt-1 text-center text-sm text-slate-500">
          بيع وتوزيع المواد الغذائية بالجملة
        </p>
        <Alert>{error}</Alert>
        <div className="space-y-4">
          <Input
            label="اسم المستخدم"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoFocus
            required
          />
          <Input
            label="كلمة المرور"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          <Button type="submit" disabled={busy} className="w-full">
            {busy ? "جارٍ الدخول..." : "تسجيل الدخول"}
          </Button>
        </div>
      </form>
    </div>
  );
}
