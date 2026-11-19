import type {
  CompiledBlockArtifact,
  HomingNodeAction,
  HomingSynthesisResult,
  SafetyGuardEdge,
  SpatialInstanceNode,
  StationHyperGraph,
  TemporalStepHyperEdge,
} from '../ir/afHyperGraph.types';
import { computeBlockHashes } from './merkleAstHasher';
import { stationHasUnboundSignals } from '../ir/stationWorkspace';
import { cmBindingStatus } from '../ir/fieldIo';

function sanitizeIdent(raw: string, fallback = 'Sym'): string {
  const cleaned = raw.replace(/[^A-Za-z0-9_]/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '');
  if (!cleaned) return fallback;
  return /^[0-9]/.test(cleaned) ? `n_${cleaned}` : cleaned;
}

function escapeSclString(raw: string): string {
  return raw.replace(/\$/g, '$$').replace(/'/g, "$'");
}

function normalizeDiagCodeHex(raw: string): string {
  const trimmed = (raw || '').trim();
  if (/^16#[0-9A-Fa-f]+$/.test(trimmed)) {
    return `16#${trimmed.slice(3).toUpperCase()}`;
  }
  if (/^#[0-9A-Fa-f]+$/.test(trimmed)) {
    return `16#${trimmed.slice(1).toUpperCase()}`;
  }
  const hexDigits = trimmed.replace(/[^0-9A-Fa-f]/g, '');
  return hexDigits ? `16#${hexDigits.toUpperCase()}` : '16#0200';
}

function formatDWordBitmask(index: number): string {
  const bit = index % 32;
  const val = (1 << bit) >>> 0;
  return `16#${val.toString(16).padStart(8, '0').toUpperCase()}`;
}

function compareStringsAscii(a: string, b: string): number {
  if (a < b) return -1;
  if (a > b) return 1;
  return 0;
}

function getActuatorNodes(station: StationHyperGraph): SpatialInstanceNode[] {
  return station.spatialNodes.filter((node) => node.role === 'ACTUATOR');
}

function buildUniqueActuatorFieldNames(actuators: SpatialInstanceNode[]): Map<string, string> {
  const used = new Set<string>();
  const map = new Map<string, string>();
  for (const node of actuators) {
    const base = sanitizeIdent(node.instanceDb || node.id, 'Inst');
    let candidate = base;
    let suffix = 2;
    while (used.has(candidate)) {
      candidate = `${base}_${suffix++}`;
    }
    used.add(candidate);
    map.set(node.id, candidate);
  }
  return map;
}

function compileInstancesDbBlock(station: StationHyperGraph): CompiledBlockArtifact {
  const blockName = `DB_${sanitizeIdent(station.stationId, 'ST')}_Instances`;
  const actuators = getActuatorNodes(station);
  const fieldNames = buildUniqueActuatorFieldNames(actuators);

  const lines: string[] = [
    `// AF-Studio v5 Deterministic Multi-Target Compiler - Station Instances DB`,
    `DATA_BLOCK "${blockName}"`,
    `{ S7_Optimized_Access := 'TRUE' }`,
    `VERSION : 0.1`,
    `NON_RETAIN`,
    `   VAR`,
    `      // Station: ${station.stationId} (${station.stationName})`,
  ];

  if (actuators.length === 0) {
    lines.push(`      bStationReady : Bool; // No actuator instances declared`);
  } else {
    for (const node of actuators) {
      const fieldName = fieldNames.get(node.id)!;
      const driverClass = sanitizeIdent(node.driverClass, 'FB_AF_Actuator2Pos');
      lines.push(`      ${fieldName} : "${driverClass}"; // [${node.id}] ${node.title}`);
    }
  }

  const ioRows: string[] = [];
  for (const node of actuators) {
    const ioKeys = Object.keys(node.cohesiveIoMap ?? {}).sort(compareStringsAscii);
    for (const ioKey of ioKeys) {
      const terminal = node.cohesiveIoMap[ioKey];
      const sym = sanitizeIdent(`${node.id}_${ioKey}`, 'ioPin');
      ioRows.push(`         ${sym} : String[48] := '${escapeSclString(String(terminal))}';`);
    }
  }

  if (ioRows.length > 0) {
    lines.push(`      // 内聚硬件 IO 端子映射表 (Cohesive Hardware IO Map)`);
    lines.push(`      ioTerminalMap : Struct`);
    lines.push(...ioRows);
    lines.push(`      END_STRUCT;`);
  }

  lines.push(`   END_VAR`);
  lines.push(`BEGIN`);
  lines.push(`END_DATA_BLOCK`);

  const sclCode = lines.join('\n');
  const hashes = computeBlockHashes(sclCode);
  return {
    blockName,
    blockType: 'DB',
    stationId: station.stationId,
    sclCode,
    ...hashes,
  };
}

function collectGuardEdgesForStep(
  step: TemporalStepHyperEdge,
  guardEdges: SafetyGuardEdge[]
): SafetyGuardEdge[] {
  const targetIds = new Set(step.invocations.map((inv) => inv.targetNodeId));
  const requiredFromIds = new Set(step.requiresGuardNodeIds ?? []);
  return guardEdges.filter(
    (g) => targetIds.has(g.toNode) || requiredFromIds.has(g.fromNode)
  );
}

function resolveBranchTargets(
  step: TemporalStepHyperEdge,
  stepIndex: number,
  sortedSteps: TemporalStepHyperEdge[],
  nodeById: Map<string, SpatialInstanceNode>
): {
  okStep?: TemporalStepHyperEdge;
  ngStep?: TemporalStepHyperEdge;
  defaultNextStepNo: number;
  sensorNode?: SpatialInstanceNode;
} {
  const targetIds = new Set(step.invocations.map((inv) => inv.targetNodeId));

  const okStep = sortedSteps.find(
    (candidate) =>
      candidate.stepNo !== step.stepNo &&
      targetIds.has(candidate.fromNode) &&
      (candidate.branchPredicate === 'OK' || candidate.fromPort === 'OUT_OK')
  );

  const ngStep = sortedSteps.find(
    (candidate) =>
      candidate.stepNo !== step.stepNo &&
      targetIds.has(candidate.fromNode) &&
      (candidate.branchPredicate === 'NG' || candidate.fromPort === 'OUT_NG')
  );

  let sensorNode: SpatialInstanceNode | undefined;
  for (const targetId of targetIds) {
    const candidate = nodeById.get(targetId);
    if (candidate?.driverClass === 'FB_AF_VisionSensor') {
      sensorNode = candidate;
      break;
    }
  }

  const sequentialFollower = sortedSteps.find(
    (candidate, idx) =>
      idx > stepIndex &&
      targetIds.has(candidate.fromNode) &&
      candidate.branchPredicate !== 'NG'
  );

  const fallbackNext = sortedSteps[stepIndex + 1];
  const defaultNextStepNo = sequentialFollower?.stepNo ?? fallbackNext?.stepNo ?? 999;

  return {
    ...(okStep ? { okStep } : {}),
    ...(ngStep ? { ngStep } : {}),
    defaultNextStepNo,
    ...(sensorNode ? { sensorNode } : {}),
  };
}

function collectExtraInputsFromSteps(
  station: StationHyperGraph,
  alreadyDeclared: Set<string>
): string[] {
  const extras = new Set<string>();
  for (const node of station.spatialNodes) {
    if (node.role !== 'BOUNDARY_IN') continue;
    for (const key of Object.keys(node.cohesiveIoMap ?? {}).sort(compareStringsAscii)) {
      if (key.startsWith('i_') && !alreadyDeclared.has(key)) {
        extras.add(sanitizeIdent(key));
      }
    }
  }
  for (const step of station.temporalSteps) {
    for (const inv of step.invocations) {
      const regex = /(^|[^.\w])#?(i_[A-Za-z0-9_]+)\b/g;
      let match: RegExpExecArray | null;
      while ((match = regex.exec(inv.waitPredicateScl)) !== null) {
        const token = match[2];
        if (!alreadyDeclared.has(token)) {
          extras.add(sanitizeIdent(token));
        }
      }
    }
  }
  return Array.from(extras).sort(compareStringsAscii);
}

function collectBoundaryOutputs(
  station: StationHyperGraph,
  alreadyDeclared: Set<string>
): string[] {
  const outputs = new Set<string>();
  for (const node of station.spatialNodes) {
    if (node.role !== 'BOUNDARY_OUT') continue;
    for (const key of Object.keys(node.cohesiveIoMap ?? {}).sort(compareStringsAscii)) {
      if (key.startsWith('o_') && !alreadyDeclared.has(key)) {
        outputs.add(sanitizeIdent(key));
      }
    }
  }
  for (const step of station.temporalSteps) {
    for (const inv of step.invocations) {
      const regex = /(^|[^.\w])#?(o_[A-Za-z0-9_]+)\b/g;
      let match: RegExpExecArray | null;
      while ((match = regex.exec(inv.sclStatement)) !== null) {
        const token = match[2];
        if (!alreadyDeclared.has(token)) {
          outputs.add(sanitizeIdent(token));
        }
      }
    }
  }
  return Array.from(outputs).sort(compareStringsAscii);
}

function compileAutoSeqBlock(station: StationHyperGraph): CompiledBlockArtifact {
  const stationKey = sanitizeIdent(station.stationId, 'ST');
  const blockName = `FB_${stationKey}_AutoSeq`;
  const instanceDbName = `DB_${stationKey}_Instances`;

  const actuators = getActuatorNodes(station);
  const actuatorFields = buildUniqueActuatorFieldNames(actuators);
  const nodeById = new Map(station.spatialNodes.map((n) => [n.id, n]));

  const sortedSteps = [...station.temporalSteps].sort(
    (a, b) => a.stepNo - b.stepNo || compareStringsAscii(a.id, b.id)
  );

  const declaredInputs = new Set<string>(['i_bStart', 'i_bReset', 'i_bInterlockOK']);
  const guardPins = station.guardEdges.map((g) => {
    const pin = `i_bGuard_${sanitizeIdent(g.id)}`;
    declaredInputs.add(pin);
    return { guard: g, pin };
  });
  const extraInputs = collectExtraInputsFromSteps(station, declaredInputs);

  const declaredOutputs = new Set<string>([
    'q_bBusy',
    'q_bDone',
    'q_iActiveStep',
    'q_wGuardDiagCode',
  ]);
  const extraOutputs = collectBoundaryOutputs(station, declaredOutputs);

  const lines: string[] = [
    `// AF-Studio v5 Deterministic Multi-Target Compiler - Auto Sequence FB`,
    `FUNCTION_BLOCK "${blockName}"`,
    `{ S7_Optimized_Access := 'TRUE' }`,
    `VERSION : 0.1`,
    `VAR_INPUT`,
    `   i_bStart : Bool;`,
    `   i_bReset : Bool;`,
    `   i_bInterlockOK : Bool := TRUE;`,
  ];

  for (const { guard, pin } of guardPins) {
    lines.push(
      `   ${pin} : Bool := TRUE; // [${normalizeDiagCodeHex(guard.diagCodeHex)}] ${guard.humanDescription}`
    );
  }
  for (const extra of extraInputs) {
    lines.push(`   ${extra} : Bool;`);
  }

  lines.push(`END_VAR`);
  lines.push(`VAR_OUTPUT`);
  lines.push(`   q_bBusy : Bool;`);
  lines.push(`   q_bDone : Bool;`);
  lines.push(`   q_iActiveStep : Int;`);
  lines.push(`   q_wGuardDiagCode : Word;`);
  for (const outPin of extraOutputs) {
    lines.push(`   ${outPin} : Bool;`);
  }
  lines.push(`END_VAR`);
  lines.push(`VAR`);
  lines.push(`   statStep : Int := 0;`);
  lines.push(`   tonDwell : TON_TIME;`);
  for (const node of actuators) {
    const fieldName = actuatorFields.get(node.id)!;
    const driverClass = sanitizeIdent(node.driverClass, 'FB_AF_Actuator2Pos');
    lines.push(`   ${fieldName} : "${driverClass}";`);
  }
  lines.push(`END_VAR`);
  lines.push(`BEGIN`);
  lines.push(`   IF #i_bReset THEN`);
  lines.push(`      #statStep := 0;`);
  lines.push(`      #q_bBusy := FALSE;`);
  lines.push(`      #q_bDone := FALSE;`);
  lines.push(`      #q_wGuardDiagCode := 16#0000;`);
  for (const outPin of extraOutputs) {
    lines.push(`      #${outPin} := FALSE;`);
  }
  lines.push(`      RETURN;`);
  lines.push(`   END_IF;`);
  lines.push(``);

  if (guardPins.length > 0) {
    lines.push(`   // 空间安全护栏实时前置诊断 (Safety Guard Entry Evaluation)`);
    lines.push(`   #q_wGuardDiagCode := 16#0000;`);
    for (const { guard, pin } of guardPins) {
      lines.push(`   IF NOT #${pin} AND (#q_wGuardDiagCode = 16#0000) THEN`);
      lines.push(`      #q_wGuardDiagCode := ${normalizeDiagCodeHex(guard.diagCodeHex)};`);
      lines.push(`   END_IF;`);
    }
    lines.push(``);
  } else {
    lines.push(`   #q_wGuardDiagCode := 16#0000;`);
    lines.push(``);
  }

  lines.push(`   #q_iActiveStep := #statStep;`);
  lines.push(`   #q_bBusy := (#statStep > 0) AND (#statStep < 999);`);
  lines.push(``);
  lines.push(`   CASE #statStep OF`);
  const firstStepNo = sortedSteps[0]?.stepNo ?? 999;
  lines.push(`      0: // [Idle] 等待启动信号与全局互锁`);
  lines.push(`         #q_bDone := FALSE;`);
  lines.push(`         IF #i_bStart AND #i_bInterlockOK AND (#q_wGuardDiagCode = 16#0000) THEN`);
  lines.push(`            #statStep := ${firstStepNo};`);
  lines.push(`         END_IF;`);

  sortedSteps.forEach((step, idx) => {
    lines.push(``);
    const stepGuards = collectGuardEdgesForStep(step, station.guardEdges);
    const branchLabel = step.branchPredicate ? ` | branch=${step.branchPredicate}` : '';
    lines.push(`      ${step.stepNo}: // [${step.title}${branchLabel}]`);

    const indent = stepGuards.length > 0 ? '            ' : '         ';
    if (stepGuards.length > 0) {
      const guardTerms = [
        '#i_bInterlockOK',
        ...stepGuards.map((g) => `#i_bGuard_${sanitizeIdent(g.id)}`),
      ];
      lines.push(`         // 步序入口互锁判定 (${stepGuards.map((g) => normalizeDiagCodeHex(g.diagCodeHex)).join(', ')})`);
      lines.push(`         IF NOT (${guardTerms.join(' AND ')}) THEN`);
      for (const g of stepGuards) {
        lines.push(`            IF NOT #i_bGuard_${sanitizeIdent(g.id)} THEN`);
        lines.push(`               #q_wGuardDiagCode := ${normalizeDiagCodeHex(g.diagCodeHex)};`);
        lines.push(`            END_IF;`);
      }
      lines.push(`         ELSE`);
    }

    for (const inv of step.invocations) {
      const stmt = inv.sclStatement.trim();
      const formattedStmt = stmt.endsWith(';') ? stmt : `${stmt};`;
      lines.push(`${indent}${formattedStmt} // ${inv.actionLabel} -> ${inv.targetDiscreteState}`);
    }

    const waitTerms: string[] = [];
    const seenWait = new Set<string>();
    for (const inv of step.invocations) {
      const pred = (inv.waitPredicateScl || 'TRUE').trim();
      if (!seenWait.has(pred)) {
        seenWait.add(pred);
        waitTerms.push(waitTerms.length > 0 || step.invocations.length > 1 ? `(${pred})` : pred);
      }
    }
    const combinedWait = waitTerms.length > 0 ? waitTerms.join(' AND ') : 'TRUE';

    const { okStep, ngStep, defaultNextStepNo, sensorNode } = resolveBranchTargets(
      step,
      idx,
      sortedSteps,
      nodeById
    );

    lines.push(`${indent}IF (${combinedWait}) THEN`);
    if (okStep || ngStep) {
      const sensorDb = sensorNode?.instanceDb ?? `DB_${stationKey}_VisionCam`;
      const okCond = `"${sensorDb}".o_bPassOk`;
      const ngCond = `"${sensorDb}".o_bFailNg`;
      if (okStep && ngStep) {
        lines.push(`${indent}   IF ${okCond} THEN`);
        lines.push(`${indent}      #statStep := ${okStep.stepNo};`);
        lines.push(`${indent}   ELSIF ${ngCond} THEN`);
        lines.push(`${indent}      #statStep := ${ngStep.stepNo};`);
        lines.push(`${indent}   END_IF;`);
      } else if (okStep) {
        lines.push(`${indent}   IF ${okCond} THEN`);
        lines.push(`${indent}      #statStep := ${okStep.stepNo};`);
        lines.push(`${indent}   ELSE`);
        lines.push(`${indent}      #statStep := 999; // NG/默认分支安全收尾`);
        lines.push(`${indent}   END_IF;`);
      } else if (ngStep) {
        lines.push(`${indent}   IF ${ngCond} THEN`);
        lines.push(`${indent}      #statStep := ${ngStep.stepNo};`);
        lines.push(`${indent}   ELSE`);
        lines.push(`${indent}      #statStep := ${defaultNextStepNo};`);
        lines.push(`${indent}   END_IF;`);
      }
    } else {
      lines.push(`${indent}   #statStep := ${defaultNextStepNo};`);
    }
    lines.push(`${indent}END_IF;`);

    if (stepGuards.length > 0) {
      lines.push(`         END_IF;`);
    }
  });

  lines.push(``);
  lines.push(`      999: // [CycleDone] 周期完成`);
  lines.push(`         #q_bDone := TRUE;`);
  lines.push(`         IF NOT #i_bStart THEN`);
  lines.push(`            #statStep := 0;`);
  lines.push(`         END_IF;`);
  lines.push(`      ELSE`);
  lines.push(`         #statStep := 0;`);
  lines.push(`   END_CASE;`);
  lines.push(`END_FUNCTION_BLOCK`);

  const sclCode = lines.join('\n');
  const hashes = computeBlockHashes(sclCode);
  return {
    blockName,
    blockType: 'FB',
    stationId: station.stationId,
    sclCode,
    instanceDbName,
    ...hashes,
  };
}

interface InternalHomingSynthesis {
  hasCycleDeadlock: boolean;
  cycleNodeIds: string[];
  cycleEdgeIds: string[];
  layerActions: HomingNodeAction[][];
}

/**
 * Deterministic Kahn partial-order topological layering + Tarjan SCC deadlock detection.
 * Mirrors Algorithm 1 (`autoHomingSynth`) without taking a cross-module dependency.
 */
function synthesizeHomingInternal(station: StationHyperGraph): InternalHomingSynthesis {
  const actuators = station.spatialNodes.filter(
    (n) => n.role === 'ACTUATOR' && n.driverClass !== 'FB_AF_VisionSensor'
  );
  const actuatorMap = new Map(actuators.map((n) => [n.id, n]));
  const adj = new Map<string, string[]>();
  const inDegree = new Map<string, number>();
  const edgeSet = new Set<string>();

  for (const node of actuators) {
    adj.set(node.id, []);
    inDegree.set(node.id, 0);
  }

  for (const guard of station.guardEdges) {
    if (
      !actuatorMap.has(guard.fromNode) ||
      !actuatorMap.has(guard.toNode) ||
      guard.fromNode === guard.toNode
    ) {
      continue;
    }
    const key = `${guard.fromNode}->${guard.toNode}`;
    if (edgeSet.has(key)) continue;
    edgeSet.add(key);
    adj.get(guard.fromNode)!.push(guard.toNode);
    inDegree.set(guard.toNode, (inDegree.get(guard.toNode) ?? 0) + 1);
  }

  // Tarjan SCC detection for guard cycles
  let indexCounter = 0;
  const indices = new Map<string, number>();
  const lowlink = new Map<string, number>();
  const onStack = new Set<string>();
  const stack: string[] = [];
  const cycleNodeSet = new Set<string>();

  function strongConnect(v: string): void {
    indices.set(v, indexCounter);
    lowlink.set(v, indexCounter);
    indexCounter++;
    stack.push(v);
    onStack.add(v);

    for (const w of adj.get(v) ?? []) {
      if (!indices.has(w)) {
        strongConnect(w);
        lowlink.set(v, Math.min(lowlink.get(v)!, lowlink.get(w)!));
      } else if (onStack.has(w)) {
        lowlink.set(v, Math.min(lowlink.get(v)!, indices.get(w)!));
      }
    }

    if (lowlink.get(v) === indices.get(v)) {
      const scc: string[] = [];
      let w: string;
      do {
        w = stack.pop()!;
        onStack.delete(w);
        scc.push(w);
      } while (w !== v);

      if (scc.length >= 2) {
        for (const id of scc) cycleNodeSet.add(id);
      }
    }
  }

  for (const node of actuators) {
    if (!indices.has(node.id)) {
      strongConnect(node.id);
    }
  }

  if (cycleNodeSet.size > 0) {
    const cycleNodeIds = actuators.filter((n) => cycleNodeSet.has(n.id)).map((n) => n.id);
    const cycleEdgeIds = station.guardEdges
      .filter((g) => cycleNodeSet.has(g.fromNode) && cycleNodeSet.has(g.toNode))
      .map((g) => g.id);
    return {
      hasCycleDeadlock: true,
      cycleNodeIds,
      cycleEdgeIds,
      layerActions: [],
    };
  }

  // Kahn topological layering
  const layers: SpatialInstanceNode[][] = [];
  let zeroInQueue = actuators.filter((n) => (inDegree.get(n.id) ?? 0) === 0);
  let visited = 0;

  while (zeroInQueue.length > 0) {
    layers.push(zeroInQueue);
    visited += zeroInQueue.length;
    const nextQueue: SpatialInstanceNode[] = [];
    for (const u of zeroInQueue) {
      for (const vId of adj.get(u.id) ?? []) {
        const nextDeg = (inDegree.get(vId) ?? 0) - 1;
        inDegree.set(vId, nextDeg);
        if (nextDeg === 0) {
          const vNode = actuatorMap.get(vId);
          if (vNode) nextQueue.push(vNode);
        }
      }
    }
    zeroInQueue = nextQueue;
  }

  if (visited < actuators.length) {
    const remaining = actuators.filter((n) => (inDegree.get(n.id) ?? 0) > 0).map((n) => n.id);
    const remSet = new Set(remaining);
    const cycleEdgeIds = station.guardEdges
      .filter((g) => remSet.has(g.fromNode) && remSet.has(g.toNode))
      .map((g) => g.id);
    return {
      hasCycleDeadlock: true,
      cycleNodeIds: remaining,
      cycleEdgeIds,
      layerActions: [],
    };
  }

  const layerActions: HomingNodeAction[][] = layers.map((layer) =>
    layer.map((node) => {
      const dbName = node.instanceDb;
      const partPresentProtected = Boolean(
        node.hasPartPresentSensor ||
          (node.driverClass === 'FB_AF_Gripper' && node.cohesiveIoMap?.diPartPresent)
      );
      if (partPresentProtected) {
        const sclSnippet = [
          `IF "${dbName}".i_bPartPresent THEN`,
          `   "${dbName}".i_bCmdMaintainGrip := TRUE; // 带料防掉落保护：保持夹持`,
          `ELSE`,
          `   "${dbName}".i_bCmdHome := TRUE; // 空夹爪安全张开归位`,
          `END_IF;`,
        ].join('\n');
        const waitAtHomeExpr = `("${dbName}".o_bAtHome OR "${dbName}".i_bPartPresent)`;
        return { node, partPresentProtected: true, sclSnippet, waitAtHomeExpr };
      }

      const sclSnippet = `"${dbName}".i_bCmdHome := TRUE; // ${node.title} -> ${node.initialHomeState}`;
      const waitAtHomeExpr = `"${dbName}".o_bAtHome`;
      return { node, partPresentProtected: false, sclSnippet, waitAtHomeExpr };
    })
  );

  return {
    hasCycleDeadlock: false,
    cycleNodeIds: [],
    cycleEdgeIds: [],
    layerActions,
  };
}

function buildSafeFaultStopHomeScl(
  blockName: string,
  stationId: string,
  cycleNodeIds: string[],
  cycleEdgeIds: string[]
): string {
  return [
    `// AF-Studio v5 Auto-Homing Deadlock Guard - Safe Fault Stop Block`,
    `FUNCTION_BLOCK "${blockName}"`,
    `{ S7_Optimized_Access := 'TRUE' }`,
    `VERSION : 0.1`,
    `VAR_INPUT`,
    `   i_bHomeReq : Bool;`,
    `   i_bReset : Bool;`,
    `END_VAR`,
    `VAR_OUTPUT`,
    `   q_bAtHome : Bool;`,
    `   q_bHomeFault : Bool;`,
    `   q_wHomeFaultCode : Word;`,
    `   q_iHomeStep : Int;`,
    `END_VAR`,
    `VAR`,
    `   statHomeStep : Int := -1;`,
    `END_VAR`,
    `BEGIN`,
    `   // 检测到护栏互锁死锁环 (${stationId}):`,
    `   // Cycle Nodes: ${cycleNodeIds.join(', ') || 'UNKNOWN'}`,
    `   // Cycle Guard Edges: ${cycleEdgeIds.join(', ') || 'UNKNOWN'}`,
    `   #statHomeStep := -1;`,
    `   #q_iHomeStep := #statHomeStep;`,
    `   #q_bAtHome := FALSE;`,
    `   #q_bHomeFault := TRUE;`,
    `   #q_wHomeFaultCode := 16#DEAD;`,
    `END_FUNCTION_BLOCK`,
  ].join('\n');
}

function compileHomeSeqBlock(
  station: StationHyperGraph,
  homingOverride?: HomingSynthesisResult
): CompiledBlockArtifact {
  const stationKey = sanitizeIdent(station.stationId, 'ST');
  const blockName = `FB_${stationKey}_HomeSeq`;
  const instanceDbName = `DB_${stationKey}_Instances`;

  let sclCode: string;

  if (homingOverride) {
    if (homingOverride.hasCycleDeadlock) {
      sclCode = buildSafeFaultStopHomeScl(
        blockName,
        station.stationId,
        homingOverride.cycleNodeIds,
        homingOverride.cycleEdgeIds
      );
    } else if (homingOverride.generatedHomeScl?.trim()) {
      const normalizedOverride = homingOverride.generatedHomeScl
        .replace(/\r\n/g, '\n')
        .replace(/\r/g, '\n')
        .trim();
      if (/FUNCTION_BLOCK\b/i.test(normalizedOverride)) {
        sclCode = normalizedOverride;
      } else {
        sclCode = [
          `// AF-Studio v5 Deterministic Multi-Target Compiler - Auto-Homing FB (Override)`,
          `FUNCTION_BLOCK "${blockName}"`,
          `{ S7_Optimized_Access := 'TRUE' }`,
          `VERSION : 0.1`,
          `VAR_INPUT`,
          `   i_bHomeReq : Bool;`,
          `   i_bReset : Bool;`,
          `END_VAR`,
          `VAR_OUTPUT`,
          `   q_bAtHome : Bool;`,
          `   q_bHomeFault : Bool;`,
          `   q_iHomeStep : Int;`,
          `END_VAR`,
          `VAR`,
          `   statHomeStep : Int := 0;`,
          `END_VAR`,
          `BEGIN`,
          `   ${normalizedOverride}`,
          `END_FUNCTION_BLOCK`,
        ].join('\n');
      }
    } else {
      sclCode = compileHomeSeqFromSynthesis(
        blockName,
        station.stationId,
        synthesizeHomingInternal(station)
      );
    }
  } else {
    sclCode = compileHomeSeqFromSynthesis(
      blockName,
      station.stationId,
      synthesizeHomingInternal(station)
    );
  }

  const hashes = computeBlockHashes(sclCode);
  return {
    blockName,
    blockType: 'FB',
    stationId: station.stationId,
    sclCode,
    instanceDbName,
    ...hashes,
  };
}

function compileHomeSeqFromSynthesis(
  blockName: string,
  stationId: string,
  synthesis: InternalHomingSynthesis
): string {
  if (synthesis.hasCycleDeadlock) {
    return buildSafeFaultStopHomeScl(
      blockName,
      stationId,
      synthesis.cycleNodeIds,
      synthesis.cycleEdgeIds
    );
  }

  const lines: string[] = [
    `// AF-Studio v5 Deterministic Multi-Target Compiler - Kahn + Tarjan Auto-Homing FB`,
    `FUNCTION_BLOCK "${blockName}"`,
    `{ S7_Optimized_Access := 'TRUE' }`,
    `VERSION : 0.1`,
    `VAR_INPUT`,
    `   i_bHomeReq : Bool;`,
    `   i_bReset : Bool;`,
    `END_VAR`,
    `VAR_OUTPUT`,
    `   q_bAtHome : Bool;`,
    `   q_bHomeFault : Bool;`,
    `   q_iHomeStep : Int;`,
    `END_VAR`,
    `VAR`,
    `   statHomeStep : Int := 0;`,
    `END_VAR`,
    `BEGIN`,
    `   IF #i_bReset THEN`,
    `      #statHomeStep := 0;`,
    `      #q_bAtHome := FALSE;`,
    `      #q_bHomeFault := FALSE;`,
    `      #q_iHomeStep := 0;`,
    `      RETURN;`,
    `   END_IF;`,
    ``,
    `   #q_bHomeFault := FALSE;`,
    `   #q_iHomeStep := #statHomeStep;`,
    ``,
    `   CASE #statHomeStep OF`,
    `      0: // [HomeIdle] 等待回原位请求`,
    `         #q_bAtHome := FALSE;`,
    `         IF #i_bHomeReq THEN`,
    `            #statHomeStep := ${synthesis.layerActions.length > 0 ? 10 : 999};`,
    `         END_IF;`,
  ];

  synthesis.layerActions.forEach((actions, layerIdx) => {
    const stepNo = (layerIdx + 1) * 10;
    const nextStepNo = layerIdx + 1 < synthesis.layerActions.length ? (layerIdx + 2) * 10 : 999;
    lines.push(``);
    lines.push(`      ${stepNo}: // [Kahn 拓扑归航层 Layer ${layerIdx + 1}]`);
    for (const action of actions) {
      for (const snippetLine of action.sclSnippet.split('\n')) {
        lines.push(`         ${snippetLine}`);
      }
    }
    const waitAll = actions.map((a) => a.waitAtHomeExpr).join(' AND ') || 'TRUE';
    lines.push(`         IF ${waitAll} THEN`);
    lines.push(`            #statHomeStep := ${nextStepNo};`);
    lines.push(`         END_IF;`);
  });

  lines.push(``);
  lines.push(`      999: // [AtHome] 全工站执行器已安全归航`);
  lines.push(`         #q_bAtHome := TRUE;`);
  lines.push(`         IF NOT #i_bHomeReq THEN`);
  lines.push(`            #statHomeStep := 0;`);
  lines.push(`         END_IF;`);
  lines.push(`      ELSE`);
  lines.push(`         #statHomeStep := 0;`);
  lines.push(`   END_CASE;`);
  lines.push(`END_FUNCTION_BLOCK`);

  return lines.join('\n');
}

function compileGuardDiagBlock(station: StationHyperGraph): CompiledBlockArtifact {
  const stationKey = sanitizeIdent(station.stationId, 'ST');
  const blockName = `FC_${stationKey}_GuardDiag`;
  const nodeById = new Map(station.spatialNodes.map((n) => [n.id, n]));

  const targetNodeIds: string[] = [];
  const seenTargets = new Set<string>();
  for (const g of station.guardEdges) {
    if (!seenTargets.has(g.toNode)) {
      seenTargets.add(g.toNode);
      targetNodeIds.push(g.toNode);
    }
  }

  const lines: string[] = [
    `// AF-Studio v5 Deterministic Multi-Target Compiler - Safety Guard & HMI Diagnostics FC`,
    `FUNCTION "${blockName}" : Word`,
    `{ S7_Optimized_Access := 'TRUE' }`,
    `VERSION : 0.1`,
    `VAR_INPUT`,
  ];

  if (station.guardEdges.length === 0) {
    lines.push(`   i_bStationEnable : Bool := TRUE;`);
  } else {
    for (const guard of station.guardEdges) {
      const pin = `i_bGuard_${sanitizeIdent(guard.id)}`;
      const crossNote = guard.crossStationRef
        ? ` [跨站源: ${guard.crossStationRef.upstreamStationId}/${guard.crossStationRef.upstreamInstanceId} 端子=${guard.crossStationRef.physicalTerminal || '-'} 线号=${guard.crossStationRef.cabinetWireTag || '-'}]`
        : '';
      lines.push(`   ${pin} : Bool; // ${guard.humanDescription}${crossNote}`);
    }
  }

  lines.push(`END_VAR`);
  lines.push(`VAR_OUTPUT`);
  lines.push(`   q_bAllGuardsHealthy : Bool;`);
  lines.push(`   q_dwDiagBitmask : DWord;`);
  for (const targetId of targetNodeIds) {
    lines.push(`   q_bInterlock_${sanitizeIdent(targetId)} : Bool;`);
  }
  lines.push(`END_VAR`);
  lines.push(`BEGIN`);
  lines.push(`   REGION Safety_Invariants_And_Diagnostic_Bitmask`);
  lines.push(`      #${blockName} := 16#0000;`);
  lines.push(`      #q_bAllGuardsHealthy := TRUE;`);
  lines.push(`      #q_dwDiagBitmask := 16#00000000;`);

  for (const targetId of targetNodeIds) {
    const targetIdent = sanitizeIdent(targetId);
    const targetNode = nodeById.get(targetId);
    lines.push(`      #q_bInterlock_${targetIdent} := TRUE;`);
    if (targetNode?.role === 'ACTUATOR') {
      lines.push(`      "${targetNode.instanceDb}".i_bInterlockOK := TRUE;`);
      lines.push(`      "${targetNode.instanceDb}".o_wBlockDiagCode := 16#0000;`);
    }
  }

  if (station.guardEdges.length === 0) {
    lines.push(`      // 当前工站无额外空间安全护栏边`);
  } else {
    station.guardEdges.forEach((guard, idx) => {
      const pin = `i_bGuard_${sanitizeIdent(guard.id)}`;
      const targetIdent = sanitizeIdent(guard.toNode);
      const targetNode = nodeById.get(guard.toNode);
      const diagHex = normalizeDiagCodeHex(guard.diagCodeHex);
      const bitmask = formatDWordBitmask(idx);

      lines.push(``);
      lines.push(
        `      // 护栏 [${guard.id}] ${diagHex}: ${guard.fromNode}(${guard.requiredSourceState}) -> ${guard.toNode}.${guard.toPort} | ${guard.humanDescription}`
      );
      if (guard.crossStationRef) {
        const ref = guard.crossStationRef;
        lines.push(
          `      // 跨站溯源 (crossStationRef): 源工站=${ref.upstreamStationId} | 源实例=${ref.upstreamInstanceId} | 源端口=${ref.upstreamPortId ?? '-'} | 源端子=${ref.physicalTerminal || '-'} | 线号=${ref.cabinetWireTag || '-'}${ref.l1EdgeId ? ` | L1边=${ref.l1EdgeId}` : ''}`
        );
      }
      lines.push(`      IF NOT #${pin} THEN`);
      lines.push(`         #q_bAllGuardsHealthy := FALSE;`);
      lines.push(`         #q_bInterlock_${targetIdent} := FALSE;`);
      lines.push(`         #q_dwDiagBitmask := #q_dwDiagBitmask OR ${bitmask};`);
      lines.push(`         IF #${blockName} = 16#0000 THEN`);
      lines.push(`            #${blockName} := ${diagHex};`);
      lines.push(`         END_IF;`);
      if (targetNode?.role === 'ACTUATOR') {
        lines.push(`         "${targetNode.instanceDb}".i_bInterlockOK := FALSE;`);
        lines.push(`         "${targetNode.instanceDb}".o_wBlockDiagCode := ${diagHex};`);
      }
      lines.push(`      END_IF;`);
    });
  }

  lines.push(`   END_REGION`);
  lines.push(`END_FUNCTION`);

  const sclCode = lines.join('\n');
  const hashes = computeBlockHashes(sclCode);
  return {
    blockName,
    blockType: 'FC',
    stationId: station.stationId,
    sclCode,
    ...hashes,
  };
}

/**
 * 100% deterministic multi-target SCL compiler for a single station hypergraph.
 * Generates 4 TIA Portal SCL blocks:
 *   1. `DB_<stationId>_Instances`
 *   2. `FB_<stationId>_AutoSeq`
 *   3. `FB_<stationId>_HomeSeq`
 *   4. `FC_<stationId>_GuardDiag`
 * Never embeds wall-clock timestamps or UI layout coordinates (`position.x/y`).
 */
export function compileStationHyperGraph(
  station: StationHyperGraph,
  homingOverride?: HomingSynthesisResult
): CompiledBlockArtifact[] {
  if (station.orchestration) throw new Error('虚拟工位编排当前仅支持离线模拟');
  const physicalStatus = cmBindingStatus(station);
  if (physicalStatus) throw new Error(physicalStatus);
  if (stationHasUnboundSignals(station)) throw new Error('工位存在待绑定的现场 I/O 或工步引用');
  return [
    compileInstancesDbBlock(station),
    compileAutoSeqBlock(station),
    compileHomeSeqBlock(station, homingOverride),
    compileGuardDiagBlock(station),
  ];
}
