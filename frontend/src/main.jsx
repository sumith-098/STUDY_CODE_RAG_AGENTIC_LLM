// App ka entry point: React ko #root me lagata hai aur CSS load karta hai.
import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./styles.css";   // saari styling ab sirf is ek file me (styles-extra.css / styles-code.css ki zaroorat nahi)

createRoot(document.getElementById("root")).render(<React.StrictMode><App /></React.StrictMode>);