import "../styles/kronos/theme";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ProcessOSWorkbench } from "./ProcessOSWorkbench";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ProcessOSWorkbench />
  </StrictMode>,
);