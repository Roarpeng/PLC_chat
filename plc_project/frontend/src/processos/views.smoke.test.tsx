import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import { ProcessOSWorkbench } from "./ProcessOSWorkbench";
import { Baselines } from "./Baselines";
import { CommissioningLedger } from "./CommissioningLedger";
import { DeploymentGateway } from "./DeploymentGateway";
import { FieldConsole } from "./FieldConsole";
import { ActorRoleWidget } from "./fieldui";
import { ImpactReportView } from "./ImpactPanel";
import { TelemetryPanel } from "./TelemetryPanel";
import { Traceability } from "./Traceability";
import type { ImpactReport } from "./types";

/* Node-environment render smoke (no jsdom): components must render to markup
   without throwing; useEffect data loading is intentionally skipped. */
const noop = () => { };
const nav = noop;

describe("field view render smoke", () => {
  it("FieldConsole renders the three entrances and the QR disclaimer", () => {
    const html = renderToString(<FieldConsole onBack={noop} onNav={nav} onOpenIncident={noop} />);
    expect(html).toContain("按工位找设备");
    expect(html).toContain("按报警找逻辑");
    expect(html).toContain("按变更单 / 项目找工程");
    expect(html).toContain("二维码只是入口，不是授权凭证");
  });

  it("CommissioningLedger renders banner, form fields and result options", () => {
    const html = renderToString(<CommissioningLedger onBack={noop} onNav={nav} />);
    expect(html).toContain("下载 TIA 工程 ≠ 将程序下载到现场 PLC");
    expect(html).toContain("artifact_sha256");
    expect(html).toContain("plc_checksum");
    expect(html).toContain("COMMISSIONED");
    expect(html).toContain("ROLLED_BACK");
  });

  it("Baselines renders B1/B2/B3, UNVERIFIED_ONLINE and verification options", () => {
    const html = renderToString(<Baselines onBack={noop} onNav={nav} />);
    expect(html).toContain("记录 B1");
    expect(html).toContain("记录 B2");
    expect(html).toContain("记录 B3");
    expect(html).toContain("UNVERIFIED_ONLINE");
    expect(html).toContain("FIELD_VERIFIED");
    expect(html).toContain("SELF_REPORTED");
  });

  it("DeploymentGateway states no one-click go-live and shows the gate form", () => {
    const html = renderToString(<DeploymentGateway onBack={noop} onNav={nav} />);
    expect(html).toContain("不存在一键上线");
    expect(html).toContain("online_compare");
    expect(html).toContain("retain_assessment");
    expect(html).toContain("rollback_plan");
    expect(html).toContain("second person");
  });

  it("TelemetryPanel keeps SIMULATED evidence framing visible", () => {
    const html = renderToString(<TelemetryPanel objectId="cm_clamp_a_001" />);
    expect(html).toContain("MANUAL_UPLOAD");
    expect(html).toContain("SIMULATED");
  });

  it("Traceability renders its header and handover hint", () => {
    const html = renderToString(<Traceability onBack={noop} onNav={nav} focusIncidentId="INC-1" />);
    expect(html).toContain("现场追溯");
    expect(html).toContain("选择一个问题单查看交接上下文");
  });

  it("ActorRoleWidget states demo identity pass-through", () => {
    const html = renderToString(<ActorRoleWidget />);
    expect(html).toContain("演示用身份传递 · 非生产认证");
  });

  it("ProcessOSWorkbench (launcher) exposes the field workbench entrance", () => {
    const html = renderToString(<ProcessOSWorkbench />);
    expect(html).toContain("现场工作台");
  });
});

describe("ImpactPanel report rendering", () => {
  const report: ImpactReport = {
    report_id: "imp_9", project_id: "P1", generated_at: "t",
    subject: { object_id: "cm_clamp_a_001", display_name: "夹紧气缸", reason: "超时 3s→5s" },
    affected: {
      units: [{ object_id: "u1", display_name: "U", kind: "af_unit" }],
      ems: [{ object_id: "e1", display_name: "E", kind: "af_em" }, { object_id: "e2", display_name: "E2", kind: "af_em" }],
      cms: [],
      steps: [{ object_id: "s1", display_name: "S", kind: "behavior_step" },
        { object_id: "s2", display_name: "S2", kind: "behavior_step" },
        { object_id: "s3", display_name: "S3", kind: "behavior_step" },
        { object_id: "s4", display_name: "S4", kind: "behavior_step" }],
    },
    callers: [],
    alarm_definitions: [{ definition_id: "alarm_clamp_timeout", code: "CM_MOTION_TIMEOUT", description: "x" }],
    io_db_interfaces: ["UNKNOWN"], hmi_messages: [],
    state_retention_risk: "UNKNOWN", online_load_impact: "UNKNOWN",
    regression_tests: [{ name: "extend_timeout", status: "UNKNOWN" }],
    deployment_notes: [],
    unknown_fields: ["io_bindings.Extended", "hmi.message_map"],
    blocked_high_risk_delivery: true,
  };

  it("renders explicit UNKNOWN badges for unknown fields and empty buckets", () => {
    const html = renderToString(<ImpactReportView report={report} />);
    expect(html).toContain("UNKNOWN");
    expect((html.match(/UNKNOWN/g) ?? []).length).toBeGreaterThanOrEqual(3); // CM count + 2 unknown fields + risk
    expect(html).toContain("CM_MOTION_TIMEOUT");
  });

  it("renders the blocked high-risk delivery banner", () => {
    const html = renderToString(<ImpactReportView report={report} />);
    expect(html).toContain("高风险交付被阻断");
  });

  it("does not claim delivery approval when not blocked", () => {
    const html = renderToString(<ImpactReportView report={{ ...report, blocked_high_risk_delivery: false, unknown_fields: [], state_retention_risk: "NONE", online_load_impact: "NONE" }} />);
    expect(html).not.toContain("高风险交付被阻断");
    expect(html).toContain("无 — 影响面已全部映射");
  });
});
