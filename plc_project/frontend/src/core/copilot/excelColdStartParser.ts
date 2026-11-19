import type {
  DriverMotherClass,
  GhostGraphTransaction,
  SpatialInstanceNode,
  SpatialPort,
  TemporalStepHyperEdge,
} from '../ir/afHyperGraph.types';
import { MOTHER_CLASS_REGISTRY } from '../ir/motherClassRegistry';
import { createDefaultAfStudioWorkspace } from '../ir/seedHyperGraphs';

export interface ParseColdStartOptions {
  stationId?: string;
  existingNodes?: SpatialInstanceNode[];
  startStepNo?: number;
}

export interface DemoExcelColdStartPayload {
  timingTableText: string;
  ioTableText: string;
  transaction: GhostGraphTransaction;
}

interface RawTimingRow {
  stepNo?: number;
  title: string;
  actuator: string;
  driverRaw: string;
  dbRaw: string;
  action: string;
  targetState: string;
  waitDesc: string;
  fromRaw: string;
  branchRaw: string;
}

interface RawIoRow {
  actuator: string;
  instanceDb: string;
  driverRaw: string;
  cohesiveIoMap: Record<string, string>;
  hasPartPresent: boolean;
}

function normalizeHeaderKey(raw: string): string {
  return raw
    .trim()
    .toLowerCase()
    .replace(/[\s_\-()（）:：/\\|]+/g, '');
}

function normalizeLookupKey(raw: string): string {
  return raw.trim().toLowerCase().replace(/\s+/g, '');
}

function sanitizeIdent(raw: string): string {
  const ascii = raw.replace(/[^A-Za-z0-9_]/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '');
  return ascii || 'Inst';
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function stripBomAndNormalizeLines(text: string): string {
  return text.replace(/^\uFEFF/, '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim();
}

/** 解析带引号的分隔符文本（CSV / TSV / 分号） */
function parseDelimitedRows(text: string, delimiter: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = '';
  let inQuotes = false;

  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          cell += '"';
          i += 1;
        } else {
          inQuotes = false;
        }
      } else {
        cell += ch;
      }
      continue;
    }

    if (ch === '"') {
      inQuotes = true;
    } else if (ch === delimiter) {
      row.push(cell.trim());
      cell = '';
    } else if (ch === '\n') {
      row.push(cell.trim());
      if (row.some((item) => item.length > 0)) {
        rows.push(row);
      }
      row = [];
      cell = '';
    } else {
      cell += ch;
    }
  }

  row.push(cell.trim());
  if (row.some((item) => item.length > 0)) {
    rows.push(row);
  }
  return rows;
}

function isMarkdownSeparatorLine(line: string): boolean {
  const trimmed = line.trim();
  if (!trimmed.includes('|') || !trimmed.includes('-')) return false;
  const cells = trimmed
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((c) => c.trim());
  return cells.length > 0 && cells.every((c) => /^:?-{2,}:?$/.test(c));
}

function parseMarkdownTableRows(lines: string[]): string[][] {
  const rows: string[][] = [];
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || !trimmed.includes('|') || isMarkdownSeparatorLine(trimmed)) continue;
    const rawCells = trimmed.replace(/^\|/, '').replace(/\|$/, '').split('|');
    const cells = rawCells.map((c) => c.trim());
    if (cells.some((c) => c.length > 0)) {
      rows.push(cells);
    }
  }
  return rows;
}

function extractJsonArray(rawText: string): Record<string, unknown>[] | null {
  const trimmed = rawText.trim();
  if (!trimmed.startsWith('[') && !trimmed.startsWith('{')) return null;

  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    return null;
  }

  if (Array.isArray(parsed)) {
    return parsed.filter(isRecord);
  }
  if (isRecord(parsed)) {
    const listCandidate = parsed.rows ?? parsed.data ?? parsed.steps ?? parsed.items ?? parsed.timing ?? parsed.io;
    if (Array.isArray(listCandidate)) {
      return listCandidate.filter(isRecord);
    }
  }
  return null;
}

function detectDelimiter(headerLine: string): string {
  let inQuotes = false;
  let tabs = 0;
  let commas = 0;
  let semis = 0;
  for (let i = 0; i < headerLine.length; i += 1) {
    const ch = headerLine[i];
    if (ch === '"') {
      inQuotes = !inQuotes;
    } else if (!inQuotes) {
      if (ch === '\t') tabs += 1;
      else if (ch === ',') commas += 1;
      else if (ch === ';') semis += 1;
    }
  }
  if (tabs > 0) return '\t';
  if (commas > 0) return ',';
  if (semis > 0) return ';';
  return '\t';
}

function parseGenericRecords(rawText: string): Record<string, string>[] {
  const clean = stripBomAndNormalizeLines(rawText);
  if (!clean) return [];

  const jsonArray = extractJsonArray(clean);
  if (jsonArray) {
    return jsonArray.map((obj) => {
      const rec: Record<string, string> = {};
      for (const [k, v] of Object.entries(obj)) {
        if (v !== undefined && v !== null) {
          rec[k] = String(v).trim();
        }
      }
      return rec;
    });
  }

  const nonEmptyLines = clean.split('\n').filter((line) => line.trim().length > 0);
  if (nonEmptyLines.length === 0) return [];

  const isMarkdown =
    nonEmptyLines.length >= 2 &&
    nonEmptyLines[0].includes('|') &&
    (isMarkdownSeparatorLine(nonEmptyLines[1]) ||
      nonEmptyLines.every((line) => line.trim().startsWith('|')));

  const matrix = isMarkdown
    ? parseMarkdownTableRows(nonEmptyLines)
    : parseDelimitedRows(clean, detectDelimiter(nonEmptyLines[0]));

  if (matrix.length < 2) return [];
  const headers = matrix[0];
  const records: Record<string, string>[] = [];

  for (let i = 1; i < matrix.length; i += 1) {
    const row = matrix[i];
    if (row.every((cell) => cell.trim().length === 0)) continue;
    const rec: Record<string, string> = {};
    headers.forEach((h, idx) => {
      const key = h.trim();
      if (key) {
        rec[key] = (row[idx] ?? '').trim();
      }
    });
    records.push(rec);
  }
  return records;
}

type TimingField =
  | 'stepNo'
  | 'title'
  | 'fromNode'
  | 'actuator'
  | 'driverClass'
  | 'instanceDb'
  | 'action'
  | 'targetState'
  | 'waitDesc'
  | 'branch';

function matchTimingField(header: string): TimingField | null {
  const norm = normalizeHeaderKey(header);
  if (!norm) return null;

  if (
    norm === '步号' ||
    norm === '步序' ||
    norm === '序号' ||
    norm === 'step' ||
    norm === 'stepno' ||
    norm === 'stepnum' ||
    norm === 'stepid' ||
    norm === '步号stepstepno'
  ) {
    return 'stepNo';
  }
  if (
    norm === '工步名称' ||
    norm === '步名称' ||
    norm === '步骤名称' ||
    norm === '工步' ||
    norm === 'title' ||
    norm === 'steptitle' ||
    norm === 'stepname' ||
    norm === '工步名称title'
  ) {
    return 'title';
  }
  if (
    norm === '前序机构' ||
    norm === '前序' ||
    norm === '前置机构' ||
    norm === '来源机构' ||
    norm === '来源' ||
    norm === '触发源' ||
    norm === 'from' ||
    norm === 'fromnode' ||
    norm === 'predecessor' ||
    norm === '前序机构from'
  ) {
    return 'fromNode';
  }
  if (
    norm === '机构' ||
    norm === '执行器' ||
    norm === '机构执行器' ||
    norm === '机构名称' ||
    norm === '执行器名称' ||
    norm === '设备' ||
    norm === '设备名称' ||
    norm === 'actuator' ||
    norm === 'device' ||
    norm === 'devicename' ||
    norm === 'target' ||
    norm === 'targetnode' ||
    norm === '机构执行器actuatordevice'
  ) {
    return 'actuator';
  }
  if (
    norm === '母版' ||
    norm === '驱动类型' ||
    norm === '驱动母版' ||
    norm === '母版类型' ||
    norm === '母版驱动类型' ||
    norm === 'driver' ||
    norm === 'driverclass' ||
    norm === 'motherclass' ||
    norm === '母版驱动类型driverdriverclass'
  ) {
    return 'driverClass';
  }
  if (
    norm === '位号' ||
    norm === 'db' ||
    norm === '位号db' ||
    norm === '背景数据块' ||
    norm === '实例db' ||
    norm === 'instancedb'
  ) {
    return 'instanceDb';
  }
  if (
    norm === '动作' ||
    norm === '工艺动作' ||
    norm === '动作名称' ||
    norm === 'action' ||
    norm === 'actionlabel' ||
    norm === 'method' ||
    norm === 'methodid' ||
    norm === 'command' ||
    norm === '动作action'
  ) {
    return 'action';
  }
  if (
    norm === '目标状态' ||
    norm === '目标离散状态' ||
    norm === '离散状态' ||
    norm === '状态' ||
    norm === 'targetstate' ||
    norm === 'targetdiscretestate' ||
    norm === 'state' ||
    norm === '目标状态targetstate'
  ) {
    return 'targetState';
  }
  if (
    norm === '完成条件' ||
    norm === '等待条件' ||
    norm === '完成谓词' ||
    norm === 'wait' ||
    norm === 'waitdesc' ||
    norm === 'waitdescription' ||
    norm === 'waitpredicate' ||
    norm === 'condition' ||
    norm === '完成条件waitwaitdesc'
  ) {
    return 'waitDesc';
  }
  if (
    norm === '分支' ||
    norm === '分支条件' ||
    norm === '分支谓词' ||
    norm === '判定' ||
    norm === 'branch' ||
    norm === 'branchpredicate' ||
    norm === '分支branch'
  ) {
    return 'branch';
  }

  // Fallback substring checks (order matters: check fromNode before actuator)
  if (norm.includes('前序') || norm.startsWith('from')) return 'fromNode';
  if (norm.includes('步号') || norm.includes('stepno')) return 'stepNo';
  if (norm.includes('工步') || norm.includes('title')) return 'title';
  if (norm.includes('机构') || norm.includes('执行器') || norm.includes('actuator') || norm.includes('device')) {
    return 'actuator';
  }
  if (norm.includes('母版') || norm.includes('driver')) return 'driverClass';
  if (norm.includes('目标状态') || norm.includes('targetstate')) return 'targetState';
  if (norm.includes('完成') || norm.includes('wait')) return 'waitDesc';
  if (norm.includes('动作') || norm.includes('action')) return 'action';
  if (norm.includes('分支') || norm.includes('branch')) return 'branch';
  if (norm.includes('位号') || norm.includes('instancedb')) return 'instanceDb';

  return null;
}

type IoField =
  | 'actuator'
  | 'instanceDb'
  | 'driverClass'
  | 'diHome'
  | 'diWork'
  | 'doWork'
  | 'diPartPresent'
  | 'cabinetTerminal'
  | 'diClosed'
  | 'diOpened'
  | 'doClose'
  | 'doOpen';

function matchIoField(header: string): IoField | null {
  const norm = normalizeHeaderKey(header);
  if (!norm) return null;

  if (
    norm === '机构' ||
    norm === '执行器' ||
    norm === '设备' ||
    norm === '机构名称' ||
    norm === '执行器名称' ||
    norm === '设备名称' ||
    norm === 'device' ||
    norm === 'devicename' ||
    norm === 'actuator' ||
    norm === 'title' ||
    norm === 'name' ||
    norm === '机构device'
  ) {
    return 'actuator';
  }
  if (
    norm === '位号' ||
    norm === 'db' ||
    norm === '位号db' ||
    norm === '背景数据块' ||
    norm === '实例db' ||
    norm === 'instancedb' ||
    norm === 'tag'
  ) {
    return 'instanceDb';
  }
  if (norm === '母版' || norm === '驱动类型' || norm === 'driver' || norm === 'driverclass') {
    return 'driverClass';
  }
  if (norm === '原位输入' || norm === '原位磁开' || norm === '原位反馈' || norm === 'dihome' || norm === 'homedi' || norm === '原位输入dihome') {
    return 'diHome';
  }
  if (norm === '动位输入' || norm === '动位磁开' || norm === '工作位输入' || norm === '动位反馈' || norm === 'diwork' || norm === 'workdi' || norm === '动位输入diwork') {
    return 'diWork';
  }
  if (norm === '输出点' || norm === '控制输出' || norm === '电磁阀输出' || norm === '电磁阀' || norm === 'dowork' || norm === 'workdo' || norm === 'do' || norm === '输出点dowork') {
    return 'doWork';
  }
  if (
    norm === '夹爪带料' ||
    norm === '带料检测' ||
    norm === '带料光电' ||
    norm === 'dipartpresent' ||
    norm === 'partpresent' ||
    norm === '夹爪带料dipartpresent'
  ) {
    return 'diPartPresent';
  }
  if (
    norm === '电柜端子' ||
    norm === '端子' ||
    norm === '端子号' ||
    norm === '接线端子' ||
    norm === 'terminal' ||
    norm === 'cabinetterminal' ||
    norm === '电柜端子terminal'
  ) {
    return 'cabinetTerminal';
  }
  if (norm === 'diclosed' || norm === '夹紧输入' || norm === '闭合输入') return 'diClosed';
  if (norm === 'diopened' || norm === '张开输入' || norm === '释放输入') return 'diOpened';
  if (norm === 'doclose' || norm === '闭合输出' || norm === '夹紧输出') return 'doClose';
  if (norm === 'doopen' || norm === '张开输出' || norm === '释放输出') return 'doOpen';

  if (norm.includes('原位')) return 'diHome';
  if (norm.includes('动位')) return 'diWork';
  if (norm.includes('带料') || norm.includes('partpresent')) return 'diPartPresent';
  if (norm.includes('端子') || norm.includes('terminal')) return 'cabinetTerminal';
  if (norm.includes('输出')) return 'doWork';
  if (norm.includes('位号') || norm.includes('db')) return 'instanceDb';
  if (norm.includes('机构') || norm.includes('设备') || norm.includes('device') || norm.includes('actuator')) {
    return 'actuator';
  }
  return null;
}

function parseStepNumber(raw: string): number | undefined {
  if (!raw) return undefined;
  const m = raw.match(/\d+/);
  if (!m) return undefined;
  const n = Number.parseInt(m[0], 10);
  return Number.isFinite(n) ? n : undefined;
}

function parseTimingRows(rawText: string): RawTimingRow[] {
  const records = parseGenericRecords(rawText);
  const rows: RawTimingRow[] = [];

  for (const rec of records) {
    let stepNo: number | undefined;
    let title = '';
    let actuator = '';
    let driverRaw = '';
    let dbRaw = '';
    let action = '';
    let targetState = '';
    let waitDesc = '';
    let fromRaw = '';
    let branchRaw = '';

    for (const [k, v] of Object.entries(rec)) {
      const field = matchTimingField(k);
      if (!field) continue;
      if (field === 'stepNo') stepNo = parseStepNumber(v);
      else if (field === 'title') title = v;
      else if (field === 'actuator') actuator = v;
      else if (field === 'driverClass') driverRaw = v;
      else if (field === 'instanceDb') dbRaw = v;
      else if (field === 'action') action = v;
      else if (field === 'targetState') targetState = v;
      else if (field === 'waitDesc') waitDesc = v;
      else if (field === 'fromNode') fromRaw = v;
      else if (field === 'branch') branchRaw = v;
    }

    if (!actuator && !action && !title) continue;
    rows.push({
      stepNo,
      title: title || action || actuator,
      actuator: actuator || title || '未命名机构',
      driverRaw,
      dbRaw,
      action: action || title || '执行动作',
      targetState,
      waitDesc,
      fromRaw,
      branchRaw,
    });
  }

  return rows;
}

function parseIoRows(rawText?: string): RawIoRow[] {
  if (!rawText || !rawText.trim()) return [];
  const records = parseGenericRecords(rawText);
  const rows: RawIoRow[] = [];

  for (const rec of records) {
    let actuator = '';
    let instanceDb = '';
    let driverRaw = '';
    const cohesiveIoMap: Record<string, string> = {};
    let hasPartPresent = false;

    for (const [k, v] of Object.entries(rec)) {
      if (!v) continue;
      const field = matchIoField(k);
      if (!field) continue;
      if (field === 'actuator') actuator = v;
      else if (field === 'instanceDb') instanceDb = v;
      else if (field === 'driverClass') driverRaw = v;
      else if (field === 'diPartPresent') {
        cohesiveIoMap.diPartPresent = v;
        hasPartPresent = true;
      } else {
        cohesiveIoMap[field] = v;
      }
    }

    if (!actuator && !instanceDb && Object.keys(cohesiveIoMap).length === 0) continue;
    rows.push({
      actuator: actuator || instanceDb,
      instanceDb,
      driverRaw,
      cohesiveIoMap,
      hasPartPresent,
    });
  }

  return rows;
}

function inferDriverClass(
  driverRaw: string,
  title: string,
  ioRow?: RawIoRow
): DriverMotherClass {
  const rawTrim = (driverRaw || ioRow?.driverRaw || '').trim();
  if (rawTrim in MOTHER_CLASS_REGISTRY) {
    return rawTrim as DriverMotherClass;
  }

  const combined = `${rawTrim} ${title}`.toLowerCase();
  if (/axis|servo|stepper|vfd|伺服|电机轴|直线模组|转台|分度盘|轴/.test(combined)) {
    return 'FB_AF_AxisMotion';
  }
  if (/grip|vacuum|clamp|夹爪|抓手|吸盘/.test(combined) || ioRow?.hasPartPresent) {
    return 'FB_AF_Gripper';
  }
  if (/vision|camera|sensor|laser|barcode|scanner|rfid|视觉|相机|测高|激光|读码|扫码|光电|传感器/.test(combined)) {
    return 'FB_AF_VisionSensor';
  }
  if (/input|输入边界|station_input/.test(combined)) {
    return 'STATION_INPUT_PORT';
  }
  if (/output|输出边界|station_output/.test(combined)) {
    return 'STATION_OUTPUT_PORT';
  }
  return 'FB_AF_Actuator2Pos';
}

function defaultDbPrefix(driverClass: DriverMotherClass): string {
  switch (driverClass) {
    case 'FB_AF_AxisMotion':
      return 'Axis';
    case 'FB_AF_Gripper':
      return 'Grip';
    case 'FB_AF_VisionSensor':
      return 'Cam';
    default:
      return 'Cyl';
  }
}

function buildUniqueNodeId(
  stationId: string,
  dbName: string,
  title: string,
  usedIds: Set<string>,
  seqIndex: number
): string {
  let base = '';
  if (/reject|剔除/i.test(`${dbName} ${title}`)) {
    base = `INST_${stationId}_REJECT`;
  } else {
    const dbTail = dbName.replace(new RegExp(`^DB_${stationId}_`, 'i'), '').replace(/^DB_/i, '');
    const cleanTail = sanitizeIdent(dbTail || title).toUpperCase();
    base = `INST_${stationId}_${cleanTail !== 'INST' ? cleanTail : `DEV_${seqIndex}`}`;
  }
  if (!usedIds.has(base)) {
    usedIds.add(base);
    return base;
  }
  let suffix = 2;
  while (usedIds.has(`${base}_${suffix}`)) {
    suffix += 1;
  }
  const unique = `${base}_${suffix}`;
  usedIds.add(unique);
  return unique;
}

function buildUniqueDbName(
  stationId: string,
  explicitDb: string,
  driverClass: DriverMotherClass,
  title: string,
  usedDbs: Set<string>,
  seqIndex: number
): string {
  const cleanExplicit = explicitDb.trim();
  if (cleanExplicit && !usedDbs.has(cleanExplicit.toLowerCase())) {
    usedDbs.add(cleanExplicit.toLowerCase());
    return cleanExplicit;
  }
  const prefix = defaultDbPrefix(driverClass);
  const asciiHint = sanitizeIdent(title);
  const candidateBase =
    asciiHint && asciiHint !== 'Inst'
      ? `DB_${stationId}_${asciiHint}`
      : `DB_${stationId}_${prefix}${seqIndex}`;
  if (!usedDbs.has(candidateBase.toLowerCase())) {
    usedDbs.add(candidateBase.toLowerCase());
    return candidateBase;
  }
  let suffix = 2;
  while (usedDbs.has(`${candidateBase}_${suffix}`.toLowerCase())) {
    suffix += 1;
  }
  const unique = `${candidateBase}_${suffix}`;
  usedDbs.add(unique.toLowerCase());
  return unique;
}

function formatIoSummaryText(ioMap: Record<string, string>, fallback: string): string {
  const parts: string[] = [];
  if (ioMap.diHome) parts.push(`原位 ${ioMap.diHome}`);
  if (ioMap.diWork) parts.push(`动位 ${ioMap.diWork}`);
  if (ioMap.diClosed) parts.push(`闭合 ${ioMap.diClosed}`);
  if (ioMap.diOpened) parts.push(`张开 ${ioMap.diOpened}`);
  if (ioMap.doWork) parts.push(`阀 ${ioMap.doWork}`);
  if (ioMap.doClose) parts.push(`闭合阀 ${ioMap.doClose}`);
  if (ioMap.doOpen) parts.push(`张开阀 ${ioMap.doOpen}`);
  if (ioMap.diPartPresent) parts.push(`带料 ${ioMap.diPartPresent}`);
  if (ioMap.cabinetTerminal) parts.push(`端子 ${ioMap.cabinetTerminal}`);
  return parts.length > 0 ? `EPLAN导入: ${parts.join(' / ')}` : fallback;
}

function normalizeBranchPredicate(raw: string): TemporalStepHyperEdge['branchPredicate'] {
  const s = raw.trim().toUpperCase();
  if (!s) return 'ALWAYS';
  if (/NG|FAIL|FALSE|超差|不良|异常/.test(s)) return 'NG';
  if (/OK|PASS|TRUE|合格|良品|正常/.test(s)) return 'OK';
  return 'ALWAYS';
}

function selectOutPortForBranch(
  node: SpatialInstanceNode | undefined,
  branch: TemporalStepHyperEdge['branchPredicate']
): string {
  if (!node || node.outPorts.length === 0) return 'OUT_DONE';
  const seqPorts = node.outPorts.filter((p) => p.type === 'SEQ');
  const candidates = seqPorts.length > 0 ? seqPorts : node.outPorts;

  if (branch === 'NG') {
    const ngPort = candidates.find((p) => p.id === 'OUT_NG' || /NG/i.test(p.label));
    if (ngPort) return ngPort.id;
  }
  if (branch === 'OK') {
    const okPort = candidates.find((p) => p.id === 'OUT_OK' || /OK|合格/i.test(p.label));
    if (okPort) return okPort.id;
  }
  return candidates[0].id;
}

function compileActionInvocation(
  targetNode: SpatialInstanceNode,
  actionText: string,
  explicitTargetState: string,
  waitDesc: string
): {
  methodId: string;
  actionLabel: string;
  targetDiscreteState: string;
  sclStatement: string;
  waitPredicateScl: string;
  waitDescription: string;
} {
  const db = targetNode.instanceDb;
  const actLower = actionText.toLowerCase();
  const driverClass = targetNode.driverClass;

  let methodId = 'ExecuteStep';
  let targetDiscreteState = explicitTargetState.trim();
  let sclStatement = `#${db}.Execute();`;
  let waitPredicateScl = `"${db}".o_bDone`;

  if (driverClass === 'FB_AF_Actuator2Pos') {
    const isExtendAndRetract =
      (/伸出|推出|剔除|吹气/.test(actionText) && /退回|缩回|回原/.test(actionText)) ||
      /extendandretract|pushandretract/i.test(actLower);

    if (isExtendAndRetract) {
      methodId = 'ExtendAndRetract';
      targetDiscreteState = targetDiscreteState || 'AtHome';
      sclStatement = `#${db}.ExtendAndRetract();`;
      waitPredicateScl = `"${db}".o_bAtHome AND "${db}".o_bCycleDone`;
    } else if (/缩回|退回|回原|复位|顶升原位|retract|home/i.test(actLower)) {
      methodId = 'RetractHome';
      targetDiscreteState = targetDiscreteState || 'AtHome';
      sclStatement = `#${db}.RetractHome();`;
      waitPredicateScl = targetNode.cohesiveIoMap.diHome
        ? `"${db}".o_bAtHome (* ${targetNode.cohesiveIoMap.diHome} *)`
        : `"${db}".o_bAtHome`;
    } else if (/保压|稳压|延时|等待|dwell|hold/i.test(actLower)) {
      methodId = 'DwellHold';
      targetDiscreteState = targetDiscreteState || 'AtWork';
      sclStatement = `#${db}.HoldWork();`;
      waitPredicateScl = `"${db}".o_bAtWork AND #tonDwell.Q`;
    } else {
      methodId = 'ExtendWork';
      targetDiscreteState = targetDiscreteState || 'AtWork';
      sclStatement = `#${db}.ExtendWork();`;
      waitPredicateScl = targetNode.cohesiveIoMap.diWork
        ? `"${db}".o_bAtWork (* ${targetNode.cohesiveIoMap.diWork} *)`
        : `"${db}".o_bAtWork`;
    }
  } else if (driverClass === 'FB_AF_Gripper') {
    if (/张开|松开|释放|放料|open|release/i.test(actLower)) {
      methodId = 'GripOpen';
      targetDiscreteState = targetDiscreteState || 'Opened';
      sclStatement = `#${db}.OpenGrip();`;
      waitPredicateScl = `"${db}".o_bOpened`;
    } else {
      methodId = 'GripClose';
      targetDiscreteState = targetDiscreteState || 'Closed';
      sclStatement = `#${db}.CloseGrip();`;
      waitPredicateScl = `"${db}".o_bClosed`;
    }
  } else if (driverClass === 'FB_AF_AxisMotion') {
    const posMatch = actionText.match(/(-?\d+(?:\.\d+)?)\s*mm/i) ?? targetDiscreteState.match(/(-?\d+(?:\.\d+)?)$/);
    if (/待机|回原|归零|home/i.test(actLower)) {
      const pos = posMatch ? posMatch[1] : '0';
      methodId = 'MoveHome';
      targetDiscreteState = targetDiscreteState || `Pos_Home_${pos}`;
      sclStatement = `#${db}.MoveAbs(${pos}.0);`.replace('.0.0', '.0');
      waitPredicateScl = `"${db}".o_bInPos`;
    } else if (/抛料|剔除|reject|ng/i.test(actLower)) {
      const pos = posMatch ? posMatch[1] : '410';
      methodId = 'MoveReject';
      targetDiscreteState = targetDiscreteState || `Pos_Reject_${pos}`;
      sclStatement = `#${db}.MoveAbs(${pos}.0);`.replace('.0.0', '.0');
      waitPredicateScl = `"${db}".o_bInPos AND (ABS("${db}".o_rActPos - ${pos}.0) < 0.05)`;
    } else if (/取料|pick/i.test(actLower)) {
      const pos = posMatch ? posMatch[1] : '120';
      methodId = 'MovePick';
      targetDiscreteState = targetDiscreteState || `Pos_Pick_${pos}`;
      sclStatement = `#${db}.MoveAbs(${pos}.0);`.replace('.0.0', '.0');
      waitPredicateScl = `"${db}".o_bInPos`;
    } else {
      const pos = posMatch ? posMatch[1] : '245';
      methodId = 'MovePress';
      targetDiscreteState = targetDiscreteState || `Pos_Work_${pos}`;
      sclStatement = `#${db}.MoveAbs(${pos}.0);`.replace('.0.0', '.0');
      waitPredicateScl = `"${db}".o_bInPos`;
    }
  } else if (driverClass === 'FB_AF_VisionSensor') {
    methodId = 'TrigInspect';
    targetDiscreteState = targetDiscreteState || 'Pass_OK';
    sclStatement = `#${db}.TriggerCam();`;
    waitPredicateScl = `"${db}".o_bDone`;
  } else if (driverClass === 'STATION_OUTPUT_PORT') {
    methodId = 'ReleaseNext';
    targetDiscreteState = targetDiscreteState || 'CycleDone';
    sclStatement = 'o_bCycleDone := TRUE;';
    waitPredicateScl = 'i_bDownstreamAck';
  }

  return {
    methodId,
    actionLabel: actionText,
    targetDiscreteState: targetDiscreteState || targetNode.discreteStates[targetNode.discreteStates.length - 1] || 'AtWork',
    sclStatement,
    waitPredicateScl,
    waitDescription: waitDesc || `${actionText} 完成`,
  };
}

function findMatchingNode(
  query: string,
  dbHint: string,
  nodes: SpatialInstanceNode[]
): SpatialInstanceNode | undefined {
  const qNorm = normalizeLookupKey(query);
  const dbNorm = normalizeLookupKey(dbHint);

  if (query) {
    const byId = nodes.find((n) => n.id === query.trim() || normalizeLookupKey(n.id) === qNorm);
    if (byId) return byId;
  }
  if (dbNorm) {
    const byDb = nodes.find((n) => normalizeLookupKey(n.instanceDb) === dbNorm);
    if (byDb) return byDb;
  }
  if (qNorm) {
    const byDbAsActuator = nodes.find((n) => normalizeLookupKey(n.instanceDb) === qNorm);
    if (byDbAsActuator) return byDbAsActuator;

    const byTitle = nodes.find((n) => normalizeLookupKey(n.title) === qNorm);
    if (byTitle) return byTitle;
  }
  return undefined;
}

function findMatchingIoRow(
  actuator: string,
  dbHint: string,
  ioRows: RawIoRow[]
): RawIoRow | undefined {
  const aNorm = normalizeLookupKey(actuator);
  const dbNorm = normalizeLookupKey(dbHint);

  if (dbNorm) {
    const byDb = ioRows.find((r) => normalizeLookupKey(r.instanceDb) === dbNorm);
    if (byDb) return byDb;
  }
  if (aNorm) {
    const byActuator = ioRows.find((r) => normalizeLookupKey(r.actuator) === aNorm);
    if (byActuator) return byActuator;

    const byDbAsActuator = ioRows.find((r) => normalizeLookupKey(r.instanceDb) === aNorm);
    if (byDbAsActuator) return byDbAsActuator;
  }
  return undefined;
}

/**
 * 解析机械《动作时序表》与电气《EPLAN IO 表》（支持 TSV / CSV / Markdown / JSON），
 * 严格遵循 AF-Studio v5 正交超图规则：同一执行器多次往复动作去重为唯一 SpatialInstanceNode，
 * 多次动作分别编译为 addedTemporalSteps 虚影步序超边。
 */
export function parseColdStartTables(
  timingTableText: string,
  ioTableText?: string,
  options?: ParseColdStartOptions
): GhostGraphTransaction {
  const stationId = options?.stationId ?? 'ST30';
  const existingNodes = options?.existingNodes ?? [];
  const startStepNo = options?.startStepNo ?? 10;

  const timingRows = parseTimingRows(timingTableText);
  const ioRows = parseIoRows(ioTableText);

  const usedIds = new Set<string>(existingNodes.map((n) => n.id));
  const usedDbs = new Set<string>(existingNodes.map((n) => n.instanceDb.toLowerCase()));

  const addedNodes: SpatialInstanceNode[] = [];
  const addedTemporalSteps: TemporalStepHyperEdge[] = [];
  const warnings: string[] = [];

  if (timingRows.length === 0 && ioRows.length === 0) {
    return {
      txId: `TX_COLDSTART_${stationId}_EMPTY`,
      stationId,
      summary: '未从输入文本中识别到有效工步或 IO 映射行',
      addedNodes: [],
      addedGuardEdges: [],
      addedTemporalSteps: [],
      verificationPassed: false,
      verifierWarnings: ['请检查表头是否包含「工步/机构/动作」或「机构/位号/IO点」字段。'],
    };
  }

  let nextAutoStepNo = startStepNo;
  let lastStepTargetNode: SpatialInstanceNode | undefined = existingNodes.find(
    (n) => n.role === 'BOUNDARY_IN'
  );

  const usedStepNos = new Set<number>();

  timingRows.forEach((row, rowIdx) => {
    const matchedIo = findMatchingIoRow(row.actuator, row.dbRaw, ioRows);

    // 1. Lookup existing node first, then already-created addedNodes (strictly deduplicated!)
    let targetNode =
      findMatchingNode(row.actuator, row.dbRaw || matchedIo?.instanceDb || '', existingNodes) ??
      findMatchingNode(row.actuator, row.dbRaw || matchedIo?.instanceDb || '', addedNodes);

    if (!targetNode) {
      const driverClass = inferDriverClass(row.driverRaw, row.actuator, matchedIo);
      const spec = MOTHER_CLASS_REGISTRY[driverClass] ?? MOTHER_CLASS_REGISTRY.FB_AF_Actuator2Pos;
      const dbName = buildUniqueDbName(
        stationId,
        row.dbRaw || matchedIo?.instanceDb || '',
        driverClass,
        row.actuator,
        usedDbs,
        addedNodes.length + 1
      );
      const nodeId = buildUniqueNodeId(
        stationId,
        dbName,
        row.actuator,
        usedIds,
        addedNodes.length + 1
      );

      const cohesiveIoMap: Record<string, string> = matchedIo ? { ...matchedIo.cohesiveIoMap } : {};
      const ioSummaryText = formatIoSummaryText(cohesiveIoMap, spec.defaultIoSummaryText);
      const col = addedNodes.length % 3;
      const lane = Math.floor(addedNodes.length / 3);

      targetNode = {
        id: nodeId,
        role: spec.role,
        title: row.actuator,
        driverClass,
        instanceDb: dbName,
        position: { x: 380 + col * 280, y: 120 + lane * 185 },
        isPinned: false,
        ...(spec.supportsPartPresentSensor || matchedIo?.hasPartPresent
          ? { hasPartPresentSensor: true }
          : {}),
        discreteStates: [...spec.defaultDiscreteStates],
        initialHomeState: spec.initialHomeState,
        cohesiveIoMap,
        ioSummaryText,
        theme: spec.theme,
        inPorts: spec.defaultInPorts.map((p: SpatialPort) => ({ ...p })),
        outPorts: spec.defaultOutPorts.map((p: SpatialPort) => ({ ...p })),
      };
      addedNodes.push(targetNode);
    }

    // 2. Resolve stepNo
    let stepNo = row.stepNo ?? nextAutoStepNo;
    while (usedStepNos.has(stepNo)) {
      stepNo += 10;
    }
    usedStepNos.add(stepNo);
    nextAutoStepNo = stepNo + 10;

    // 3. Resolve fromNode & fromPort
    const branchPredicate = normalizeBranchPredicate(row.branchRaw);
    const allKnownNodes = [...existingNodes, ...addedNodes];
    let fromNodeObj: SpatialInstanceNode | undefined;

    if (row.fromRaw) {
      fromNodeObj = findMatchingNode(row.fromRaw, '', allKnownNodes);
    }
    if (!fromNodeObj) {
      fromNodeObj = lastStepTargetNode;
    }

    const fromNodeId = fromNodeObj?.id ?? `BOUND_IN_${stationId}`;
    const fromPortId = fromNodeObj
      ? selectOutPortForBranch(fromNodeObj, branchPredicate)
      : 'OUT_PART_ARRIVED';

    // 4. Compile invocation
    const compiled = compileActionInvocation(
      targetNode,
      row.action,
      row.targetState,
      row.waitDesc
    );

    if (
      !targetNode.discreteStates.includes(compiled.targetDiscreteState) &&
      addedNodes.includes(targetNode)
    ) {
      targetNode.discreteStates.push(compiled.targetDiscreteState);
    }

    const execPortId = targetNode.inPorts.find((p) => p.type === 'SEQ')?.id ?? 'IN_EXEC';

    addedTemporalSteps.push({
      id: `GW_EXCEL_${stationId}_S${stepNo}_${rowIdx + 1}`,
      stepNo,
      title: row.title,
      fromNode: fromNodeId,
      fromPort: fromPortId,
      invocations: [
        {
          targetNodeId: targetNode.id,
          targetPortId: execPortId,
          methodId: compiled.methodId,
          actionLabel: compiled.actionLabel,
          targetDiscreteState: compiled.targetDiscreteState,
          sclStatement: compiled.sclStatement,
          waitPredicateScl: compiled.waitPredicateScl,
          waitDescription: compiled.waitDescription,
        },
      ],
      branchPredicate,
    });

    lastStepTargetNode = targetNode;
  });

  // Handle IO-only cold start when timing table had 0 rows
  if (timingRows.length === 0 && ioRows.length > 0) {
    ioRows.forEach((ioRow) => {
      const already =
        findMatchingNode(ioRow.actuator, ioRow.instanceDb, existingNodes) ??
        findMatchingNode(ioRow.actuator, ioRow.instanceDb, addedNodes);
      if (already) return;
      const driverClass = inferDriverClass(ioRow.driverRaw, ioRow.actuator, ioRow);
      const spec = MOTHER_CLASS_REGISTRY[driverClass] ?? MOTHER_CLASS_REGISTRY.FB_AF_Actuator2Pos;
      const dbName = buildUniqueDbName(
        stationId,
        ioRow.instanceDb,
        driverClass,
        ioRow.actuator,
        usedDbs,
        addedNodes.length + 1
      );
      const nodeId = buildUniqueNodeId(
        stationId,
        dbName,
        ioRow.actuator,
        usedIds,
        addedNodes.length + 1
      );
      const col = addedNodes.length % 3;
      const lane = Math.floor(addedNodes.length / 3);
      addedNodes.push({
        id: nodeId,
        role: spec.role,
        title: ioRow.actuator || dbName,
        driverClass,
        instanceDb: dbName,
        position: { x: 380 + col * 280, y: 120 + lane * 185 },
        isPinned: false,
        ...(spec.supportsPartPresentSensor || ioRow.hasPartPresent
          ? { hasPartPresentSensor: true }
          : {}),
        discreteStates: [...spec.defaultDiscreteStates],
        initialHomeState: spec.initialHomeState,
        cohesiveIoMap: { ...ioRow.cohesiveIoMap },
        ioSummaryText: formatIoSummaryText(ioRow.cohesiveIoMap, spec.defaultIoSummaryText),
        theme: spec.theme,
        inPorts: spec.defaultInPorts.map((p: SpatialPort) => ({ ...p })),
        outPorts: spec.defaultOutPorts.map((p: SpatialPort) => ({ ...p })),
      });
    });
  }

  const reusedCount = Math.max(0, timingRows.length - addedNodes.length);
  const summaryParts = [`表格冷启动解析完成：新增 ${addedNodes.length} 个唯一实例`];
  if (reusedCount > 0) {
    summaryParts.push(`复用去重 ${reusedCount} 次`);
  }
  summaryParts.push(`生成 ${addedTemporalSteps.length} 条虚影步序超边`);

  if (addedNodes.length > 0 && addedTemporalSteps.length === 0) {
    warnings.push('仅解析到 EPLAN IO 映射表，尚未包含动作时序连线。');
  } else {
    warnings.push('冷启动虚影预览已就绪，请核对后按 Tab 采纳或运行静态符号验证。');
  }

  return {
    txId: `TX_COLDSTART_${stationId}_${addedNodes.length}_${addedTemporalSteps.length}`,
    stationId,
    summary: summaryParts.join(' · '),
    addedNodes,
    addedGuardEdges: [],
    addedTemporalSteps,
    verificationPassed: true,
    verifierWarnings: warnings,
  };
}

/**
 * 生成与 `af_studio_v5.html` 中「模拟导入《ST30动作时序表.xlsx》与《EPLAN_IO.xlsx》」等价的
 * 完整冷启动演示数据（默认针对 ST30 生成 `NG剔除吹气气缸 DB_ST30_CylReject` 与 `S25` 虚影连线）。
 */
export function createDemoExcelColdStartPayload(
  stationId = 'ST30'
): DemoExcelColdStartPayload {
  const workspace = createDefaultAfStudioWorkspace();
  const targetStation = workspace.stationGraphs[stationId];
  const existingNodes = targetStation?.spatialNodes ?? [];

  const upstreamActuator =
    existingNodes.find((n) => n.driverClass === 'FB_AF_VisionSensor')?.title ??
    existingNodes.find((n) => n.role === 'ACTUATOR')?.title ??
    `BOUND_IN_${stationId}`;

  const timingTableText = [
    '步号\t工步名称\t机构\t母版\t动作\t目标状态\t完成条件\t前序机构\t分支',
    `25\t测高超差NG剔除\tNG剔除吹气气缸\tFB_AF_Actuator2Pos\t伸出剔除NG品并退回\tAtHome\tNG滑槽光电确认\t${upstreamActuator}\tNG`,
  ].join('\n');

  const ioTableText = [
    '机构\t位号\t原位输入\t动位输入\t输出点\t电柜端子',
    `NG剔除吹气气缸\tDB_${stationId}_CylReject\t%I20.2\t%I20.3\t%Q20.1\tX20:02`,
  ].join('\n');

  const transaction = parseColdStartTables(timingTableText, ioTableText, {
    stationId,
    existingNodes,
    startStepNo: 25,
  });

  return {
    timingTableText,
    ioTableText,
    transaction: {
      ...transaction,
      summary: `已解析《${stationId}动作时序表.xlsx》与《EPLAN_IO.xlsx》：生成 NG剔除吹气气缸 (DB_${stationId}_CylReject) 与 S25 虚影连线`,
    },
  };
}
