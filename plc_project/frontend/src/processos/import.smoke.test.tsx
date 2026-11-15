import { afterEach, describe, expect, it, vi } from "vitest";
import { renderToString } from "react-dom/server";
import {
  ImportTreeView, buildClaimPayload, draftFor, groupByFidelity, ImportView, ClaimTable,
  type ClaimDraft,
} from "./ImportView";
import {
  importerApi, readBlockFiles, sha256Hex, verdictLabel, verdictTone,
  type ParsedBlock, type ParseResult,
} from "./apiImporter";

/* Node-environment tests (no jsdom), pattern of views.smoke / canvas.smoke:
   (1) fetch is mocked and the REAL apiImporter calls are asserted (binding,
   URL, actor headers, payload shape); (2) presentational views render their
   data to markup; (3) pure helpers (grouping, draft prefill, claim payload)
   are exercised directly. */

const BLOCK_XML = '<?xml version="1.0"?><Document><SW.Blocks.FB ID="0"><AttributeList>' +
  '<Interface><Sections xmlns="http://www.siemens.com/automation/Openness/SW/Interface/v5">' +
  '<Section Name="Input"><Member Name="Start" Datatype="Bool" /></Section>' +
  '</Sections></Interface><Name>FB_EM_CLAMP_SEQ</Name><Number>2</Number>' +
  '<ProgrammingLanguage>SCL</ProgrammingLanguage></AttributeList></SW.Blocks.FB></Document>';

function blk(node_id: string, block_name: string, fidelity: ParsedBlock["fidelity"],
             signals: ParsedBlock["signals"] = [{ name: "Start", datatype: "Bool", section: "Input" }]): ParsedBlock {
  return { node_id, block_name, block_type: "FB", number: "2", language: "SCL",
           fidelity, signals, note: "note-" + fidelity };
}

const parse: ParseResult = {
  parse_id: "PARSE_ABC123", project_name: "装配线旧工程", parsed_at: "2026-11-15T09:00:00+00:00",
  nodes: [
    blk("node_001", "FB_EM_CLAMP_SEQ", "EXACT"),
    blk("node_002", "FB_CM_CLAMP_CYL_DRV", "EXACT"),
    blk("node_003", "PumpCtrl", "PARTIAL"),
    blk("node_004", "DB_Recipe", "OPAQUE", "UNKNOWN"),
    blk("node_005", "F_SafetyGate", "PROTECTED", [{ name: "ACK", datatype: "Bool", section: "Input" }]),
  ],
  stats: { EXACT: 2, PARTIAL: 1, OPAQUE: 1, PROTECTED: 1 },
};

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn(async (_url: string, _init: any) => ({
    ok: status >= 200 && status < 300,
    status,
    statusText: "x",
    text: async () => JSON.stringify(body),
  }));
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("apiImporter binding", () => {
  it("parse posts to /api/processos/import/parse with actor headers and block payload", async () => {
    const fn = mockFetch(200, parse);
    const r = await importerApi.parse({ project_name: "装配线旧工程", blocks: [{ name: "Main", xml_text: BLOCK_XML }] });
    expect(r.parse_id).toBe("PARSE_ABC123");
    const [url, init] = fn.mock.calls[0];
    expect(url).toBe("/api/processos/import/parse");
    expect(init.method).toBe("POST");
    expect(init.headers["X-Actor-Id"]).toBe("demo_operator"); // actorHeaders() demo identity
    expect(init.headers["X-Actor-Role"]).toBe("Viewer");
    expect(init.headers["Content-Type"]).toBe("application/json");
    const body = JSON.parse(init.body);
    expect(body.project_name).toBe("装配线旧工程");
    expect(body.blocks[0]).toEqual({ name: "Main", xml_text: BLOCK_XML });
  });

  it("claim posts parse_id, project_id and mappings to /claim", async () => {
    const fn = mockFetch(200, { claim_id: "CLAIM_X", parse_id: "PARSE_ABC123", project_id: null, objects: [], unmapped: [] });
    await importerApi.claim({
      parse_id: "PARSE_ABC123", project_id: "PRJ_CLAMP",
      mappings: [{ block_name: "FB_EM_CLAMP_SEQ", target_kind: "em", station_name: "装配站" }],
    });
    const [url, init] = fn.mock.calls[0];
    expect(url).toBe("/api/processos/import/claim");
    const body = JSON.parse(init.body);
    expect(body.parse_id).toBe("PARSE_ABC123");
    expect(body.project_id).toBe("PRJ_CLAMP");
    expect(body.mappings[0].target_kind).toBe("em");
  });

  it("baselineCheck posts project_id and surfaces the verdict", async () => {
    const fn = mockFetch(200, { project_id: "PRJ_CLAMP", verdict: "UNVERIFIED_ONLINE",
      note: "新导入，无历史基线，登记 B2 后可比对", compare: null, block_diff: null });
    const r = await importerApi.baselineCheck({ project_id: "PRJ_CLAMP" });
    expect(r.verdict).toBe("UNVERIFIED_ONLINE");
    expect(fn.mock.calls[0][0]).toBe("/api/processos/import/baseline-check");
  });
});

describe("upload helpers", () => {
  it("readBlockFiles reads xml text and the manifest project name", async () => {
    const files = [
      new File([BLOCK_XML], "FB_EM_CLAMP_SEQ.xml", { type: "text/xml" }),
      new File(['{"projectName":"CanvasE2E"}'], "manifest.json", { type: "application/json" }),
      new File(["ignore"], "notes.txt"),
    ];
    const out = await readBlockFiles(files);
    expect(out.projectName).toBe("CanvasE2E");
    expect(out.blocks).toEqual([{ name: "FB_EM_CLAMP_SEQ", xml_text: BLOCK_XML }]);
  });

  it("sha256Hex computes a real hash, never a fabricated one", async () => {
    expect(await sha256Hex("abc"))
      .toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  });
});

describe("fidelity tree", () => {
  it("groupByFidelity keeps EXACT→PARTIAL→OPAQUE→PROTECTED order and drops empties", () => {
    const groups = groupByFidelity(parse.nodes);
    expect(groups.map(g => g[0])).toEqual(["EXACT", "PARTIAL", "OPAQUE", "PROTECTED"]);
    expect(groups[0][1]).toHaveLength(2);
  });

  it("ImportTreeView renders grouped badges, signals, UNKNOWN and the read-only lock", () => {
    const html = renderToString(<ImportTreeView parse={parse} />);
    expect((html.match(/fid EXACT/g) ?? []).length).toBeGreaterThanOrEqual(1);
    expect(html).toContain("PumpCtrl");
    expect(html).toContain("黑盒 · 仅元数据");
    expect(html).toContain("信号清单 UNKNOWN");
    expect(html).toContain("F_SafetyGate");
    expect(html).toContain("只读");
    expect(html).toContain("F/Safety 只读零修改");
  });
});

describe("claim mapping", () => {
  it("draftFor prefills AF-pattern blocks conservatively", () => {
    expect(draftFor(blk("n", "FB_EM_CLAMP_SEQ", "EXACT")).target_kind).toBe("em");
    expect(draftFor(blk("n", "FB_CM_CLAMP_CYL_DRV", "EXACT")).target_kind).toBe("cm");
    expect(draftFor(blk("n", "Main", "EXACT")).target_kind).toBe("ob");
    expect(draftFor(blk("n", "PumpCtrl", "PARTIAL")).target_kind).toBe("");
  });

  it("ClaimTable disables the select on PROTECTED rows and marks them read-only", () => {
    const html = renderToString(
      <ClaimTable parse={parse} drafts={{}} onDraft={() => { }} />);
    expect(html).toContain("disabled");
    expect(html).toContain("安全块 · 只读，不可认领");
    expect(html).toContain("MANAGED_NATIVE_OVERRIDE"); // OPAQUE row hint
  });

  it("buildClaimPayload sends only claimed rows, never PROTECTED", () => {
    const drafts: Record<string, ClaimDraft> = {
      FB_EM_CLAMP_SEQ: { ...draftFor(parse.nodes[0]), station_name: "装配站" },
      FB_CM_CLAMP_CYL_DRV: { ...draftFor(parse.nodes[1]), station_name: " 装配站 ", driver_hint: "cylinder" },
      PumpCtrl: { ...draftFor(parse.nodes[2]), target_kind: "component", display_name: "夹紧泵" },
      DB_Recipe: { ...draftFor(parse.nodes[3]) }, // OPAQUE 但未选择 → 不提交
      F_SafetyGate: { ...draftFor(parse.nodes[4]), target_kind: "cm" }, // 即使 UI 被绕过也不得提交
    };
    const body = buildClaimPayload(parse, drafts, "PRJ_CLAMP");
    expect(body.parse_id).toBe("PARSE_ABC123");
    expect(body.project_id).toBe("PRJ_CLAMP");
    expect(body.mappings.map(m => m.block_name)).toEqual(
      ["FB_EM_CLAMP_SEQ", "FB_CM_CLAMP_CYL_DRV", "PumpCtrl"]);
    expect(body.mappings[1].station_name).toBe("装配站"); // trim
    expect(body.mappings[1].driver_hint).toBe("cylinder");
    expect(body.mappings[0].display_name).toBe("FB_EM_CLAMP_SEQ");
  });
});

describe("ImportView screens", () => {
  it("screen 0 states the pre-work comparison and the fresh-import yellow banner", () => {
    const html = renderToString(<ImportView onCancel={() => { }} onDone={() => { }} />);
    expect(html).toContain("开工前比对");
    expect(html).toContain("全新导入 · 无历史基线");
    expect(html).toContain("将登记首份 B2");
    expect(html).toContain("B3 不能仅凭 Build ID 自报");
  });

  it("verdict helpers map the three-colour banner tones", () => {
    expect(verdictTone("OK_TO_PROCEED")).toBe("ok");
    expect(verdictTone("FROZEN_DRIFT")).toBe("err");
    expect(verdictTone("UNVERIFIED_ONLINE")).toBe("warn");
    expect(verdictLabel("FROZEN_DRIFT")).toContain("冻结变更");
  });
});
