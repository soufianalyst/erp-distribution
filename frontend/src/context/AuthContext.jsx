import { createContext, useContext, useEffect, useState } from "react";
import api from "../services/api";

const AuthContext = createContext(null);

export const ROLE_LABELS = {
  admin: "مدير النظام",
  storekeeper: "أمين المستودع",
  sales: "مندوب مبيعات",
  accountant: "محاسب",
  driver: "سائق توصيل",
  cashier: "أمين الصندوق",
};

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Restore the session on page load if a token is still stored.
    const bootstrap = async () => {
      if (!localStorage.getItem("access_token")) {
        setLoading(false);
        return;
      }
      try {
        const { data } = await api.get("/auth/me");
        setUser(data.data);
      } catch {
        localStorage.removeItem("access_token");
        localStorage.removeItem("refresh_token");
      } finally {
        setLoading(false);
      }
    };
    bootstrap();
  }, []);

  const login = async (username, password) => {
    const { data } = await api.post("/auth/login", { username, password });
    localStorage.setItem("access_token", data.data.access_token);
    localStorage.setItem("refresh_token", data.data.refresh_token);
    setUser(data.data.user);
    return data.data.user;
  };

  const logout = () => {
    localStorage.removeItem("access_token");
    localStorage.removeItem("refresh_token");
    setUser(null);
  };

  const hasRole = (...roles) => user && roles.includes(user.role);

  // Granular check against the effective permissions resolved by the backend.
  const can = (...permissions) =>
    !!user && permissions.every((p) => user.effective_permissions?.includes(p));

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, hasRole, can }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
