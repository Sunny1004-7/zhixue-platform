import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { AuthProvider } from "./AuthContext";
import { RuntimeProvider } from "./RuntimeContext";
import { DialogProvider } from "./components/Dialogs";
import { api } from "./api";
import "./styles.css";
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <RuntimeProvider api={api}>
        <AuthProvider>
          <DialogProvider>
            <App />
          </DialogProvider>
        </AuthProvider>
      </RuntimeProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
