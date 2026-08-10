import React from "react";
import { createRoot } from "react-dom/client";
import "./globals.css";
import "./i18n";
import App from "./App";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
