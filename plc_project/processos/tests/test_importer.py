"""Import Agent (L) tests: TIA block-export parsing, fidelity grading, claim
mapping and the pre-work baseline check (PLAN §0.6/§3.1/§4).

XML fixtures are inline simplified shapes of the REAL TIA Openness exports under
``tmp_validate/blk_probe_canvas`` and ``blk_validate/blk_probe_212316``
(SW.Blocks.OB/FB + AttributeList + namespaced Interface Sections + SCL
StructuredText/Access bodies) — the tests never depend on those paths.
"""
from __future__ import annotations

import hashlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from processos.api.import_routes import register_routes
from processos.api.store import ProjectStore
from processos.baselines import BaselineService
from processos.contract import clamp_contract
from processos.importer import ImportParseService
from processos.registry import ObjectRegistry
from processos.safety import SafetyError
from processos.traceability import TraceabilityService

PID = "PRJ_CLAMP"
BASE = "/api/processos/import"
IFACE_NS = "http://www.siemens.com/automation/Openness/SW/Interface/v5"
ST_NS = "http://www.siemens.com/automation/Openness/SW/NetworkSource/StructuredText/v4"


def _ob(name: str = "Main") -> str:
    """Main.xml 风格（blk_probe_canvas 真实样例的内联精简版）：OB/LAD/带接口。"""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Document><Engineering version="V19" />
  <SW.Blocks.OB ID="0"><AttributeList>
    <Interface><Sections xmlns="{IFACE_NS}">
      <Section Name="Input">
        <Member Name="Initial_Call" Datatype="Bool" Accessibility="Public" Informative="true" />
        <Member Name="Remanence" Datatype="Bool" Accessibility="Public" Informative="true" />
      </Section>
      <Section Name="Temp" />
    </Sections></Interface>
    <Name>{name}</Name><Number>1</Number>
    <ProgrammingLanguage>LAD</ProgrammingLanguage><SecondaryType>ProgramCycle</SecondaryType>
  </AttributeList></SW.Blocks.OB>
</Document>"""


def _fb(name: str, *, body: bool = True) -> str:
    """FB_EM_CLAMP_SEQ.xml / PumpCtrl.xml 风格：FB/SCL + 接口 + StructuredText 正文。"""
    scl = f"""<NetworkSource><StructuredText xmlns="{ST_NS}">
  <Token Text="IF" UId="1" />
  <Access Scope="LocalVariable" UId="2"><Symbol UId="3"><Component Name="Start" UId="4" /></Symbol></Access>
  <Token Text="THEN" UId="5" />
  <Access Scope="LocalVariable" UId="6"><Symbol UId="7"><Component Name="Running" UId="8" /></Symbol></Access>
  <Token Text=":=" UId="9" />
  <Access Scope="LiteralConstant" UId="10"><Constant UId="11"><ConstantValue UId="12">TRUE</ConstantValue></Constant></Access>
  <Token Text=";" UId="13" />
</StructuredText></NetworkSource>""" if body else ""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Document><Engineering version="V19" />
  <SW.Blocks.FB ID="0"><AttributeList>
    <Interface><Sections xmlns="{IFACE_NS}">
      <Section Name="Input">
        <Member Name="Start" Datatype="Bool" Accessibility="Public" />
        <Member Name="Extended" Datatype="Bool" Accessibility="Public" />
      </Section>
      <Section Name="Output">
        <Member Name="Busy" Datatype="Bool" Accessibility="Public" />
        <Member Name="Extend" Datatype="Bool" Accessibility="Public" />
      </Section>
    </Sections></Interface>
    <Name>{name}</Name><Number>2</Number>
    <ProgrammingLanguage>SCL</ProgrammingLanguage>
  </AttributeList>
  <ObjectList>
    <SW.Blocks.CompileUnit ID="3" CompositionName="CompileUnits">
      <AttributeList>{scl}
        <ProgrammingLanguage>SCL</ProgrammingLanguage>
      </AttributeList>
    </SW.Blocks.CompileUnit>
  </ObjectList>
  </SW.Blocks.FB>
</Document>"""


def _f_block(name: str = "F_SafetyGate") -> str:
    """F 块：Fail-Safe 命名约定（F_ 前缀）——真实样例中未导出 safety 块，构造内联等形。"""
    return _fb(name).replace("<ProgrammingLanguage>SCL</ProgrammingLanguage>",
                             "<ProgrammingLanguage>FBD</ProgrammingLanguage>", 1)


def _safety_marker_block() -> str:
    """非 F_ 前缀但携带 SafetyLanguage 标记 → 仍必须按 PROTECTED 处理（fail-closed）。"""
    return _fb("GateCtl").replace(
        "<Name>GateCtl</Name>",
        "<Name>GateCtl</Name><SafetyLanguage>F-Runtime</SafetyLanguage>", 1)


BROKEN_XML = "<Document><SW.Blocks.FB ID='0'><AttributeList><Name>Half"


def _mem(name: str, dt: str) -> str:
    return f'<Member Name="{name}" Datatype="{dt}" Accessibility="Public" />'


@pytest.fixture()
def service(tmp_path):
    db = str(tmp_path / "import.sqlite3")
    return ImportParseService(TraceabilityService(), BaselineService(db), db=db)


@pytest.fixture()
def client(tmp_path):
    app = FastAPI()
    db = str(tmp_path / "import.sqlite3")
    app.state.store = ProjectStore()
    app.state.store.create_project(clamp_contract())  # demo project PRJ_CLAMP
    app.state.trace = TraceabilityService()
    app.state.db_path = db
    app.state.baselines = BaselineService(db)
    app.state.importer = ImportParseService(app.state.trace, app.state.baselines, db=db)
    register_routes(app)
    return TestClient(app)


def _blocks(*xmls: str) -> list[dict]:
    return [{"name": f"blk{i}", "xml_text": x} for i, x in enumerate(xmls)]


# ---------- 1. fidelity grading over real block shapes ----------

def test_grades_main_ob_exact(service):
    doc = service.parse("canvas", [{"name": "Main.xml", "xml_text": _ob()}])
    node = doc["nodes"][0]
    assert node["fidelity"] == "EXACT"
    assert node["block_type"] == "OB" and node["language"] == "LAD"
    assert node["block_name"] == "Main" and node["number"] == "1"
    sigs = node["signals"]
    assert isinstance(sigs, list) and {s["name"] for s in sigs} == {"Initial_Call", "Remanence"}
    assert doc["stats"] == {"EXACT": 1, "PARTIAL": 0, "OPAQUE": 0, "PROTECTED": 0}


def test_grades_af_pattern_scl_exact_and_plain_fb_partial(service):
    doc = service.parse("212316", [
        {"name": "FB_EM_CLAMP_SEQ.xml", "xml_text": _fb("FB_EM_CLAMP_SEQ")},
        {"name": "PumpCtrl.xml", "xml_text": _fb("PumpCtrl")},
    ])
    af, pump = doc["nodes"]
    assert af["fidelity"] == "EXACT"  # AF 命名 + 接口 + SCL Access 提取完整
    assert pump["fidelity"] == "PARTIAL"  # 常规用户块：语义重建不完全
    assert pump["signals"][0]["section"] == "Input"


def test_af_scl_without_body_extraction_downgrades_to_partial(service):
    doc = service.parse("p", [{"name": "FB_U_ASSEMBLY_UNIT.xml",
                               "xml_text": _fb("FB_U_ASSEMBLY_UNIT", body=False)}])
    assert doc["nodes"][0]["fidelity"] == "PARTIAL"
    assert "SCL" in doc["nodes"][0]["note"]


def test_f_prefix_and_safety_marker_are_protected(service):
    doc = service.parse("safety", _blocks(_f_block(), _safety_marker_block()))
    assert all(n["fidelity"] == "PROTECTED" for n in doc["nodes"])
    assert doc["stats"]["PROTECTED"] == 2


def test_broken_xml_is_opaque_not_a_500(service):
    doc = service.parse("broken", [{"name": "Half", "xml_text": BROKEN_XML}])
    node = doc["nodes"][0]
    assert node["fidelity"] == "OPAQUE" and node["signals"] == "UNKNOWN"
    assert "解析失败" in node["note"]


# ---------- 2. HTTP parse + persistence roundtrip ----------

def test_http_parse_and_get_roundtrip(client):
    r = client.post(f"{BASE}/parse", json={
        "project_name": "装配线旧工程",
        "blocks": [{"name": "Main.xml", "xml_text": _ob()},
                   {"name": "F_SafetyGate.xml", "xml_text": _f_block()},
                   {"name": "Half", "xml_text": BROKEN_XML}]})
    assert r.status_code == 200
    doc = r.json()
    assert doc["stats"] == {"EXACT": 1, "PARTIAL": 0, "OPAQUE": 1, "PROTECTED": 1}
    assert doc["parsed_at"] and doc["parse_id"].startswith("PARSE_")

    got = client.get(f"{BASE}/parses/{doc['parse_id']}")
    assert got.status_code == 200 and got.json()["stats"] == doc["stats"]
    assert client.get(f"{BASE}/parses/PARSE_NOPE").status_code == 404


def test_parse_persists_across_service_instances(tmp_path):
    db = str(tmp_path / "import.sqlite3")
    first = ImportParseService(TraceabilityService(), BaselineService(db), db=db)
    doc = first.parse("roundtrip", [{"name": "Main.xml", "xml_text": _ob()}])
    second = ImportParseService(TraceabilityService(), BaselineService(db), db=db)
    restored = second.get_parse(doc["parse_id"])
    assert restored is not None
    assert restored["nodes"][0]["block_name"] == "Main"


# ---------- 3. claim: registry objects + deterministic relations ----------

def _claim_body(parse_id: str, mappings: list[dict], project_id: str = "") -> dict:
    return {"parse_id": parse_id, "project_id": project_id, "mappings": mappings}


def test_claim_builds_station_component_em_cm_relations(client):
    r = client.post(f"{BASE}/parse", json={"project_name": "装配线", "blocks": [
        {"name": "FB_U_ASSEMBLY_UNIT.xml", "xml_text": _fb("FB_U_ASSEMBLY_UNIT", body=False)},
        {"name": "FB_EM_CLAMP_SEQ.xml", "xml_text": _fb("FB_EM_CLAMP_SEQ")},
        {"name": "FB_CM_CLAMP_CYL_DRV.xml", "xml_text": _fb("FB_CM_CLAMP_CYL_DRV")},
        {"name": "PumpCtrl.xml", "xml_text": _fb("PumpCtrl")},
        {"name": "Main.xml", "xml_text": _ob()}]})
    parse_id = r.json()["parse_id"]

    claim = client.post(f"{BASE}/claim", json=_claim_body(parse_id, [
        {"block_name": "FB_U_ASSEMBLY_UNIT", "target_kind": "em", "station_name": "装配站"},
        {"block_name": "FB_EM_CLAMP_SEQ", "target_kind": "em", "station_name": "装配站"},
        {"block_name": "FB_CM_CLAMP_CYL_DRV", "target_kind": "cm", "station_name": "装配站",
         "driver_hint": "cylinder"},
        {"block_name": "PumpCtrl", "target_kind": "component", "station_name": "装配站",
         "display_name": "夹紧泵"},
    ], project_id=PID))
    assert claim.status_code == 200
    body = claim.json()
    assert len(body["objects"]) == 4
    assert {o["kind"] for o in body["objects"]} == {"af_em", "af_cm", "component"}
    assert {u["block_name"] for u in body["unmapped"]} == {"Main"}  # 未认领 → unmapped

    reg: ObjectRegistry = client.app.state.trace.registry
    station = reg.find_by_name("装配站")
    assert station is not None and station.kind == "station"
    ems = reg.neighbors(station.object_id, "maps_to", "out")  # §0.2 工位映射多个 EM
    assert sorted(e.display_name for e in ems) == ["FB_EM_CLAMP_SEQ", "FB_U_ASSEMBLY_UNIT"]
    pump = reg.find_by_name("夹紧泵")
    assert reg.neighbors(pump.object_id, "part_of", "out")[0].object_id == station.object_id
    cm = next(o for o in body["objects"] if o["kind"] == "af_cm")
    cm_obj = reg.get(cm["object_id"])
    assert cm_obj.attributes["driver_hint"] == "cylinder"
    assert cm_obj.attributes["project_id"] == PID
    em_id = reg.neighbors(cm_obj.object_id, "part_of", "out")[0]  # cm part_of 同批同工位 em
    assert em_id.kind == "af_em"


def test_claim_without_project_id_is_standalone(client):
    r = client.post(f"{BASE}/parse", json={"project_name": "x",
                                           "blocks": [{"name": "Main.xml", "xml_text": _ob()}]})
    claim = client.post(f"{BASE}/claim", json=_claim_body(r.json()["parse_id"], [
        {"block_name": "Main", "target_kind": "ob"}]))
    assert claim.status_code == 200
    obj = claim.json()["objects"][0]
    assert obj["kind"] == "ob" and obj["block_name"] == "Main"


def test_opaque_claim_is_marked_managed_native_override(client):
    r = client.post(f"{BASE}/parse", json={"project_name": "x",
                                           "blocks": [{"name": "Half", "xml_text": BROKEN_XML}]})
    block_name = r.json()["nodes"][0]["block_name"]  # parse 失败时保留上传名
    claim = client.post(f"{BASE}/claim", json=_claim_body(r.json()["parse_id"], [
        {"block_name": block_name, "target_kind": "other"}]))
    assert claim.status_code == 200
    oid = claim.json()["objects"][0]["object_id"]
    obj = client.app.state.trace.registry.get(oid)
    assert obj.attributes["ownership"] == "MANAGED_NATIVE_OVERRIDE"
    assert obj.attributes["fidelity"] == "OPAQUE"


# ---------- 4. PROTECTED claim -> 403 SAFETY_SCOPE_BLOCKED ----------

def test_protected_claim_blocked_at_service_level(service):
    doc = service.parse("s", [{"name": "F_SafetyGate.xml", "xml_text": _f_block()}])
    with pytest.raises(SafetyError) as ei:
        service.claim(doc["parse_id"], [
            {"block_name": "F_SafetyGate", "target_kind": "cm", "station_name": "s1"}])
    assert ei.value.code == "SAFETY_SCOPE_BLOCKED"
    assert ei.value.http_status == 403


def test_protected_claim_http_403(client):
    r = client.post(f"{BASE}/parse", json={"project_name": "s",
                                           "blocks": [{"name": "F_SafetyGate.xml", "xml_text": _f_block()}]})
    resp = client.post(f"{BASE}/claim", json=_claim_body(r.json()["parse_id"], [
        {"block_name": "F_SafetyGate", "target_kind": "em"}]))
    assert resp.status_code == 403
    body = resp.json()
    assert body["code"] == "SAFETY_SCOPE_BLOCKED"
    assert body["details"]["block_name"] == "F_SafetyGate"


def test_claim_unknown_parse_is_404(client):
    r = client.post(f"{BASE}/claim", json=_claim_body("PARSE_NOPE", [
        {"block_name": "X", "target_kind": "ob"}]))
    assert r.status_code == 404


def test_claim_unknown_project_is_404(client):
    r = client.post(f"{BASE}/parse", json={"project_name": "x",
                                           "blocks": [{"name": "Main.xml", "xml_text": _ob()}]})
    r = client.post(f"{BASE}/claim", json=_claim_body(r.json()["parse_id"], [
        {"block_name": "Main", "target_kind": "ob"}], project_id="PRJ_NOPE"))
    assert r.status_code == 404


# ---------- 5. baseline-check three states (PLAN §4 开工前比对) ----------

def test_baseline_check_no_baselines_is_unverified_with_note(service):
    out = service.baseline_check(PID)
    assert out["verdict"] == "UNVERIFIED_ONLINE"
    assert "无历史基线" in out["note"] and "B2" in out["note"]
    assert out["compare"] is None


def test_baseline_check_with_b2_passes_compare_through(service):
    svc: BaselineService = service._baselines
    arc = hashlib.sha256(b"zap19-v1").hexdigest()
    svc.record_b1(PID, "sha256:spec", 1)
    svc.record_b2(PID, "build_219", arc, {"FB_EM_CLAMP_SEQ": hashlib.sha256(b"em-v1").hexdigest(),
                                          "PumpCtrl": hashlib.sha256(b"pump-v1").hexdigest()})
    svc.record_b3(PID, "build_219", verification="FIELD_VERIFIED", plc_checksum=arc)

    out = service.baseline_check(PID, [
        {"block_name": "FB_EM_CLAMP_SEQ", "sha256": hashlib.sha256(b"em-v1").hexdigest()},
        {"block_name": "PumpCtrl", "sha256": hashlib.sha256(b"pump-EDITED").hexdigest()},
        {"block_name": "FB_New", "sha256": hashlib.sha256(b"new").hexdigest()}])
    assert out["verdict"] == "OK_TO_PROCEED"  # B2↔B3 匹配
    assert out["compare"]["b2_vs_b3"] == "MATCH"
    diff = out["block_diff"]  # 上传哈希 vs B2 清单的块级三方差异
    assert diff["matched"] == ["FB_EM_CLAMP_SEQ"]
    assert diff["changed"] == ["PumpCtrl"]
    assert diff["added_in_upload"] == ["FB_New"]
    assert diff["missing_from_upload"] == []


def test_baseline_check_self_reported_b3_stays_unverified(service):
    svc: BaselineService = service._baselines
    arc = hashlib.sha256(b"zap19-v1").hexdigest()
    svc.record_b2(PID, "build_219", arc, {})
    svc.record_b3(PID, "build_219", verification="SELF_REPORTED")
    out = service.baseline_check(PID)
    assert out["verdict"] == "UNVERIFIED_ONLINE"  # Build ID 自报不是现场验证
    assert out["compare"]["differences"][0]["kind"] == "UNVERIFIED_ONLINE"


def test_baseline_check_http_requires_known_project(client):
    r = client.post(f"{BASE}/baseline-check", json={"project_id": "PRJ_NOPE"})
    assert r.status_code == 404
    r = client.post(f"{BASE}/baseline-check", json={"project_id": PID})
    assert r.status_code == 200 and r.json()["verdict"] == "UNVERIFIED_ONLINE"


# ---------- 6. route mount idempotency ----------

def test_register_routes_is_idempotent(tmp_path):
    app = FastAPI()
    db = str(tmp_path / "import.sqlite3")
    app.state.trace = TraceabilityService()
    service = ImportParseService(app.state.trace, BaselineService(db), db=db)
    app.state.importer = service
    register_routes(app)
    before = len(app.routes)
    register_routes(app)
    assert len(app.routes) == before
    assert app.state.importer is service
