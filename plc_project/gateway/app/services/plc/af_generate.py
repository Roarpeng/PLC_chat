"""AF 内置化 N 线服务:confirmed 工艺需求 → AF V1.2 画布草稿(契约 docs/23 §3)。

链路全部复用外部会话的 ``plc_engine/af`` 引擎,零平行造轮子:
- ``planner.plan_af_project_from_spec``(需求卡 dict 自动路由到
  ``_plan_from_requirement_card``:origin_prompt + intent_summary + items
  全文拼工艺描述 → ``_parse_devices_from_text`` / ``_plan_em_from_text``);
- ``af_generator.generate_af_project_blocks``(官方 V1.2 块生成,
  软件单元命名 ``U#_…`` / ``U#Em#_…``,OB 编号走 ``af_numbering``);
- ``af_linter.lint_af_canvas`` + ``plc_engine.scl_precheck.precheck_canvas``
  双门禁(AF 结构规则 + IEC 61131 SCL 结构预检)。

铁律:本服务**只产画布草稿,不做任何写回**——工程落盘、编译、PCEC
事务仍由既有确认链(confirm-writeback 等)承载。
"""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any

from plc_engine.af.af_generator import generate_af_project_blocks
from plc_engine.af.af_linter import lint_af_canvas
from plc_engine.af.planner import plan_af_project_from_spec
from plc_engine.canvas_model import CanvasState
from plc_engine.scl_precheck import precheck_canvas

#: 门禁发现上限(契约 §3:linter_findings / iec_violations 各截 50)
MAX_FINDINGS = 50


class RequirementNotConfirmed(ValueError):
    """需求卡未通过 confirmed 门禁(docs/23 §3:未确认不得生成)。"""

    def __init__(self) -> None:
        super().__init__("REQUIREMENT_NOT_CONFIRMED")


def wash_project_name(name: str) -> str:
    """洗成合法 SCL 标识(规则与 planner._clean_identifier 对齐,幂等)。

    非字母数字下划线一律剔除;首字符非字母则补 ``Project_`` 前缀;
    全空(如纯中文)回退 ``AF_Project``。示例::``"Line-1#装箱"`` → ``"Line1"``。
    """
    cleaned = re.sub(r"[^A-Za-z0-9_]", "", str(name or "").strip())
    if not cleaned:
        return "AF_Project"
    if not cleaned[0].isalpha():
        cleaned = f"Project_{cleaned}"
    return cleaned


def generate_from_requirement(requirement: dict[str, Any], project_name: str) -> dict[str, Any]:
    """从 confirmed 工艺需求卡生成 AF V1.2 画布草稿(只生成,不写回)。

    Args:
        requirement: 完整需求卡对象(requirement_store 契约 docs/22 §1 的 12 字段),
            必须 ``confirmation_status == "confirmed"``,否则抛
            ``ValueError("REQUIREMENT_NOT_CONFIRMED")``。
        project_name: 工程名(U 线最小创建确认给出);缺省回退卡内
            ``project_name``,再缺省 ``AF_Project``。洗成合法标识后作为
            Unit 命名(``U1_<洗过的项目名>``)。

    Returns:
        ``{canvas, blocks_created, linter_findings, iec_violations}``;
        两组门禁发现各截 ``MAX_FINDINGS`` 条。
    """
    # 1. confirmed 门禁:未确认/非对象一律拒绝(工艺意图未确认不得生成)
    if not isinstance(requirement, dict) or str(requirement.get("confirmation_status") or "") != "confirmed":
        raise RequirementNotConfirmed()

    # 2. 工程名:body 优先(最小创建确认的权威名),回退卡内字段
    p_name = wash_project_name(str(project_name or "").strip() or str(requirement.get("project_name") or ""))

    # 3. 文本规划:planner 对含 items/requirement_id 的 dict 自动走
    #    _plan_from_requirement_card(origin_prompt+intent_summary+items 全文
    #    → 设备解析 + EM/工序规划),单 Unit 起步:U1_<洗过的项目名>
    card = dict(requirement)
    card["project_name"] = p_name  # 强制以 body 工程名为准(覆盖卡内旧名)
    af_project = plan_af_project_from_spec(card, project_name=p_name)

    # 4. 官方 V1.2 块生成 → 合成画布(全部 draft,software_unit 按生成器输出)
    generated = generate_af_project_blocks(af_project)
    canvas = CanvasState(project_name=af_project.name)
    for key, block in generated.items():
        block.status = "draft"
        canvas.blocks[key] = block

    # 5. 双门禁:AF 结构 linter + SCL/IEC 预检(只报告,不拦截——草稿交由
    #    四层审查/确认链消化;发现结构可查,violation 不静默丢弃)
    findings = lint_af_canvas(canvas)
    linter_findings = [asdict(f) if hasattr(f, "__dataclass_fields__") else f for f in findings]
    iec_result = precheck_canvas(canvas)
    iec_violations = list(iec_result.get("findings") or [])

    return {
        "canvas": canvas.to_dict(),
        "blocks_created": len(generated),
        "linter_findings": linter_findings[:MAX_FINDINGS],
        "iec_violations": iec_violations[:MAX_FINDINGS],
    }
