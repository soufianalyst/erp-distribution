// HTTP client for the customer portal.
//
// A separate instance from the staff client, and separate localStorage keys, for a
// reason that bites immediately otherwise: both apps are served from one origin, so
// a shop owner signing in on the same browser an employee uses would overwrite
// `access_token` and quietly log the employee out — or worse, send a customer's
// token to a staff endpoint, where the realm check rejects it and the shared
// refresh interceptor bounces everyone to /login.
//
// The refresh path is likewise the portal's own: a customer's refresh token is
// minted in the customer realm and `/auth/refresh` would refuse it.
import axios from "axios";

const ACCESS_KEY = "portal_access_token";
const REFRESH_KEY = "portal_refresh_token";

export const portalTokens = {
  get access() {
    return localStorage.getItem(ACCESS_KEY);
  },
  save(data) {
    localStorage.setItem(ACCESS_KEY, data.access_token);
    localStorage.setItem(REFRESH_KEY, data.refresh_token);
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
  },
};

const portalApi = axios.create({
  baseURL: `${import.meta.env.VITE_API_URL || ""}/api/v1`,
});

portalApi.interceptors.request.use((config) => {
  const token = portalTokens.access;
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

let refreshPromise = null;

portalApi.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config;
    const refreshToken = localStorage.getItem(REFRESH_KEY);
    if (error.response?.status === 401 && !original._retry && refreshToken) {
      original._retry = true;
      try {
        refreshPromise =
          refreshPromise ||
          axios.post(
            `${import.meta.env.VITE_API_URL || ""}/api/v1/portal/auth/refresh`,
            { refresh_token: refreshToken }
          );
        const { data } = await refreshPromise;
        refreshPromise = null;
        portalTokens.save(data.data);
        original.headers.Authorization = `Bearer ${data.data.access_token}`;
        return portalApi(original);
      } catch {
        refreshPromise = null;
        portalTokens.clear();
        window.location.href = "/portal/login";
      }
    }
    return Promise.reject(error);
  }
);

// The API answers in Arabic already, so the message is shown as-is rather than
// translated in the UI — one wording, from one place.
export const portalMessage = (error) =>
  error?.response?.data?.message || "تعذّر إتمام العملية، حاول مرة أخرى.";

export default portalApi;
