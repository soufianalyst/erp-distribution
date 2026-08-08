// Who the portal thinks is signed in.
//
// Kept apart from the staff `AuthContext` for the same reason the tokens are: the
// two are different kinds of principal, and one context serving both would sooner
// or later hand a customer object to a screen expecting an employee.
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import portalApi, { portalTokens } from "../services/portalApi";

const PortalAuthContext = createContext(null);

export function PortalAuthProvider({ children }) {
  const [customer, setCustomer] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!portalTokens.access) {
      setCustomer(null);
      setLoading(false);
      return;
    }
    try {
      const { data } = await portalApi.get("/portal/me");
      setCustomer(data.data);
    } catch {
      portalTokens.clear();
      setCustomer(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const login = async (loginId, password) => {
    const { data } = await portalApi.post("/portal/auth/login", {
      login_id: loginId,
      password,
    });
    portalTokens.save(data.data);
    setCustomer(data.data.customer);
    return data.data.customer;
  };

  const logout = () => {
    portalTokens.clear();
    setCustomer(null);
  };

  return (
    <PortalAuthContext.Provider
      value={{ customer, loading, login, logout, refresh: load }}
    >
      {children}
    </PortalAuthContext.Provider>
  );
}

export const usePortalAuth = () => useContext(PortalAuthContext);
