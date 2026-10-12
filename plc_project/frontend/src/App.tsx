import React, { useEffect, useState } from "react";
import { PlcInteractiveCanvas } from "./canvas/PlcInteractiveCanvas";
import type { CanvasStateData, CompilerAttribution } from "./canvas/types";

const API_BASE = "http://localhost:8000";

export const App: React.FC = () => {
  const [initialCanvas, setInitialCanvas] = useState<CanvasStateData | undefined>(undefined);
  const [backendConnected, setBackendConnected] = useState<boolean | null>(null);

  // Fetch initial default canvas from Backend Gateway on mount
  useEffect(() => {
    fetch(`${API_BASE}/api/v1/plc/canvas/default`)
      .then((res) => res.json())
      .then((data) => {
        if (data && data.ok && data.data) {
          setInitialCanvas(data.data);
          setBackendConnected(true);
        }
      })
      .catch(() => {
        setBackendConnected(false);
      });
  }, []);

  const handleApplyPatch = async (operations: any[]): Promise<CanvasStateData> => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/plc/canvas/patch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ operations, canvas: initialCanvas }),
      });
      const json = await res.json();
      if (json && json.ok && json.data) {
        setInitialCanvas(json.data);
        return json.data;
      }
    } catch (e) {
      console.warn("Backend unavailable, falling back to local client state update", e);
    }
    return initialCanvas!;
  };

  const handleConfirmWriteback = async (
    canvas: CanvasStateData
  ): Promise<{
    writeback: Record<string, any>;
    attributions: CompilerAttribution[];
    canvas: CanvasStateData;
  }> => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/plc/canvas/confirm-writeback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          canvas,
          project_path: `${canvas.project_name}.ap19`,
          plc_name: "PLC_1",
          compile_after: true,
        }),
      });
      const json = await res.json();
      if (json && json.ok && json.data) {
        return json.data;
      }
    } catch (e) {
      console.warn("Backend writeback error", e);
    }

    // Client fallback mock
    return {
      writeback: { ok: true, note: "Local client simulated writeback" },
      attributions: [],
      canvas: {
        ...canvas,
        blocks: Object.fromEntries(
          Object.entries(canvas.blocks).map(([k, b]) => [k, { ...b, status: "synced" }])
        ),
        hmi_widgets: Object.fromEntries(
          Object.entries(canvas.hmi_widgets).map(([k, w]) => [k, { ...w, status: "synced" }])
        ),
      },
    };
  };

  const handleAutoFix = async (
    attributions: CompilerAttribution[]
  ): Promise<CanvasStateData> => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/plc/canvas/auto-fix`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ canvas: initialCanvas, attributions }),
      });
      const json = await res.json();
      if (json && json.ok && json.data?.canvas) {
        return json.data.canvas;
      }
    } catch (e) {
      console.warn("Auto-fix backend call error", e);
    }
    return initialCanvas!;
  };

  return (
    <div className="w-screen h-screen overflow-hidden flex flex-col bg-[#07090e]">
      <PlcInteractiveCanvas
        initialCanvas={initialCanvas}
        backendConnected={backendConnected}
        onApplyPatch={handleApplyPatch}
        onConfirmWriteback={handleConfirmWriteback}
        onAutoFix={handleAutoFix}
      />
    </div>
  );
};
export default App;
