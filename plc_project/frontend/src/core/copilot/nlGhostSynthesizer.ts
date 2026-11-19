import type {
  DriverMotherClass,
  GhostGraphTransaction,
  RadialMethodOption,
  SafetyGuardEdge,
  SpatialInstanceNode,
  SpatialPort,
  StationHyperGraph,
  TemporalStepHyperEdge,
} from '../ir/afHyperGraph.types';
import { MOTHER_CLASS_REGISTRY, getRadialMethodsForClass } from '../ir/motherClassRegistry';

function getMaxStepNo(station: StationHyperGraph): number {
  return station.temporalSteps.reduce((max, s) => Math.max(max, s.stepNo), 0);
}

function makeUniqueId(prefix: string, existingIds: Set<string>): string {
  if (!existingIds.has(prefix)) {
    existingIds.add(prefix);
    return prefix;
  }
  let idx = 2;
  while (existingIds.has(`${prefix}_${idx}`)) {
    idx += 1;
  }
  const unique = `${prefix}_${idx}`;
  existingIds.add(unique);
  return unique;
}

function nextDiagCodeHex(guardEdges: SafetyGuardEdge[]): string {
  let maxVal = 0x0200;
  for (const g of guardEdges) {
    const m = g.diagCodeHex.match(/([0-9A-Fa-f]+)$/);
    if (m) {
      const parsed = Number.parseInt(m[1], 16);
      if (Number.isFinite(parsed) && parsed > maxVal) {
        maxVal = parsed;
      }
    }
  }
  return `16#${(maxVal + 1).toString(16).padStart(4, '0').toUpperCase()}`;
}

function pickFirstSeqOutPort(node: SpatialInstanceNode | undefined, preferNg = false): string {
  if (!node || node.outPorts.length === 0) return 'OUT_DONE';
  const seqPorts = node.outPorts.filter((p) => p.type === 'SEQ');
  const pool = seqPorts.length > 0 ? seqPorts : node.outPorts;
  if (preferNg) {
    const ng = pool.find((p) => p.id === 'OUT_NG' || /NG/i.test(p.label));
    if (ng) return ng.id;
  }
  return pool[0].id;
}

function pickInExecPort(node: SpatialInstanceNode): string {
  return node.inPorts.find((p) => p.type === 'SEQ')?.id ?? node.inPorts[0]?.id ?? 'IN_EXEC';
}

function findNonOverlappingPosition(existingNodes: SpatialInstanceNode[], offsetIndex = 0): {
  x: number;
  y: number;
} {
  let x = 420 + (offsetIndex % 3) * 260;
  let y = 270 + Math.floor(offsetIndex / 3) * 160;
  for (let attempt = 0; attempt < 16; attempt += 1) {
    const overlaps = existingNodes.some(
      (n) => Math.abs(n.position.x - x) < 120 && Math.abs(n.position.y - y) < 95
    );
    if (!overlaps) break;
    x = 260 + ((x + 150) % 520);
    y = 95 + ((y + 110) % 300);
  }
  return { x, y };
}

function buildSpatialNodeFromClass(
  station: StationHyperGraph,
  driverClass: DriverMotherClass,
  title: string,
  dbSuffix: string,
  idSuffix: string,
  usedIds: Set<string>,
  usedDbs: Set<string>,
  cohesiveIoMap: Record<string, string> = {},
  ioSummaryText?: string
): SpatialInstanceNode {
  const spec = MOTHER_CLASS_REGISTRY[driverClass];
  const nodeId = makeUniqueId(`INST_${station.stationId}_${idSuffix}`, usedIds);
  let dbCandidate = `DB_${station.stationId}_${dbSuffix}`;
  if (usedDbs.has(dbCandidate.toLowerCase())) {
    let idx = 2;
    while (usedDbs.has(`${dbCandidate}_${idx}`.toLowerCase())) {
      idx += 1;
    }
    dbCandidate = `${dbCandidate}_${idx}`;
  }
  usedDbs.add(dbCandidate.toLowerCase());

  return {
    id: nodeId,
    role: 'ACTUATOR',
    title,
    driverClass,
    instanceDb: dbCandidate,
    position: findNonOverlappingPosition(station.spatialNodes),
    isPinned: false,
    ...(spec.supportsPartPresentSensor ? { hasPartPresentSensor: true } : {}),
    discreteStates: [...spec.defaultDiscreteStates],
    initialHomeState: spec.initialHomeState,
    cohesiveIoMap,
    ioSummaryText: ioSummaryText ?? spec.defaultIoSummaryText,
    theme: spec.theme,
    inPorts: spec.defaultInPorts.map((p: SpatialPort) => ({ ...p })),
    outPorts: spec.defaultOutPorts.map((p: SpatialPort) => ({ ...p })),
  };
}

function wouldIntroduceGuardCycle(
  existingGuards: SafetyGuardEdge[],
  fromId: string,
  toId: string
): boolean {
  if (fromId === toId) return true;
  // Check if `fromId` is already reachable from `toId` along existing guardEdges
  const adj = new Map<string, string[]>();
  for (const g of existingGuards) {
    const list = adj.get(g.fromNode) ?? [];
    list.push(g.toNode);
    adj.set(g.fromNode, list);
  }
  const visited = new Set<string>([toId]);
  const queue: string[] = [toId];
  while (queue.length > 0) {
    const curr = queue.shift()!;
    if (curr === fromId) return true;
    for (const next of adj.get(curr) ?? []) {
      if (!visited.has(next)) {
        visited.add(next);
        queue.push(next);
      }
    }
  }
  return false;
}

function synthesizeNgRejectBranch(
  prompt: string,
  station: StationHyperGraph,
  usedNodeIds: Set<string>,
  usedDbs: Set<string>,
  usedStepIds: Set<string>
): GhostGraphTransaction {
  const visionNode = station.spatialNodes.find((n) => n.driverClass === 'FB_AF_VisionSensor');
  const axisNode = station.spatialNodes.find((n) => n.driverClass === 'FB_AF_AxisMotion');
  const gripperNode = station.spatialNodes.find((n) => n.driverClass === 'FB_AF_Gripper');
  const maxStepNo = getMaxStepNo(station);
  const existingStepNos = new Set(station.temporalSteps.map((s) => s.stepNo));

  // Case 1A: Station has Vision + Axis (e.g. ST20) -> S35 (OUT_NG -> AxisX) & S36 (AxisX -> Gripper)
  if (visionNode && axisNode) {
    const prefer35And36 =
      !existingStepNos.has(35) && !existingStepNos.has(36) && existingStepNos.has(30);
    const step1No = prefer35And36 ? 35 : maxStepNo + 10;
    const step2No = prefer35And36 ? 36 : step1No + 1;

    const visionNgPort = pickFirstSeqOutPort(visionNode, true);
    const axisOutPort = pickFirstSeqOutPort(axisNode, false);

    const requiresGuardNodeIds = station.guardEdges
      .filter((g) => g.toNode === axisNode.id)
      .map((g) => g.fromNode)
      .filter((id) => station.spatialNodes.some((n) => n.id === id && n.role === 'ACTUATOR'));

    const rejectPosMatch = prompt.match(/(\d+(?:\.\d+)?)\s*mm/i);
    const rejectPosMm = rejectPosMatch ? rejectPosMatch[1] : '410';
    const rejectState =
      axisNode.discreteStates.find((s) => /reject|410/i.test(s)) ?? `Pos_Reject_${rejectPosMm}`;

    const step1: TemporalStepHyperEdge = {
      id: makeUniqueId(`GW_NG_${station.stationId}_S${step1No}`, usedStepIds),
      stepNo: step1No,
      title: `NG移至抛料位 (${rejectPosMm}mm)`,
      fromNode: visionNode.id,
      fromPort: visionNgPort,
      invocations: [
        {
          targetNodeId: axisNode.id,
          targetPortId: pickInExecPort(axisNode),
          methodId: 'MoveReject',
          actionLabel: `移至NG抛料位 (${rejectPosMm}mm)`,
          targetDiscreteState: rejectState,
          sclStatement: `#${axisNode.instanceDb}.MoveAbs(${rejectPosMm}.0);`.replace('.0.0', '.0'),
          waitPredicateScl: `"${axisNode.instanceDb}".o_bInPos AND (ABS("${axisNode.instanceDb}".o_rActPos - ${rejectPosMm}.0) < 0.05)`,
          waitDescription: `到达 ${rejectPosMm}mm 抛料口`,
        },
      ],
      branchPredicate: 'NG',
      ...(requiresGuardNodeIds.length > 0 ? { requiresGuardNodeIds } : {}),
    };

    const addedNodes: SpatialInstanceNode[] = [];
    let step2Target: SpatialInstanceNode | undefined = gripperNode;
    let step2InvocationMethod = 'GripOpen';
    let step2ActionLabel = '张开释放NG电芯';
    let step2TargetState = 'Opened';
    let step2Scl = gripperNode ? `#${gripperNode.instanceDb}.OpenGrip();` : '';
    let step2Wait = gripperNode ? `"${gripperNode.instanceDb}".o_bOpened` : '';
    let step2WaitDesc = '夹爪张开到位';

    if (!step2Target) {
      const existingReject = station.spatialNodes.find((n) =>
        /剔除|吹气|抛料|reject/i.test(`${n.title} ${n.instanceDb}`)
      );
      if (existingReject) {
        step2Target = existingReject;
      } else {
        step2Target = buildSpatialNodeFromClass(
          station,
          'FB_AF_Actuator2Pos',
          'NG剔除吹气气缸',
          'CylReject',
          'REJECT',
          usedNodeIds,
          usedDbs,
          { diHome: '%I20.2', diWork: '%I20.3', doWork: '%Q20.1' },
          '原位 %I20.2 / 阀 %Q20.1'
        );
        addedNodes.push(step2Target);
      }
      step2InvocationMethod = 'ExtendAndRetract';
      step2ActionLabel = '伸出剔除NG品并退回';
      step2TargetState = 'AtHome';
      step2Scl = `#${step2Target.instanceDb}.ExtendAndRetract();`;
      step2Wait = `"${step2Target.instanceDb}".o_bAtHome AND "${step2Target.instanceDb}".o_bCycleDone`;
      step2WaitDesc = 'NG滑槽光电确认';
    }

    const step2: TemporalStepHyperEdge = {
      id: makeUniqueId(`GW_NG_${station.stationId}_S${step2No}`, usedStepIds),
      stepNo: step2No,
      title: gripperNode ? 'NG张开夹爪抛料' : 'NG吹气剔除放行',
      fromNode: axisNode.id,
      fromPort: axisOutPort,
      invocations: [
        {
          targetNodeId: step2Target.id,
          targetPortId: pickInExecPort(step2Target),
          methodId: step2InvocationMethod,
          actionLabel: step2ActionLabel,
          targetDiscreteState: step2TargetState,
          sclStatement: step2Scl,
          waitPredicateScl: step2Wait,
          waitDescription: step2WaitDesc,
        },
      ],
      branchPredicate: 'NG',
    };

    return {
      txId: `TX_NL_NG_${station.stationId}_${step1No}_${step2No}`,
      stationId: station.stationId,
      summary: `AI 已生成 ${addedNodes.length > 0 ? `${addedNodes.length} 个新实例与 ` : ''}2 条 NG 抛料虚影步序超边 (S${step1No} → S${step2No})`,
      addedNodes,
      addedGuardEdges: [],
      addedTemporalSteps: [step1, step2],
      verificationPassed: true,
      verifierWarnings: [
        '离线神经符号预览已生成，待静态符号验证器 (Symbolic Verifier) 复核防撞护栏。',
      ],
    };
  }

  // Case 1B: Station without full Axis+Gripper (e.g. ST30) -> attach NG Reject Cylinder + Ghost Step
  const addedNodes: SpatialInstanceNode[] = [];
  let rejectNode = station.spatialNodes.find((n) =>
    /剔除|吹气|抛料|reject/i.test(`${n.title} ${n.instanceDb}`)
  );
  if (!rejectNode) {
    rejectNode = buildSpatialNodeFromClass(
      station,
      'FB_AF_Actuator2Pos',
      'NG剔除吹气气缸',
      'CylReject',
      'REJECT',
      usedNodeIds,
      usedDbs,
      { diHome: '%I20.2', diWork: '%I20.3', doWork: '%Q20.1' },
      '原位 %I20.2 / 阀 %Q20.1'
    );
    addedNodes.push(rejectNode);
  }

  const sourceNode =
    visionNode ??
    station.spatialNodes.find((n) => n.role === 'ACTUATOR' && n.id !== rejectNode!.id) ??
    station.spatialNodes[0];

  const stepNo =
    station.stationId === 'ST30' && !existingStepNos.has(25) ? 25 : maxStepNo + 10;

  const ngStep: TemporalStepHyperEdge = {
    id: makeUniqueId(`GW_NG_${station.stationId}_S${stepNo}`, usedStepIds),
    stepNo,
    title: 'NG剔除分拣动作',
    fromNode: sourceNode?.id ?? `BOUND_IN_${station.stationId}`,
    fromPort: pickFirstSeqOutPort(sourceNode, true),
    invocations: [
      {
        targetNodeId: rejectNode.id,
        targetPortId: pickInExecPort(rejectNode),
        methodId: 'ExtendAndRetract',
        actionLabel: '伸出剔除NG品并退回',
        targetDiscreteState: 'AtHome',
        sclStatement: `#${rejectNode.instanceDb}.ExtendAndRetract();`,
        waitPredicateScl: `"${rejectNode.instanceDb}".o_bAtHome AND "${rejectNode.instanceDb}".o_bCycleDone`,
        waitDescription: 'NG滑槽光电确认',
      },
    ],
    branchPredicate: 'NG',
  };

  return {
    txId: `TX_NL_NG_${station.stationId}_${stepNo}`,
    stationId: station.stationId,
    summary: `AI 已生成 ${addedNodes.length > 0 ? 'NG剔除吹气气缸实例与 ' : ''}S${stepNo} NG 剔除虚影超边`,
    addedNodes,
    addedGuardEdges: [],
    addedTemporalSteps: [ngStep],
    verificationPassed: true,
    verifierWarnings: [
      '离线神经符号预览已生成，待静态符号验证器 (Symbolic Verifier) 复核。',
    ],
  };
}

function scoreGuardPair(
  prompt: string,
  src: SpatialInstanceNode,
  dst: SpatialInstanceNode
): number {
  let score = 0;
  if (src.driverClass === 'FB_AF_Actuator2Pos' && dst.driverClass === 'FB_AF_AxisMotion') {
    score += 50;
  } else if (src.driverClass === 'FB_AF_Actuator2Pos' && dst.driverClass === 'FB_AF_Gripper') {
    score += 30;
  } else if (src.driverClass === 'FB_AF_Gripper' && dst.driverClass === 'FB_AF_AxisMotion') {
    score += 20;
  } else if (src.driverClass === 'FB_AF_Actuator2Pos' && dst.driverClass === 'FB_AF_Actuator2Pos') {
    score += 15;
  }

  const pLower = prompt.toLowerCase();
  if (pLower.includes(src.title.toLowerCase()) || (/z轴|z缸/i.test(prompt) && /z/i.test(src.title))) {
    score += 25;
  }
  if (pLower.includes(dst.title.toLowerCase()) || (/x轴|伺服/i.test(prompt) && /x|伺服/i.test(dst.title))) {
    score += 25;
  }
  return score;
}

function synthesizeGuardrailSuggestion(
  prompt: string,
  station: StationHyperGraph
): GhostGraphTransaction {
  const actuators = station.spatialNodes.filter(
    (n) => n.role === 'ACTUATOR' && n.driverClass !== 'FB_AF_VisionSensor'
  );
  const existingPairSet = new Set(station.guardEdges.map((g) => `${g.fromNode}->${g.toNode}`));

  const candidates: Array<{ src: SpatialInstanceNode; dst: SpatialInstanceNode; score: number }> = [];
  for (const src of actuators) {
    for (const dst of actuators) {
      if (src.id === dst.id) continue;
      if (existingPairSet.has(`${src.id}->${dst.id}`)) continue;
      if (wouldIntroduceGuardCycle(station.guardEdges, src.id, dst.id)) continue;
      candidates.push({ src, dst, score: scoreGuardPair(prompt, src, dst) });
    }
  }

  candidates.sort((a, b) => b.score - a.score);

  if (candidates.length === 0) {
    return {
      txId: `TX_NL_GUARD_${station.stationId}_NONE`,
      stationId: station.stationId,
      summary: `${station.stationId} 现有无环护栏拓扑已覆盖可保护执行器对`,
      addedNodes: [],
      addedGuardEdges: [],
      addedTemporalSteps: [],
      verificationPassed: true,
      verifierWarnings: ['未发现可追加而不产生死锁环路的新增护栏边。'],
    };
  }

  const chosen = candidates[0];
  const fromPort =
    chosen.src.outPorts.find((p) => p.type === 'GUARD')?.id ?? 'OUT_AT_HOME';
  const toPort =
    chosen.dst.inPorts.find((p) => p.type === 'GUARD')?.id ?? 'IN_GUARD';
  const diagCodeHex = nextDiagCodeHex(station.guardEdges);

  const guardEdge: SafetyGuardEdge = {
    id: `G_AI_${chosen.src.id}_TO_${chosen.dst.id}`,
    fromNode: chosen.src.id,
    fromPort,
    toNode: chosen.dst.id,
    toPort,
    requiredSourceState: chosen.src.initialHomeState || 'AtHome',
    diagCodeHex,
    humanDescription: `${chosen.src.title}处于安全原位 (${chosen.src.initialHomeState}) 才允许${chosen.dst.title}动作`,
    isHealthy: true,
  };

  return {
    txId: `TX_NL_GUARD_${station.stationId}_${chosen.src.id}_${chosen.dst.id}`,
    stationId: station.stationId,
    summary: `AI 建议注入安全护栏 ${diagCodeHex}：${chosen.src.title} → ${chosen.dst.title}`,
    addedNodes: [],
    addedGuardEdges: [guardEdge],
    addedTemporalSteps: [],
    verificationPassed: true,
    verifierWarnings: [
      '护栏拓扑已通过无环路检查，待静态符号验证器 (Symbolic Verifier) 复核。',
    ],
  };
}

function detectRequestedDriverClass(prompt: string): DriverMotherClass {
  if (/伺服|搬运轴|直线模组|分度盘|axis|servo/i.test(prompt)) return 'FB_AF_AxisMotion';
  if (/夹爪|抓手|吸盘|gripper|clamp/i.test(prompt)) return 'FB_AF_Gripper';
  if (/气缸|压缸|推缸|顶升缸|阻挡缸|吹气|cylinder|actuator/i.test(prompt)) {
    return 'FB_AF_Actuator2Pos';
  }
  if (/复检|视觉|相机|测高|激光|扫码|读码|传感器|vision|camera|laser|sensor/i.test(prompt)) {
    return 'FB_AF_VisionSensor';
  }
  return 'FB_AF_Actuator2Pos';
}

function inferNewActuatorMeta(prompt: string, driverClass: DriverMotherClass): {
  title: string;
  dbSuffix: string;
  idSuffix: string;
} {
  if (/复检/.test(prompt)) {
    if (driverClass === 'FB_AF_VisionSensor') {
      return { title: '视觉复检相机', dbSuffix: 'CamRecheck', idSuffix: 'RECHECK_CAM' };
    }
    return { title: '复检执行气缸', dbSuffix: 'CylRecheck', idSuffix: 'RECHECK_CYL' };
  }
  switch (driverClass) {
    case 'FB_AF_AxisMotion':
      return { title: '新增辅助伺服轴', dbSuffix: 'AxisAux', idSuffix: 'AUX_AXIS' };
    case 'FB_AF_Gripper':
      return { title: '新增气动夹爪', dbSuffix: 'GripAux', idSuffix: 'AUX_GRIP' };
    case 'FB_AF_VisionSensor':
      return { title: '新增工艺传感器', dbSuffix: 'CamAux', idSuffix: 'AUX_CAM' };
    default:
      return { title: '新增辅助气缸', dbSuffix: 'CylAux', idSuffix: 'AUX_CYL' };
  }
}

function selectMethodForPrompt(
  prompt: string,
  node: SpatialInstanceNode
): RadialMethodOption {
  const methods = getRadialMethodsForClass(node.driverClass, node).filter((m) => !m.isGuard);
  if (methods.length === 0) {
    return {
      methodId: 'Execute',
      label: '执行工艺动作',
      waitDescription: '动作到位',
      sclCommand: 'Execute()',
      targetDiscreteState: node.discreteStates[node.discreteStates.length - 1] ?? 'AtWork',
    };
  }

  if (/张开|松开|释放|open|release/i.test(prompt)) {
    return methods.find((m) => /open/i.test(m.methodId)) ?? methods[0];
  }
  if (/闭合|夹紧|close|grip/i.test(prompt)) {
    return methods.find((m) => /close/i.test(m.methodId)) ?? methods[0];
  }
  if (/缩回|退回|回原|复位|待机|home|retract/i.test(prompt)) {
    return methods.find((m) => /home|retract/i.test(m.methodId)) ?? methods[0];
  }
  if (/抛料|reject/i.test(prompt)) {
    return methods.find((m) => /reject/i.test(m.methodId)) ?? methods[0];
  }
  if (/取料|pick/i.test(prompt)) {
    return methods.find((m) => /pick/i.test(m.methodId)) ?? methods[0];
  }
  if (/压装|伸出|下压|press|extend/i.test(prompt)) {
    return methods.find((m) => /press|extend/i.test(m.methodId)) ?? methods[0];
  }
  return methods[0];
}

function matchExistingActuator(prompt: string, station: StationHyperGraph): SpatialInstanceNode | undefined {
  const actuators = station.spatialNodes.filter((n) => n.role === 'ACTUATOR');
  const pLower = prompt.toLowerCase();
  return actuators.find((n) => {
    const titleMatch = pLower.includes(n.title.toLowerCase());
    const dbMatch = pLower.includes(n.instanceDb.toLowerCase());
    const axisMatch =
      n.driverClass === 'FB_AF_AxisMotion' &&
      (/x轴|伺服/i.test(prompt) && /x|伺服/i.test(n.title));
    const zMatch =
      n.driverClass === 'FB_AF_Actuator2Pos' &&
      (/z轴/i.test(prompt) && /z/i.test(n.title));
    const gripMatch =
      n.driverClass === 'FB_AF_Gripper' && /夹爪/.test(prompt) && /夹爪/.test(n.title);
    return titleMatch || dbMatch || axisMatch || zMatch || gripMatch;
  });
}

/**
 * 纯前端离线确定性意图解析器：
 * 在后端 LLM 未连接时毫秒级将自然语言工艺指令合成结构化 GhostGraphTransaction 预览，
 * 绝不直接覆盖既有图，且所有新生成空间实例 `isPinned` 设为 `false`。
 */
export function synthesizeGhostFromPrompt(
  prompt: string,
  station: StationHyperGraph
): GhostGraphTransaction {
  const trimmed = prompt.trim();
  if (!trimmed) {
    return {
      txId: `TX_NL_${station.stationId}_EMPTY`,
      stationId: station.stationId,
      summary: '请输入自然语言工艺指令后再生成虚影预览',
      addedNodes: [],
      addedGuardEdges: [],
      addedTemporalSteps: [],
      verificationPassed: false,
      verifierWarnings: ['指令内容为空，未生成任何虚影节点或连线。'],
    };
  }

  if (/续作|恢复原工步|附件更换请求|resume.*work/i.test(trimmed)) {
    return {
      txId: `TX_NL_${station.stationId}_ORCHESTRATION`,
      stationId: station.stationId,
      summary: '请在虚拟逻辑工位配置跨站暂停、更换与续作',
      addedNodes: [],
      addedGuardEdges: [],
      addedTemporalSteps: [],
      verificationPassed: false,
      verifierWarnings: [],
    };
  }

  const usedNodeIds = new Set(station.spatialNodes.map((n) => n.id));
  const usedDbs = new Set(station.spatialNodes.map((n) => n.instanceDb.toLowerCase()));
  const usedStepIds = new Set(station.temporalSteps.map((s) => s.id));

  // 1. NG / 抛料 / 剔除 分支意图
  if (/NG|抛料|剔除|不良|废品|分拣|reject|scrap/i.test(trimmed)) {
    return synthesizeNgRejectBranch(trimmed, station, usedNodeIds, usedDbs, usedStepIds);
  }

  // 2. 护栏 / 防撞 / 互锁 意图
  if (/护栏|防撞|互锁|安全锁|interlock|guard/i.test(trimmed)) {
    return synthesizeGuardrailSuggestion(trimmed, station);
  }

  // 3. 新增执行器 / 复检 / 通用工步合成
  const maxStepNo = getMaxStepNo(station);
  const nextStepNo = maxStepNo + 10;
  const wantsNewInstance =
    /新增|添加|加装|新加|加一个|复检|add|create|new/i.test(trimmed) ||
    (/增加/.test(trimmed) && /气缸|伺服|夹爪|视觉|相机|测高|传感器|复检/.test(trimmed));

  const matchedExisting = wantsNewInstance ? undefined : matchExistingActuator(trimmed, station);
  const driverClass = matchedExisting?.driverClass ?? detectRequestedDriverClass(trimmed);

  const addedNodes: SpatialInstanceNode[] = [];
  let targetNode = matchedExisting;

  if (!targetNode) {
    const meta = inferNewActuatorMeta(trimmed, driverClass);
    targetNode = buildSpatialNodeFromClass(
      station,
      driverClass,
      meta.title,
      meta.dbSuffix,
      meta.idSuffix,
      usedNodeIds,
      usedDbs
    );
    addedNodes.push(targetNode);
  }

  const chosenMethod = selectMethodForPrompt(trimmed, targetNode);
  const lastStep = [...station.temporalSteps].sort((a, b) => a.stepNo - b.stepNo).at(-1);
  const prevTargetNodeId = lastStep?.invocations[0]?.targetNodeId;
  const prevNode =
    (prevTargetNodeId
      ? station.spatialNodes.find((n) => n.id === prevTargetNodeId)
      : undefined) ??
    station.spatialNodes.find((n) => n.role === 'ACTUATOR') ??
    station.spatialNodes.find((n) => n.role === 'BOUNDARY_IN') ??
    station.spatialNodes[0];

  const cleanActionLabel = chosenMethod.label.replace(/^[^\u4e00-\u9fa5A-Za-z0-9]+/, '').trim();
  const stepTitle = `${targetNode.title}·${cleanActionLabel}`;

  const stepEdge: TemporalStepHyperEdge = {
    id: makeUniqueId(`GW_NL_${station.stationId}_S${nextStepNo}`, usedStepIds),
    stepNo: nextStepNo,
    title: stepTitle,
    fromNode: prevNode?.id ?? `BOUND_IN_${station.stationId}`,
    fromPort: pickFirstSeqOutPort(prevNode, false),
    invocations: [
      {
        targetNodeId: targetNode.id,
        targetPortId: pickInExecPort(targetNode),
        methodId: chosenMethod.methodId,
        actionLabel: cleanActionLabel,
        targetDiscreteState: chosenMethod.targetDiscreteState,
        sclStatement: `#${targetNode.instanceDb}.${chosenMethod.sclCommand};`.replace(';;', ';'),
        waitPredicateScl: `"${targetNode.instanceDb}".o_bDone`,
        waitDescription: chosenMethod.waitDescription,
      },
    ],
    branchPredicate: 'ALWAYS',
  };

  return {
    txId: `TX_NL_${station.stationId}_S${nextStepNo}`,
    stationId: station.stationId,
    summary: `AI 已合成 ${addedNodes.length > 0 ? `1 个新实例「${targetNode.title}」与 ` : ''}S${nextStepNo} 虚影超边`,
    addedNodes,
    addedGuardEdges: [],
    addedTemporalSteps: [stepEdge],
    verificationPassed: true,
    verifierWarnings: [
      '离线神经符号草稿已生成，待静态符号验证器 (Symbolic Verifier) 校验。',
    ],
  };
}

/** 自然语言虚影意图合成别名，支持 (prompt, station) 与 (station, prompt) 参数反转容错 */
export function synthesizeNlIntentToGhost(
  arg1: string | StationHyperGraph,
  arg2: StationHyperGraph | string
): GhostGraphTransaction {
  if (typeof arg1 === 'string') {
    return synthesizeGhostFromPrompt(arg1, arg2 as StationHyperGraph);
  }
  return synthesizeGhostFromPrompt(arg2 as string, arg1 as StationHyperGraph);
}
