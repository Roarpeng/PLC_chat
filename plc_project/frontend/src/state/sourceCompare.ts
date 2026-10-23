/**
 * 按需源码对比（docs/15-lad2scl-silent-contract.md §3/§5）—— 取数与回退状态模块。
 *
 * - LAD→SCL 的原始工件（FlgNet XML / 1:1 直译 SCL / 归约追踪）只存服务端，
 *   仅当用户在块详情打开「查看原始源码」抽屉时才按块按 kind 拉取：
 *   GET /api/v1/plc/jobs/{job_id}/blocks/{block_name}/source?kind=flgnet_xml|literal_scl|ast_trace
 * - mock-first：404 / 400 / 网关不可达 / 无活跃 job 时一律回退内置电机启保停样例，
 *   只打一条 console.debug，绝不向 UI 抛错（前端行为契约 §5）。
 * - 活跃 job id 沿用 App.tsx 解析降级告警的既有规则：jobs 里挑 status=ready 且
 *   project_name 与当前画布一致者，否则第一个 ready，否则 null。
 */
import {
  listPlcJobs,
  requestPlc,
  type PlcJobSummary,
} from "../lib/plcGateway";

/** 源码工件类别（= API kind 查询参数） */
export type SourceKind = "flgnet_xml" | "literal_scl" | "ast_trace";

/** 抽屉顶部小型切换的展示顺序与文案 */
export const SOURCE_KINDS: Array<{ kind: SourceKind; label: string }> = [
  { kind: "flgnet_xml", label: "FlgNet XML" },
  { kind: "literal_scl", label: "直译 SCL" },
  { kind: "ast_trace", label: "归约追踪" },
];

export function isSourceKind(value: unknown): value is SourceKind {
  return value === "flgnet_xml" || value === "literal_scl" || value === "ast_trace";
}

/** 一份已就绪的源码工件（网关或 mock） */
export interface SourceArtifact {
  job_id: string | null;
  block_name: string;
  kind: SourceKind;
  content: string;
  /** gateway = 网关工件；mock = 内置示例回退 */
  origin: "gateway" | "mock";
}

/* ------------------------------------------------------------------ */
/* 内置 mock：电机启保停样例（后端工件未就绪时的开发回退）             */
/* ------------------------------------------------------------------ */

/** mock 样例块名（仅用于回退展示与测试断言） */
export const MOCK_BLOCK_NAME = "FB_Motor";

const MOCK_FLGNET_XML = `<?xml version="1.0" encoding="utf-8"?>
<!-- mock · FB_Motor Network 1「电机正向启保停」FlgNet 片段（网关工件未就绪时的开发回退） -->
<Document>
  <SW.Blocks.CompileUnit ID="1" CompositionName="Networks">
    <AttributeList>
      <NetworkNumber>1</NetworkNumber>
      <ProgrammingLanguage>LAD</ProgrammingLanguage>
    </AttributeList>
    <ObjectList>
      <FlgNet ID="10">
        <Parts>
          <Part Name="Contact" UId="20">
            <Negated>false</Negated>
          </Part>
          <Part Name="Contact" UId="21">
            <Negated>false</Negated>
          </Part>
          <Part Name="Or" UId="22" />
          <Part Name="Contact" UId="23">
            <Negated>true</Negated>
          </Part>
          <Part Name="Coil" UId="24">
            <Negated>false</Negated>
          </Part>
        </Parts>
        <Wires>
          <Wire UId="30">
            <Powerrail>10</Powerrail>
            <NameCon UId="20" Name="operand" />
          </Wire>
          <Wire UId="31">
            <IdentCon UId="40">
              <Address>i_bStartFwd</Address>
            </IdentCon>
            <NameCon UId="20" Name="operand" />
          </Wire>
          <Wire UId="32">
            <Powerrail>11</Powerrail>
            <NameCon UId="21" Name="operand" />
          </Wire>
          <Wire UId="33">
            <IdentCon UId="41">
              <Address>q_bMotorFwd</Address>
            </IdentCon>
            <NameCon UId="21" Name="operand" />
          </Wire>
          <Wire UId="34">
            <NameCon UId="20" Name="result" />
            <NameCon UId="22" Name="in1" />
          </Wire>
          <Wire UId="35">
            <NameCon UId="21" Name="result" />
            <NameCon UId="22" Name="in2" />
          </Wire>
          <Wire UId="36">
            <NameCon UId="22" Name="result" />
            <NameCon UId="23" Name="in" />
          </Wire>
          <Wire UId="37">
            <NameCon UId="23" Name="result" />
            <NameCon UId="24" Name="operand" />
          </Wire>
        </Wires>
        <Access>
          <Symbol UId="50">
            <Component Name="i_bStartFwd" />
          </Symbol>
        </Access>
      </FlgNet>
    </ObjectList>
  </SW.Blocks.CompileUnit>
</Document>`;

const MOCK_LITERAL_SCL = `// mock · FB_Motor literal 1:1 直译（按 FlgNet 布尔拓扑逐项翻译，未做语义重构）
// Network 1 电机正向启保停
#q_bMotorFwd := (#i_bStartFwd OR #q_bMotorFwd) AND NOT #i_bStop;
// Network 2 速度给定
#rSpeedSet := #i_rSpeedCmd;`;

const MOCK_AST_TRACE = `[block] FB_Motor
[net 1] Coil #q_bMotorFwd := (#i_bStartFwd OR #q_bMotorFwd) AND NOT #i_bStop
  step: UId=23.in 汇入 2 条 Wire -> 并联 OR 归约
  step: OR 分支含 q_bMotorFwd 回环 -> 自保（启保停保持语义）
  step: 串联取反触点 #i_bStop -> 串联 AND 归约
[net 2] Coil #rSpeedSet := #i_rSpeedCmd
  step: 单 Wire 直通，无归约`;

const MOCK_CONTENT: Record<SourceKind, string> = {
  flgnet_xml: MOCK_FLGNET_XML,
  literal_scl: MOCK_LITERAL_SCL,
  ast_trace: MOCK_AST_TRACE,
};

/** 取内置示例工件（不触网，不抛错） */
export function mockArtifact(blockName: string, kind: SourceKind): SourceArtifact {
  return {
    job_id: null,
    block_name: blockName,
    kind,
    content: MOCK_CONTENT[kind],
    origin: "mock",
  };
}

/* ------------------------------------------------------------------ */
/* 活跃 job 解析                                                       */
/* ------------------------------------------------------------------ */

/**
 * 从 jobs 列表挑当前活跃 PLC 解析作业 id：
 * status=ready 且 project_name 与画布一致者优先，否则第一个 ready；无 ready 返回 null。
 * 列表拉取失败同样返回 null（离线沙箱不阻塞）。
 */
export function pickActiveJobId(jobs: PlcJobSummary[], projectName: string): string | null {
  const ready = jobs.filter(
    (job) => job && job.status === "ready" && job.coverage && typeof job.coverage === "object",
  );
  if (!ready.length) return null;
  const wanted = (projectName || "").trim();
  const matched =
    wanted ? ready.find((job) => String(job?.project_name || "") === wanted) : undefined;
  return String((matched ?? ready[0])?.id || "") || null;
}

export async function resolveActivePlcJobId(projectName: string): Promise<string | null> {
  try {
    return pickActiveJobId(await listPlcJobs(10), projectName);
  } catch {
    return null;
  }
}

/* ------------------------------------------------------------------ */
/* 按需取源（mock-first）                                              */
/* ------------------------------------------------------------------ */

type SourceResponse = {
  job_id?: string;
  block_name?: string;
  kind?: string;
  content?: string;
};

/**
 * 拉取一个块的源码工件；任何失败（无 job / 404 / 400 / 网络错误）静默回退内置 mock。
 *
 * @param blockName 块名（URL path 段）
 * @param kind      工件类别
 * @param opts.jobId      已解析的活跃 job id（缺省时用 projectName 现场解析）
 * @param opts.projectName  解析活跃 job 时匹配的画布工程名
 */
export async function fetchSourceArtifact(
  blockName: string,
  kind: SourceKind,
  opts?: { jobId?: string | null; projectName?: string },
): Promise<SourceArtifact> {
  let jobId = opts?.jobId ?? null;
  if (jobId === null && opts?.projectName !== undefined) {
    jobId = await resolveActivePlcJobId(opts.projectName);
  }
  if (!jobId) {
    console.debug(
      `[source-compare] 无活跃 PLC 作业，${blockName}/${kind} 回退内置示例`,
    );
    return mockArtifact(blockName, kind);
  }

  try {
    const data = await requestPlc<SourceResponse>(
      `/api/v1/plc/jobs/${encodeURIComponent(jobId)}` +
        `/blocks/${encodeURIComponent(blockName)}/source` +
        `?kind=${encodeURIComponent(kind)}`,
      { signal: AbortSignal.timeout?.(8000) },
    );
    if (typeof data?.content === "string" && data.content.length > 0) {
      return {
        job_id: String(data.job_id ?? jobId),
        block_name: String(data.block_name ?? blockName),
        kind: isSourceKind(data.kind) ? data.kind : kind,
        content: data.content,
        origin: "gateway",
      };
    }
    throw new Error("空 content");
  } catch (err) {
    // 404 / 400 / 超时 / 网关不可达：一条 debug 日志 + mock 回退，不打扰用户
    console.debug(
      `[source-compare] ${blockName}/${kind} 拉取失败（${
        err instanceof Error ? err.message : String(err)
      }），回退内置示例`,
    );
    return mockArtifact(blockName, kind);
  }
}
