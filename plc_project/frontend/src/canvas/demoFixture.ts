import type { PlcJobDetail } from "../../api";
import type { KnowledgeCanvasData } from "../../KnowledgeCanvas";

/** Local-only canvas when `?canvasDemo=1` — does not touch export / SCL pipelines. */
export function demoKnowledgeCanvas(): KnowledgeCanvasData {
  return {
    nodes: [
      {
        id: "plc_b_demo_Main",
        label: "Main",
        summary: "OB1 扫描入口：调用电机启停与互锁。",
        kind: "plc_ob",
        x: 220,
        y: 160,
        export_status: "exported",
        source: { type: "plc", block_name: "Main", block_type: "OB", project: "Demo" },
      },
      {
        id: "plc_b_demo_FB_Motor",
        label: "FB_Motor",
        summary: "电机自锁启停：Start 置位、Stop 复位，写 Q 线圈。",
        kind: "plc_block",
        x: 420,
        y: 220,
        export_status: "exported",
        hub: true,
        source: { type: "plc", block_name: "FB_Motor", block_type: "FB", project: "Demo" },
      },
      {
        id: "plc_b_demo_DB_MotorInst",
        label: "DB_MotorInst",
        summary: "FB_Motor 实例数据。",
        kind: "plc_instance",
        x: 620,
        y: 160,
        export_status: "pending",
        source: {
          type: "plc",
          block_name: "DB_MotorInst",
          block_type: "DB",
          instance_of: "FB_Motor",
          entity_kind: "instance",
          project: "Demo",
        },
      },
      {
        id: "plc_b_demo_StartBtn",
        label: "StartBtn",
        summary: "READS · %I0.0 · 现场启动按钮",
        kind: "plc_tag",
        x: 420,
        y: 360,
        export_status: "unknown",
        source: { type: "plc", quote: "StartBtn", project: "Demo" },
      },
    ],
    edges: [
      { id: "e1", source: "plc_b_demo_Main", target: "plc_b_demo_FB_Motor", label: "CALLS" },
      {
        id: "e2",
        source: "plc_b_demo_FB_Motor",
        target: "plc_b_demo_DB_MotorInst",
        label: "INSTANCE_OF",
      },
    ],
  };
}

export function demoPlcJob(): PlcJobDetail {
  return {
    id: "demo-canvas",
    status: "ready",
    source_type: "demo",
    project_name: "Demo",
    export_ready: true,
    blocks: [
      {
        name: "Main",
        type: "OB",
        comment: "OB1 扫描入口",
        networks: 2,
        inputs: [],
        outputs: [],
      },
      {
        name: "FB_Motor",
        type: "FB",
        comment: "电机自锁启停",
        networks: 3,
        inputs: ["Start", "Stop"],
        outputs: ["Q_Motor"],
      },
      {
        name: "DB_MotorInst",
        type: "DB",
        instance_of: "FB_Motor",
        comment: "实例 DB",
        interface_only: true,
      },
    ],
    knowledge_graph: {
      nodes: [
        { id: "Block::FB_Motor", type: "Block", props: { name: "FB_Motor" } },
        { id: "Tag::StartBtn", type: "Tag", props: { name: "StartBtn", address: "%I0.0" } },
        { id: "Tag::Q_Motor", type: "Tag", props: { name: "Q_Motor", address: "%Q0.0" } },
      ],
      edges: [
        { source: "Block::FB_Motor", target: "Tag::StartBtn", type: "READS" },
        { source: "Block::FB_Motor", target: "Tag::Q_Motor", type: "WRITES" },
      ],
    },
    chat: [
      {
        role: "assistant",
        content: "FB_Motor 在 Network 1 用 Start 置位自锁。",
        block_name: "FB_Motor",
        citations: [
          {
            block: "FB_Motor",
            network: "Network 1",
            locator: "Network 1 / line 2",
            snippet: "Start AND NOT Stop => Q_Motor",
            source_status: "exported",
          },
        ],
      },
    ],
  };
}
