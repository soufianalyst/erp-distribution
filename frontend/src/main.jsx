import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

// Offline shell for the salesman field app. Production only — a cached shell
// would fight Vite's hot reload in development.
if ("serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/service-worker.js").catch(() => {
      // Not fatal: without it the app simply needs a connection to open.
    });
  });
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
