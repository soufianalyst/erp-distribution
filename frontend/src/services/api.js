import axios from "axios";

// Central Axios client: attaches the JWT and refreshes it transparently on expiry.
const api = axios.create({
  baseURL: `${import.meta.env.VITE_API_URL || ""}/api/v1`,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

let refreshPromise = null;

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config;
    const refreshToken = localStorage.getItem("refresh_token");
    if (error.response?.status === 401 && !original._retry && refreshToken) {
      original._retry = true;
      try {
          refreshPromise =
          refreshPromise ||
          axios.post(`${import.meta.env.VITE_API_URL || ""}/api/v1/auth/refresh`, { refresh_token: refreshToken });
        const { data } = await refreshPromise;
        refreshPromise = null;
        localStorage.setItem("access_token", data.data.access_token);
        localStorage.setItem("refresh_token", data.data.refresh_token);
        original.headers.Authorization = `Bearer ${data.data.access_token}`;
        return api(original);
      } catch {
        refreshPromise = null;
        localStorage.removeItem("access_token");
        localStorage.removeItem("refresh_token");
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

// Extract the backend's Arabic message from the unified envelope.
export const apiMessage = (error) =>
  error?.response?.data?.message || "حدث خطأ غير متوقع، يرجى المحاولة مرة أخرى.";

export default api;
