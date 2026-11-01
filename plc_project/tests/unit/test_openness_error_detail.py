"""Openness 错误详情提取单测 — format_openness_failure / openness_error_details。

背景：真机 GenerateBlocksFromSource 失败时，C# Host（BlockService.cs）只回传
``Unwrap(ex).Message`` —— ``EngineeringTargetInvocationException`` 的包装语
"Error when calling method '…' of type '…'"（常在类型名中途戛然而止，
Python 提取层没有任何 [:N] 切片）；SCL 行号/语法诊断在 InnerException
全链与 EngineeringCompilationError 集合（Path/LineNumber/Text）里。

本文件验证提取层契约：
(a) InnerException 全链消息逐层带出（JSON payload 键 / Python __cause__ 链）；
(b) 编译错误集合逐条 ``<文件> 行 N: 文本``（零填充行号归一、缺路径兜底）；
(c) 外部源 .scl 文件名与首条诊断关联（``外部源: <name>``）；
(d) 超长消息不截断（提取层零丢失，展示层截断归消费方）；
(e) 既有消息前缀格式不变 —— 消费方（compile_jobs 归因 / fix_loop /
    refactor_pipeline._extract_compile_errors、画布 attribute_compiler_errors）
    按 message 字符串消费，只允许信息量单调追加。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.plc.tia.openness_cli import (
    exception_chain_messages,
    format_compilation_error_entry,
    format_openness_failure,
    openness_error_details,
)


# ---------------------------------------------------------------------------
# 合成 payload：真机 generate-from-source 失败时 Program.cs 的实际 JSON 形状
# （ok=false + project + generate.error，详情只到包装语为止）
# ---------------------------------------------------------------------------


def _legacy_fail_payload() -> dict:
    """真机观测到的「最穷」payload：没有任何 InnerException / 编译诊断。"""
    return {
        "ok": False,
        "project": {"ok": True, "message": "Project opened via TIA Openness."},
        "generate": {
            "ok": False,
            "error": {
                "code": "openness_error",
                "message": (
                    "Error when calling method 'GenerateBlocksFromSource' of type "
                    "'Siemens.Engineering.SW.ExternalSources.Plc"
                ),
            },
        },
        "_exit_code": 4,
    }


def _rich_fail_payload(scl: Path) -> dict:
    """理想 payload：InnerException 全链 + EngineeringCompilationError 集合。"""
    return {
        "ok": False,
        "project": {"ok": True, "message": "Project opened via TIA Openness."},
        "generate": {
            "ok": False,
            "sclPath": str(scl),
            "sourceName": scl.name,
            "error": {
                "code": "openness_error",
                "message": (
                    "Error when calling method 'GenerateBlocksFromSource' of type "
                    "'Siemens.Engineering.SW.ExternalSources.PlcExternalSource'"
                ),
                "innerException": {
                    "message": "SCL 外部源编译失败",
                    "innerException": {"message": "语法错误：设定值\"FUNCTION_BLOCK\"无效"},
                },
                "compilerErrors": [
                    {
                        "path": str(scl),
                        "lineNumber": "000014",
                        "text": "语法错误：设定值\"FUNCTION_BLOCK\"无效。",
                    },
                    {"lineNumber": 17, "text": "未声明的标识符 'data_in'"},
                    {"path": str(scl), "text": "缺少 END_FUNCTION_BLOCK"},
                ],
            },
        },
        "_exit_code": 4,
    }


# ---------------------------------------------------------------------------
# (e) 前缀兼容：无附加结构时输出与历史格式逐字节一致
# ---------------------------------------------------------------------------


def test_legacy_payload_format_byte_identical() -> None:
    """旧 payload（无 sclPath/无内部链）→ 消息与历史版本完全一致，零追加。"""
    payload = _legacy_fail_payload()
    msg = format_openness_failure(
        payload, project_path="C:/tmp/job1/Line.ap19", action="generate_from_source"
    )
    expected = (
        "TIA Openness SCL External Source → GenerateBlocksFromSource失败。\n"
        "工程: C:/tmp/job1/Line.ap19\n"
        "详情: Project opened via TIA Openness.\n"
        "Error when calling method 'GenerateBlocksFromSource' of type "
        "'Siemens.Engineering.SW.ExternalSources.Plc"
    )
    assert msg == expected
    # 提取层对纯包装语 payload 无可追加项
    assert openness_error_details(payload) == []


def test_rich_payload_prefix_unchanged_details_appended(tmp_path: Path) -> None:
    """新 payload：前缀逐字节保持，详情行只追加在尾部。"""
    scl = tmp_path / "FB1080_Component.scl"
    payload = _rich_fail_payload(scl)
    msg = format_openness_failure(
        payload,
        project_path="C:/tmp/job1/Line.ap19",
        action="generate_from_source",
        scl_path=scl,
    )
    # 前缀不变：历史正文（project.message + 包装语）原样保留
    expected_prefix = (
        "TIA Openness SCL External Source → GenerateBlocksFromSource失败。\n"
        "工程: C:/tmp/job1/Line.ap19\n"
        "详情: Project opened via TIA Openness.\n"
        "Error when calling method 'GenerateBlocksFromSource' of type "
        "'Siemens.Engineering.SW.ExternalSources.PlcExternalSource'"
    )
    assert msg.startswith(expected_prefix)
    # 尾部只增不改：追加行全部在前缀之后
    tail = msg[len(expected_prefix):]
    assert tail.startswith("\n")
    assert "外部源: FB1080_Component.scl" in tail
    assert "内部异常[1]: SCL 外部源编译失败" in tail
    assert "内部异常[2]: 语法错误：设定值\"FUNCTION_BLOCK\"无效" in tail


def test_payload_without_scl_keys_no_external_source_line() -> None:
    """payload 无 sclPath/sourceName 且未传 scl_path → 不产出外部源行。"""
    payload = _rich_fail_payload(Path("D:/x/FB_T.scl"))
    payload["generate"].pop("sclPath")
    payload["generate"].pop("sourceName")
    lines = openness_error_details(payload)
    assert not any(line.startswith("外部源:") for line in lines)
    # 编译诊断仍在，仅缺路径兜底
    assert any("行 14:" in line for line in lines)


# ---------------------------------------------------------------------------
# (a) InnerException 全链
# ---------------------------------------------------------------------------


def test_inner_exception_chain_levels() -> None:
    """两级嵌套 innerException → 内部异常[1]/[2] 逐层带出。"""
    scl = Path("D:/staging/FB1910_DrillData.scl")
    payload = _rich_fail_payload(scl)
    lines = openness_error_details(payload, scl_path=scl)
    assert lines[0] == "外部源: FB1910_DrillData.scl"
    assert "内部异常[1]: SCL 外部源编译失败" in lines
    assert "内部异常[2]: 语法错误：设定值\"FUNCTION_BLOCK\"无效" in lines


def test_python_exception_cause_chain() -> None:
    """Python 异常输入：__cause__ 链（等价 InnerException）逐层带出。"""
    try:
        try:
            raise ValueError("底层根因：DB 连接已关闭")
        except ValueError as inner:
            raise RuntimeError("Openness 调用失败") from inner
    except RuntimeError as exc:
        chain = exception_chain_messages(exc)
        assert chain == ["底层根因：DB 连接已关闭"]
        details = openness_error_details(exc)
        assert details == ["内部异常[1]: 底层根因：DB 连接已关闭"]
        msg = format_openness_failure(exc, project_path="C:/p.ap19", action="compile")
        assert msg.startswith("TIA Openness 编译 PLC 软件（ICompilable.Compile）失败。\n")
        assert "内部异常[1]: 底层根因：DB 连接已关闭" in msg


def test_plain_exception_has_no_details() -> None:
    exc = RuntimeError("孤立的失败")
    assert exception_chain_messages(exc) == []
    assert openness_error_details(exc) == []


# ---------------------------------------------------------------------------
# (b) 编译错误集合 → 「文件 行 N: 文本」
# ---------------------------------------------------------------------------


def test_format_compilation_error_entry_variants() -> None:
    """零填充行号归一、路径取 basename、缺路径兜底、缺行号只留文本。"""
    entry = {
        "path": r"D:\staging\FB1080_Component.scl",
        "lineNumber": "000014",
        "text": "语法错误：设定值\"FUNCTION_BLOCK\"无效。",
    }
    assert (
        format_compilation_error_entry(entry)
        == "FB1080_Component.scl 行 14: 语法错误：设定值\"FUNCTION_BLOCK\"无效。"
    )
    # 缺路径 → default_path（外部源文件名）兜底
    assert (
        format_compilation_error_entry(
            {"lineNumber": 17, "text": "未声明的标识符 'data_in'"},
            default_path="FB1080_Component.scl",
        )
        == "FB1080_Component.scl 行 17: 未声明的标识符 'data_in'"
    )
    # 缺行号 → 只留文本，不带 "行 N:"
    assert (
        format_compilation_error_entry({"text": "缺少 END_FUNCTION_BLOCK"})
        == "缺少 END_FUNCTION_BLOCK"
    )
    # 纯字符串条目原样保留
    assert format_compilation_error_entry("原始诊断文本") == "原始诊断文本"
    # 未知 dict 结构 → JSON 序列化兜底，不丢字段
    unknown = format_compilation_error_entry({"weird": True})
    assert "weird" in unknown


def test_compile_error_collection_in_details(tmp_path: Path) -> None:
    scl = tmp_path / "FB1080_Component.scl"
    payload = _rich_fail_payload(scl)
    lines = openness_error_details(payload, scl_path=scl)
    diag = [line for line in lines if line.startswith("编译诊断（3 条）:")]
    assert len(diag) == 1
    # 整组并入单行（消费方前瞻正则不接受条目间换行），条目以三个空格分隔
    assert "FB1080_Component.scl 行 14: 语法错误：设定值\"FUNCTION_BLOCK\"无效。" in diag[0]
    # 无路径条目用 scl 文件名兜底 → 每条诊断都能自证出处
    assert "FB1080_Component.scl 行 17: 未声明的标识符 'data_in'" in diag[0]
    # 无行号条目只留文本（仍带文件关联）
    assert "FB1080_Component.scl 缺少 END_FUNCTION_BLOCK" in diag[0]
    # 诊断行必须是最后一行：$ 前瞻要求末条之后直达串尾
    assert lines[-1] is diag[0]


def test_alternative_collection_keys() -> None:
    """compilationErrors / innerMessages 等别名键同样识别。"""
    payload = {
        "error": {
            "message": "wrapper",
            "innerMessages": ["第一层根因"],
            "compilationErrors": [{"line": "000003", "description": "分号缺失"}],
        }
    }
    lines = openness_error_details(payload)
    assert "内部异常[1]: 第一层根因" in lines
    assert "编译诊断（1 条）: 行 3: 分号缺失" in lines


def test_cli_stderr_appended() -> None:
    """CLI 崩溃时 stderr 尾部也随详情带出（正文不含 _stderr）。"""
    payload = _legacy_fail_payload()
    payload["_stderr"] = "Unhandled exception. EngineCompilationError dump..."
    lines = openness_error_details(payload)
    assert any(line.startswith("CLI stderr: Unhandled exception") for line in lines)


# ---------------------------------------------------------------------------
# (d) 超长消息不截断
# ---------------------------------------------------------------------------


def test_long_messages_not_truncated() -> None:
    """400 条编译诊断 + 超长文本：首尾条目齐全、无省略号、条数完整。"""
    entries = [
        {
            "path": r"D:\staging\FB1080_Component.scl",
            "lineNumber": f"{i:06d}",
            "text": f"诊断第 {i} 条：" + "x" * 120,
        }
        for i in range(1, 401)
    ]
    payload = {
        "ok": False,
        "generate": {
            "ok": False,
            "sourceName": "FB1080_Component.scl",
            "error": {
                "code": "openness_error",
                "message": "wrapper",
                "compilerErrors": entries,
            },
        },
    }
    msg = format_openness_failure(
        payload,
        project_path="C:/tmp/job1/Line.ap19",
        action="generate_from_source",
        scl_path="D:/staging/FB1080_Component.scl",
    )
    # 首条与末条都在 —— 任何 [:N] 切片都会丢掉末条
    assert "行 1: 诊断第 1 条：" in msg
    assert "行 400: 诊断第 400 条：" in msg
    # 条数完整，无省略截断
    assert msg.count("诊断第 ") == 400
    assert "编译诊断（400 条）:" in msg
    assert "…" not in msg and "..." not in msg
    assert len(msg) > 400 * 130


# ---------------------------------------------------------------------------
# (e) 消费方兼容：画布归因解析「行 N:」诊断
# ---------------------------------------------------------------------------


def test_canvas_attribution_parses_enhanced_detail() -> None:
    r"""端到端：增强详情经 plc_engine.attribute_compiler_errors 归因到块。

    画布用正则 ``行\s*0*(\d+)[:：]`` 提取诊断 —— 本测试用该真实函数
    验证追加行的格式与之兼容（否则详情永远进不了修复循环）。
    """
    from plc_engine.canvas_model import attribute_compiler_errors, create_empty_canvas

    scl = Path(r"D:\tmp_compile\import_bundle\FB1080_Component.scl")
    formatted = format_openness_failure(
        _rich_fail_payload(scl),
        project_path=r"C:\tmp_compile\Line.ap19",
        action="generate_from_source",
        scl_path=scl,
    )
    canvas = create_empty_canvas(project_name="Line")
    compile_result = {
        "scl_results": [{"scl": str(scl), "result": {"ok": False, "error": formatted}}]
    }
    attributions = attribute_compiler_errors(canvas, compile_result)
    assert len(attributions) == 1
    att = attributions[0]
    # 前缀契约：博图生成失败：块 [X] … 开头保持
    assert att["message"].startswith("博图生成失败：块 [FB1080_Component] ")
    # 行号诊断被画布正则捕获并转成「行 N：文本」展示；
    # 第三条无行号（缺少 END_FUNCTION_BLOCK）被并入前条文本，不单列
    assert "行 14：语法错误：设定值\"FUNCTION_BLOCK\"无效。" in att["message"]
    assert "行 17：未声明的标识符 'data_in'" in att["message"]
    assert "缺少 END_FUNCTION_BLOCK" in att["message"]
    # 归因 detail 保留完整提取结果（本用例 <1000 字符，不受展示层截断）
    assert "内部异常[2]" in att["detail"]
    assert "缺少 END_FUNCTION_BLOCK" in att["detail"]
    assert att["target_id"] == "FB1080_Component"
    assert att["severity"] == "error"


# ---------------------------------------------------------------------------
# writeback 错误收集：_exception_result 带异常链
# ---------------------------------------------------------------------------


def test_writeback_exception_result_carries_chain() -> None:
    from agents.plc.tia.writeback import _exception_result

    try:
        try:
            raise ValueError("根因：SCL 源文件不存在")
        except ValueError as inner:
            raise RuntimeError("generate-from-source 调用失败") from inner
    except RuntimeError as exc:
        payload = _exception_result(exc)
        assert payload["ok"] is False
        # 只追加不改前缀：error 仍以原异常消息开头
        assert payload["error"].startswith("generate-from-source 调用失败")
        assert "内部异常: 根因：SCL 源文件不存在" in payload["error"]
        assert payload["error_chain"] == ["根因：SCL 源文件不存在"]


def test_writeback_exception_result_plain() -> None:
    from agents.plc.tia.writeback import _exception_result

    payload = _exception_result(RuntimeError("无链失败"))
    assert payload == {"ok": False, "error": "无链失败"}


# ---------------------------------------------------------------------------
# CLI 失败路径：generate_from_source_via_openness_cli 传入 scl_path
# ---------------------------------------------------------------------------


def test_generate_from_source_cli_failure_carries_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """monkeypatch CLI 返回失败 payload → RuntimeError 消息带 .scl 关联与诊断。"""
    from agents.plc.tia import openness_cli as oc

    scl = tmp_path / "FB_Foo.scl"
    scl.write_text('FUNCTION_BLOCK "FB_Foo"\nEND_FUNCTION_BLOCK\n', encoding="utf-8")
    project = tmp_path / "Line.ap19"
    project.write_bytes(b"fake")

    def fake_cli(*_args: str, **_kw) -> dict:
        return _rich_fail_payload(scl)

    monkeypatch.setattr(oc, "openness_cli", fake_cli)

    with pytest.raises(RuntimeError) as ei:
        oc.generate_from_source_via_openness_cli(project, scl)
    msg = str(ei.value)
    assert msg.startswith(
        "TIA Openness SCL External Source → GenerateBlocksFromSource失败。\n"
    )
    assert "外部源: FB_Foo.scl" in msg
    assert "内部异常[1]: SCL 外部源编译失败" in msg
    assert "FB_Foo.scl 行 14: 语法错误：设定值\"FUNCTION_BLOCK\"无效。" in msg


def test_license_branch_keeps_prefix_and_appends_details() -> None:
    """许可证分支：无附加结构时与历史格式逐字节一致；有则只在尾部追加。"""
    legacy = {
        "error": {
            "code": "openness_error",
            "message": (
                "Error when calling method 'Export' of type "
                "'Siemens.Engineering.SW.Blocks.InstanceDB'. "
                "Necessary license 'STEP 7 Basic' is missing."
            ),
        }
    }
    msg = format_openness_failure(legacy, project_path="C:/x/Line.ap19", action="export")
    expected = (
        "TIA Openness 已打开工程，但操作失败：缺少必要许可证（如 STEP 7 Basic）。\n"
        "请在本机 Automation License Manager 安装/激活与 Portal 版本匹配的 "
        "STEP 7 / TIA 许可证后重试导出与写回。\n"
        "工程: C:/x/Line.ap19\n"
        "详情: Error when calling method 'Export' of type "
        "'Siemens.Engineering.SW.Blocks.InstanceDB'. "
        "Necessary license 'STEP 7 Basic' is missing."
    )
    assert msg == expected

    rich = {
        "error": {
            "message": legacy["error"]["message"],
            "innerException": {"message": "许可证服务未启动"},
        }
    }
    msg2 = format_openness_failure(rich, project_path="C:/x/Line.ap19", action="export")
    assert msg2.startswith(expected)
    assert "内部异常[1]: 许可证服务未启动" in msg2
