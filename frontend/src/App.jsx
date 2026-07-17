import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { Loading } from "./components/Ui";
import { AuthProvider, useAuth } from "./context/AuthContext";
import AccountingPage from "./pages/AccountingPage";
import AnalyticsPage from "./pages/AnalyticsPage";
import CustomersPage from "./pages/CustomersPage";
import DashboardPage from "./pages/DashboardPage";
import DeliveryPage from "./pages/DeliveryPage";
import LoginPage from "./pages/LoginPage";
import PrintInvoicePage from "./pages/PrintInvoicePage";
import PrintPickingPage from "./pages/PrintPickingPage";
import PrintPickupPrepPage from "./pages/PrintPickupPrepPage";
import ProductsPage from "./pages/ProductsPage";
import PurchasesPage from "./pages/PurchasesPage";
import SalesPage from "./pages/SalesPage";
import StockPage from "./pages/StockPage";
import SuppliersPage from "./pages/SuppliersPage";
import UsersPage from "./pages/UsersPage";
import WarehousesPage from "./pages/WarehousesPage";

function RequireAuth({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <Loading />;
  return user ? children : <Navigate to="/login" replace />;
}

function RequirePerm({ perm, children }) {
  const { can } = useAuth();
  return can(perm) ? children : <Navigate to="/" replace />;
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/print/invoice/:invoiceId"
            element={
              <RequireAuth>
                <PrintInvoicePage />
              </RequireAuth>
            }
          />
          <Route
            path="/print/picking/:tripId"
            element={
              <RequireAuth>
                <PrintPickingPage />
              </RequireAuth>
            }
          />
          <Route
            path="/print/pickup/:invoiceId"
            element={
              <RequireAuth>
                <PrintPickupPrepPage />
              </RequireAuth>
            }
          />
          <Route
            element={
              <RequireAuth>
                <Layout />
              </RequireAuth>
            }
          >
            <Route path="/" element={<DashboardPage />} />
            <Route path="/products" element={<ProductsPage />} />
            <Route path="/warehouses" element={<WarehousesPage />} />
            <Route path="/stock" element={<StockPage />} />
            <Route path="/customers" element={<CustomersPage />} />
            <Route path="/sales" element={<SalesPage />} />
            <Route path="/delivery" element={<DeliveryPage />} />
            <Route path="/suppliers" element={<SuppliersPage />} />
            <Route path="/purchases" element={<PurchasesPage />} />
            <Route
              path="/accounting"
              element={
                <RequirePerm perm="accounting.view">
                  <AccountingPage />
                </RequirePerm>
              }
            />
            <Route
              path="/analytics"
              element={
                <RequirePerm perm="analytics.view">
                  <AnalyticsPage />
                </RequirePerm>
              }
            />
            <Route
              path="/users"
              element={
                <RequirePerm perm="users.manage">
                  <UsersPage />
                </RequirePerm>
              }
            />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
