import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";
import { ensureResizeObserver } from "./resizeObserverShim";

async function bootstrap() {
  // 嵌入式浏览器 ResizeObserver 失效时启用轮询兜底（约 60ms 探针）
  await ensureResizeObserver();

  const rootElement = document.getElementById("root");
  if (rootElement) {
    ReactDOM.createRoot(rootElement).render(
      <React.StrictMode>
        <App />
      </React.StrictMode>
    );
  }
}

void bootstrap();
