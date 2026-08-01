import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { Loading } from "./components/Ui";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { ThemeProvider } from "./context/ThemeContext";
import AccountingPage from "./pages/AccountingPage";
import AnalyticsPage from "./pages/AnalyticsPage";
import AuditLogPage from "./pages/AuditLogPage";
import BarcodeScanPage from "./pages/BarcodeScanPage";
import CashierPage from "./pages/CashierPage";
import CustomersPage from "./pages/CustomersPage";
import DashboardPage from "./pages/DashboardPage";
import DeliveryPage from "./pages/DeliveryPage";
import ExpensesPage from "./pages/ExpensesPage";
import FieldPage from "./pages/FieldPage";
import LoginPage from "./pages/LoginPage";
import PrintInvoicePage from "./pages/PrintInvoicePage";
import PrintPickingPage from "./pages/PrintPickingPage";
import PrintAdjustmentPage from "./pages/PrintAdjustmentPage";
import PrintDamageReportPage from "./pages/PrintDamageReportPage";
import PrintDiscountReportPage from "./pages/PrintDiscountReportPage";
import PrintPickupPrepPage from "./pages/PrintPickupPrepPage";
import PrintStocktakePage from "./pages/PrintStocktakePage";
import ProductsPage from "./pages/ProductsPage";
import PurchasesPage from "./pages/PurchasesPage";
import SalesPage from "./pages/SalesPage";
import SettingsPage from "./pages/SettingsPage";
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
      <ThemeProvider>
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
              path="/print/adjustment/:adjustmentId"
              element={
                <RequireAuth>
                  <PrintAdjustmentPage />
                </RequireAuth>
              }
            />
            <Route
              path="/print/stocktake/:stocktakeId"
              element={
                <RequireAuth>
                  <PrintStocktakePage />
                </RequireAuth>
              }
            />
            <Route
              path="/print/damage-report"
              element={
                <RequireAuth>
                  <PrintDamageReportPage />
                </RequireAuth>
              }
            />
            <Route
              path="/print/discount-report"
              element={
                <RequireAuth>
                  <PrintDiscountReportPage />
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
              <Route
                path="/barcode-scan"
                element={
                  <RequirePerm perm="products.view">
                    <BarcodeScanPage />
                  </RequirePerm>
                }
              />
              <Route path="/warehouses" element={<WarehousesPage />} />
              <Route path="/stock" element={<StockPage />} />
              <Route path="/customers" element={<CustomersPage />} />
              <Route path="/sales" element={<SalesPage />} />
              <Route
                path="/cashier"
                element={
                  <RequirePerm perm="cashier.view">
                    <CashierPage />
                  </RequirePerm>
                }
              />
              <Route path="/delivery" element={<DeliveryPage />} />
              <Route path="/suppliers" element={<SuppliersPage />} />
              <Route path="/purchases" element={<PurchasesPage />} />
              <Route
                path="/expenses"
                element={
                  <RequirePerm perm="expenses.view">
                    <ExpensesPage />
                  </RequirePerm>
                }
              />
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
                path="/settings"
                element={
                  <RequirePerm perm="settings.view">
                    <SettingsPage />
                  </RequirePerm>
                }
              />
              <Route
                path="/field"
                element={
                  <RequirePerm perm="sales.field_sync">
                    <FieldPage />
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
              <Route
                path="/audit"
                element={
                  <RequirePerm perm="audit.view">
                    <AuditLogPage />
                  </RequirePerm>
                }
              />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AuthProvider>
      </ThemeProvider>
    </BrowserRouter>
  );
}
