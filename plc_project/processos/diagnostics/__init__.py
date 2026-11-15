"""PLAN §1 L-loop · 编译诊断 → SourceMap → 画布/对象定位（修错闭环）。

``DiagnosticsLocateService.locate`` 把原生编译诊断（块名/行号/消息）经
SourceMap 反查回语义对象（CM/EM/Step），不可映射的块（手写原生代码/未知块）
显式标记 ``UNMAPPED_NATIVE_CODE``（§11：不可映射不猜），并附带
RepairBoundaryService 的候选修复提案（must_return_to_review 恒真）。

``compile_scope`` 对一组待交付 patch ops 给出**建议**编译范围（incremental/
full）：触及 invariants/interface/io 或结构性 add/remove → full（增量不安全）；
否则 incremental + 受影响块清单。生成器当前总是全量编译——本服务不冒充已
增量，note 明写增量由 FastWriteback 分级编译承接（C# 侧）。
"""
from processos.diagnostics.service import (
    BLOCK_LEVEL_TEXT,
    UNMAPPED_NATIVE_CODE,
    DiagnosticsLocateService,
)

__all__ = [
    "BLOCK_LEVEL_TEXT",
    "UNMAPPED_NATIVE_CODE",
    "DiagnosticsLocateService",
]
