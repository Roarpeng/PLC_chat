import type { PlcJobDetail } from "../api";
import type { SclDiffItem } from "../SclDiffPreview";

type CsOp = { kind?: string; payload?: Record<string, unknown> };

export function helperNamesFromChangeset(ops: CsOp[], notes: unknown[], focus: string): string[] {
  const helpers = new Set<string>();
  const prefix = `optimize:decouple:${focus}->`;
  for (const n of notes) {
    const s = String(n);
    if (s.startsWith(prefix)) helpers.add(s.slice(prefix.length).split(":")[0].trim());
  }
  const newBlocks = new Set(
    ops
      .filter((o) => o.payload?.new_block && o.payload?.block_name)
      .map((o) => String(o.payload?.block_name)),
  );
  for (const op of ops) {
    if (op.kind !== "add_edge") continue;
    const src = String(op.payload?.source || "");
    const tgt = String(op.payload?.target || "");
    const srcN = src.startsWith("Block::") ? src.slice("Block::".length) : src;
    const tgtN = tgt.startsWith("Block::") ? tgt.slice("Block::".length) : tgt;
    const props = (op.payload?.props || {}) as Record<string, unknown>;
    const etype = String(op.payload?.type || "");
    if (srcN !== focus || !tgtN) continue;
    if (props.evidence === "decouple_extract" || (etype === "CALLS" && newBlocks.has(tgtN))) {
      helpers.add(tgtN);
    }
  }
  return [...helpers].filter((h) => h && h !== focus);
}

export function writebackHintForBlock(
  job: PlcJobDetail | null | undefined,
  blockName: string,
): { canWrite: boolean; reason: string } {
  const name = String(blockName || "").trim();
  if (!name) {
    return { canWrite: false, reason: "未选中程序块" };
  }
  if (!job?.changeset) {
    return { canWrite: false, reason: "请先点「优化SCL」生成 HITL 预览（不会自动反写）" };
  }
  const cs = job.changeset as { ops?: CsOp[]; notes?: unknown[] };
  const ops = Array.isArray(cs.ops) ? cs.ops : [];
  const allowed = new Set([name, ...helperNamesFromChangeset(ops, cs.notes || [], name)]);
  const importable = ops.some((op) => {
    const b = String(op.payload?.block_name || "");
    if (!allowed.has(b)) return false;
    if (op.kind === "rewrite_scl" || op.kind === "stage_scl_source") {
      return Boolean(String(op.payload?.scl_text || op.payload?.scl || "").trim());
    }
    return op.kind === "stage_xml_import" && Boolean(op.payload?.xml_path);
  });
  if (importable) {
    return {
      canWrite: true,
      reason: "确认该块 changeset 并 Openness 反写归档 .zap（不含工程级死块删除）",
    };
  }
  const skipped = (job.scl_skipped || []).find((s) => s.block === name);
  if (skipped) {
    const bit = [skipped.reason, skipped.detail].filter(Boolean).join(" — ");
    return { canWrite: false, reason: bit || "跳过写程序体" };
  }
  const block = (job.blocks || []).find((b) => b.name === name);
  if (block?.is_safety) {
    return { canWrite: false, reason: "Safety/F-block，拒绝写程序体" };
  }
  if (block?.protected) {
    return { canWrite: false, reason: "Know-how / protected，拒绝写程序体" };
  }
  if (block?.interface_only || block?.body_available === false) {
    return { canWrite: false, reason: "interface-only / 无程序体，无可写 SCL" };
  }
  return { canWrite: false, reason: "该块没有可落地的 XML/SCL 写回" };
}

export function sclDiffsForFocus(job: PlcJobDetail | null | undefined, focus?: string | null): SclDiffItem[] {
  const diffs = job?.scl_diffs || [];
  const name = String(focus || "").trim();
  if (!name) return diffs.slice(0, 8);
  const cs = job?.changeset as { ops?: CsOp[]; notes?: unknown[] } | undefined;
  const helpers = helperNamesFromChangeset(cs?.ops || [], cs?.notes || [], name);
  const allowed = new Set([name, ...helpers]);
  const kept = diffs.filter((d) => allowed.has(String(d.block || "")));
  const fallback = diffs.filter((d) => String(d.block || "") === name);
  return (kept.length ? kept : fallback).slice(0, 8);
}

export function formatWritebackRecap(
  data: Record<string, unknown>,
  detail: PlcJobDetail | null,
  scopedBlock?: string | null,
): string {
  const wb = (detail?.writeback || data) as Record<string, unknown>;
  const scope = String(wb.scope || (scopedBlock ? `block:${scopedBlock}` : "project"));
  const helpers = Array.isArray(wb.helper_blocks)
    ? (wb.helper_blocks as unknown[]).map((h) => String(h)).filter(Boolean)
    : [];
  const lines = ["### 确认反写"];
  if (scope.startsWith("block:")) {
    const block = scope.slice("block:".length) || scopedBlock || "?";
    const extra = helpers.length ? `（含 helper ${helpers.map((h) => `\`${h}\``).join("、")}）` : "";
    lines.push(`范围：焦点块 \`${block}\`${extra}。未应用工程级死块删除/无关块写回。`);
  } else {
    lines.push("范围：**整工程变更集**（含死块标注等全部 ops）。");
  }
  const skip = String(wb.skip_reason || "").trim();
  const openness = (wb.openness || data.openness) as Record<string, unknown> | undefined;
  const zapArchive = (wb.zap_archive || data.zap_archive) as Record<string, unknown> | undefined;
  const zap = String(
    wb.zap_path || data.zap_path || zapArchive?.path || "",
  ).trim();
  if (wb.skipped) {
    lines.push("");
    lines.push(`**跳过 Openness**：${skip || String(openness?.reason || openness?.note || "无可写操作")}`);
    lines.push("未导入、未编译、未归档 .zap。");
    return lines.join("\n");
  }
  if (openness?.import_ok === true || (openness?.ok === true && !openness?.skipped)) {
    lines.push("导入：**成功**");
  } else if (openness?.skipped) {
    lines.push(`导入：跳过（${String(openness.note || openness.reason || "未请求 Openness")}）`);
  } else if (openness) {
    const err = String(openness.error || openness.reason || "").trim();
    lines.push("导入：**失败**" + (err ? `（${err}）` : ""));
  } else {
    lines.push("导入：未执行");
  }
  const compile = (data.compile || wb.compile || openness?.compile) as Record<string, unknown> | undefined;
  const inner =
    compile && typeof compile.compile === "object" && compile.compile
      ? (compile.compile as Record<string, unknown>)
      : compile;
  const inconsistent = Array.isArray(inner?.inconsistentBlocks)
    ? (inner?.inconsistentBlocks as unknown[]).map((x) => String(x))
    : [];
  if (inner?.skipped) {
    lines.push(`编译门控：跳过（${String(inner.message || inner.reason || "")}）`);
  } else if (inner) {
    const compiledOk =
      openness?.compiled_ok === true || (inner.ok === true && openness?.compiled_ok !== false);
    if (compiledOk && openness?.ok !== false) {
      lines.push("编译门控：**通过**");
    } else {
      const bits = inconsistent.slice(0, 8).map((b) => `\`${b}\``).join("、") || "见 compile 详情";
      lines.push(`编译门控：**未通过**（不一致块：${bits}）`);
      lines.push("编译失败时**不会**归档 .zap。");
    }
  }
  if (zap) {
    lines.push(`归档 .zap：\`${zap}\``);
  } else if (zapArchive?.skipped) {
    lines.push("归档 .zap：**跳过**" + (zapArchive.reason ? `（${String(zapArchive.reason)}）` : ""));
  } else if (zapArchive && zapArchive.ok === false) {
    lines.push("归档 .zap：**失败**" + (zapArchive.error ? `（${String(zapArchive.error)}）` : ""));
  }
  return lines.join("\n");
}

export function formatPlcProgress(detail: PlcJobDetail): string {
  const steps = detail.progress || [];
  const running = [...steps].reverse().find((s) => s.status === "running");
  const last = running || steps[steps.length - 1];
  if (!last?.title) return `PLC ${detail.status || "…"}`;
  const dur =
    typeof last.duration_ms === "number" && last.status !== "running"
      ? ` · ${last.duration_ms}ms`
      : "";
  return `${detail.status}: ${last.title}${dur}`;
}

