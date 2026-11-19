import { describe, expect, it } from 'vitest';
import type {
  AfStudioWorkspaceData,
  GhostGraphTransaction,
  SafetyGuardEdge,
  SpatialInstanceNode,
  StationHyperGraph,
  TemporalStepHyperEdge,
} from '../../ir/afHyperGraph.types';
import { createDefaultAfStudioWorkspace } from '../../ir/seedHyperGraphs';
import {
  DeadlockCycleError,
  synthesizeSafeHomingSequence,
} from '../autoHomingSynth';
import { traceMinimalFalsifyingCutSet } from '../minimalCutSetTracer';
import { layoutWithPinnedAnchors } from '../pinnedSugiyama';
import {
  runSymbolicVerifierAsync,
  verifyStationHyperGraph,
} from '../symbolicVerifier';
import { handleVerifierWorkerMessage } from '../symbolicVerifier.worker';

function makeActuator(
  id: string,
  title: string,
  driverClass: SpatialInstanceNode['driverClass'] = 'FB_AF_Actuator2Pos',
  opts?: Partial<SpatialInstanceNode>
): SpatialInstanceNode {
  return {
    id,
    role: 'ACTUATOR',
    title,
    driverClass,
    instanceDb: `DB_${id}`,
    position: { x: 100, y: 100 },
    isPinned: false,
    discreteStates:
      driverClass === 'FB_AF_AxisMotion'
        ? ['Pos_Home_0', 'Pos_Press_245']
        : driverClass === 'FB_AF_Gripper'
          ? ['Opened', 'Closed']
          : ['AtHome', 'AtWork'],
    initialHomeState:
      driverClass === 'FB_AF_AxisMotion'
        ? 'Pos_Home_0'
        : driverClass === 'FB_AF_Gripper'
          ? 'Opened'
          : 'AtHome',
    cohesiveIoMap: {},
    inPorts: [
      { id: 'IN_EXEC', label: '▶ 触发', type: 'SEQ' },
      { id: 'IN_GUARD', label: '🛡️ 护栏', type: 'GUARD' },
    ],
    outPorts: [
      { id: 'OUT_DONE', label: '● 完成', type: 'SEQ' },
      { id: 'OUT_AT_HOME', label: '🛡️ 原位', type: 'GUARD' },
    ],
    ...opts,
  };
}

function makeGuard(
  id: string,
  fromNode: string,
  toNode: string,
  requiredSourceState = 'AtHome',
  diagCodeHex = '16#0201'
): SafetyGuardEdge {
  return {
    id,
    fromNode,
    fromPort: 'OUT_AT_HOME',
    toNode,
    toPort: 'IN_GUARD',
    requiredSourceState,
    diagCodeHex,
    humanDescription: `${fromNode} -> ${toNode}`,
    isHealthy: true,
  };
}

function boxesOverlap(
  a: { x: number; y: number },
  b: { x: number; y: number },
  w: number,
  h: number
): boolean {
  return a.x < b.x + w && a.x + w > b.x && a.y < b.y + h && a.y + h > b.y;
}

describe('Algorithm 1: autoHomingSynth', () => {
  it('synthesizes Kahn layered concurrent homing and gripper part-present protection for ST20', () => {
    const ws = createDefaultAfStudioWorkspace();
    const st20 = ws.stationGraphs.ST20;

    const result = synthesizeSafeHomingSequence(st20);
    expect(result.hasCycleDeadlock).toBe(false);
    expect(result.cycleNodeIds).toEqual([]);
    expect(result.cycleEdgeIds).toEqual([]);

    // Layer 0: Gripper + Z cylinder retract concurrently; Vision sensor is excluded
    expect(result.concurrentLayers).toHaveLength(2);
    expect(result.concurrentLayers[0].map((n) => n.id)).toEqual([
      'INST_ST20_GRIP',
      'INST_ST20_Z',
    ]);
    // Layer 1: Axis X waits until Z cylinder is safely at home
    expect(result.concurrentLayers[1].map((n) => n.id)).toEqual(['INST_ST20_X']);

    const gripAction = result.layerActions[0].find(
      (a) => a.node.id === 'INST_ST20_GRIP'
    )!;
    expect(gripAction.partPresentProtected).toBe(true);
    expect(gripAction.sclSnippet).toBe(
      'IF "DB_ST20_Gripper1".i_bPartPresent THEN "DB_ST20_Gripper1".MaintainGrip(); ELSE "DB_ST20_Gripper1".OpenGrip(); END_IF;'
    );

    const zAction = result.layerActions[0].find((a) => a.node.id === 'INST_ST20_Z')!;
    expect(zAction.partPresentProtected).toBe(false);
    expect(zAction.sclSnippet).toBe('"DB_ST20_CylZ".RetractHome();');

    const xAction = result.layerActions[1][0];
    expect(xAction.sclSnippet).toBe('"DB_ST20_AxisX".MoveAbs(0.0);');

    expect(result.generatedHomeScl).toContain('FUNCTION_BLOCK "FB_ST20_HomeSeq"');
    expect(result.generatedHomeScl).toContain('CASE #statHomeStep OF');
    expect(result.generatedHomeScl).toContain('MaintainGrip()');
    expect(result.generatedHomeScl).toContain('OpenGrip()');

    // Convenience overload (nodes, guards, stationId) yields identical layers
    const viaNodes = synthesizeSafeHomingSequence(
      st20.spatialNodes,
      st20.guardEdges,
      'ST20'
    );
    expect(viaNodes.concurrentLayers.map((l) => l.map((n) => n.id))).toEqual(
      result.concurrentLayers.map((l) => l.map((n) => n.id))
    );
  });

  it('detects 2-node and 3-node Tarjan SCC guard deadlocks and self-loops', () => {
    const a = makeActuator('ACT_A', '气缸A');
    const b = makeActuator('ACT_B', '伺服B', 'FB_AF_AxisMotion');
    const c = makeActuator('ACT_C', '气缸C');
    const d = makeActuator('ACT_D', '下游独立气缸D');

    // 2-node deadlock: A <-> B
    const twoNodeRes = synthesizeSafeHomingSequence(
      [a, b],
      [makeGuard('G_AB', 'ACT_A', 'ACT_B'), makeGuard('G_BA', 'ACT_B', 'ACT_A', 'Pos_Home_0')],
      'ST_DEAD2'
    );
    expect(twoNodeRes.hasCycleDeadlock).toBe(true);
    expect(twoNodeRes.cycleNodeIds).toEqual(['ACT_A', 'ACT_B']);
    expect(twoNodeRes.cycleEdgeIds).toEqual(['G_AB', 'G_BA']);
    expect(twoNodeRes.concurrentLayers).toEqual([]);
    expect(twoNodeRes.layerActions).toEqual([]);
    expect(twoNodeRes.generatedHomeScl).toContain('#statHomeFault := TRUE;');
    expect(twoNodeRes.generatedHomeScl).toContain('DEADLOCK');

    // 3-node deadlock: A -> B -> C -> A, plus downstream D (C -> D is NOT part of the cycle)
    const threeNodeRes = synthesizeSafeHomingSequence(
      [a, b, c, d],
      [
        makeGuard('G_AB', 'ACT_A', 'ACT_B'),
        makeGuard('G_BC', 'ACT_B', 'ACT_C', 'Pos_Home_0'),
        makeGuard('G_CA', 'ACT_C', 'ACT_A'),
        makeGuard('G_CD', 'ACT_C', 'ACT_D'),
      ],
      'ST_DEAD3'
    );
    expect(threeNodeRes.hasCycleDeadlock).toBe(true);
    expect(threeNodeRes.cycleNodeIds).toEqual(['ACT_A', 'ACT_B', 'ACT_C']);
    expect(threeNodeRes.cycleEdgeIds).toEqual(['G_AB', 'G_BC', 'G_CA']);

    // Self-loop deadlock: A -> A
    const selfLoopRes = synthesizeSafeHomingSequence(
      [a],
      [makeGuard('G_AA', 'ACT_A', 'ACT_A')],
      'ST_SELF'
    );
    expect(selfLoopRes.hasCycleDeadlock).toBe(true);
    expect(selfLoopRes.cycleNodeIds).toEqual(['ACT_A']);
    expect(selfLoopRes.cycleEdgeIds).toEqual(['G_AA']);

    // Optional throwOnDeadlock throws DeadlockCycleError
    expect(() =>
      synthesizeSafeHomingSequence(
        [a, b],
        [makeGuard('G_AB', 'ACT_A', 'ACT_B'), makeGuard('G_BA', 'ACT_B', 'ACT_A', 'Pos_Home_0')],
        'ST_DEAD2',
        { throwOnDeadlock: true }
      )
    ).toThrowError(DeadlockCycleError);
  });
});

describe('Algorithm 2: symbolicVerifier & Worker', () => {
  it('passes all default AssyLine_01 stations within 30ms', async () => {
    const ws = createDefaultAfStudioWorkspace();

    for (const station of Object.values(ws.stationGraphs)) {
      const report = verifyStationHyperGraph(station);
      expect(report.passed).toBe(true);
      expect(report.violations).toEqual([]);
      expect(report.warnings).toEqual([]);
      expect(report.elapsedMs).toBeLessThan(30);
      expect(report.exploredStateCount).toBeGreaterThanOrEqual(2);
    }

    const asyncReport = await runSymbolicVerifierAsync(ws.stationGraphs.ST20);
    expect(asyncReport.passed).toBe(true);
    expect(asyncReport.elapsedMs).toBeLessThan(30);

    const workerReport = handleVerifierWorkerMessage({
      station: ws.stationGraphs.ST20,
      ghostTx: null,
    });
    expect(workerReport.passed).toBe(true);
    expect(workerReport.violations).toEqual([]);
  });

  it('catches missing Z-axis guardrail and passes after applying suggestedGuardEdge', () => {
    const ws = createDefaultAfStudioWorkspace();
    const st20 = ws.stationGraphs.ST20;
    st20.guardEdges = st20.guardEdges.filter((g) => g.id !== 'G_ST20_Z_TO_X');

    const failedReport = verifyStationHyperGraph(st20);
    expect(failedReport.passed).toBe(false);
    expect(failedReport.elapsedMs).toBeLessThan(30);

    const missingViolation = failedReport.violations.find(
      (v) => v.kind === 'MISSING_GUARDRAIL'
    );
    expect(missingViolation).toBeDefined();
    expect(missingViolation!.stepNo).toBe(30);
    expect(missingViolation!.nodeId).toBe('INST_ST20_X');
    expect(missingViolation!.interferingNodeId).toBe('INST_ST20_Z');
    expect(missingViolation!.suggestedGuardEdge).toBeDefined();
    expect(missingViolation!.suggestedGuardEdge!.fromNode).toBe('INST_ST20_Z');
    expect(missingViolation!.suggestedGuardEdge!.toNode).toBe('INST_ST20_X');
    expect(missingViolation!.suggestedGuardEdge!.toPort).toBe('IN_GUARD');
    expect(missingViolation!.suggestedGuardEdge!.requiredSourceState).toBe('AtHome');
    expect(missingViolation!.suggestedGuardEdge!.diagCodeHex).toBe('16#0201');

    // One-click fix patch via ghostTx (without mutating st20) passes verification
    const fixTx: GhostGraphTransaction = {
      txId: 'TX_FIX_GUARD',
      stationId: 'ST20',
      summary: '一键补齐 Z 轴原位护栏',
      addedNodes: [],
      addedGuardEdges: [missingViolation!.suggestedGuardEdge!],
      addedTemporalSteps: [],
      verificationPassed: false,
      verifierWarnings: [],
    };
    const fixedReport = verifyStationHyperGraph(st20, fixTx);
    expect(fixedReport.passed).toBe(true);
    expect(fixedReport.violations).toEqual([]);
    // Input station remains unmutated
    expect(st20.guardEdges.some((g) => g.id === 'G_ST20_Z_TO_X')).toBe(false);
  });

  it('detects COLLISION_REACHABLE when vertical actuator is non-home while axis moves', () => {
    const boundIn: SpatialInstanceNode = {
      id: 'BOUND_IN',
      role: 'BOUNDARY_IN',
      title: '左边界',
      driverClass: 'STATION_INPUT_PORT',
      instanceDb: 'BOUND_IN',
      position: { x: 20, y: 100 },
      isPinned: true,
      discreteStates: ['WaitingPart', 'PartArrived'],
      initialHomeState: 'WaitingPart',
      cohesiveIoMap: {},
      inPorts: [],
      outPorts: [{ id: 'OUT_PART_ARRIVED', label: '触发', type: 'SEQ' }],
    };
    const cylZ = makeActuator('CYL_Z', 'Z轴压装缸');
    const axisX = makeActuator('AXIS_X', 'X轴搬运伺服', 'FB_AF_AxisMotion');

    const collisionStation: StationHyperGraph = {
      stationId: 'ST_COLLISION',
      stationName: '干涉测试工站',
      spatialNodes: [boundIn, cylZ, axisX],
      guardEdges: [makeGuard('G_Z_X', 'CYL_Z', 'AXIS_X')],
      temporalSteps: [
        {
          id: 'S10',
          stepNo: 10,
          title: 'Z轴先下压未复位',
          fromNode: 'BOUND_IN',
          fromPort: 'OUT_PART_ARRIVED',
          invocations: [
            {
              targetNodeId: 'CYL_Z',
              targetPortId: 'IN_EXEC',
              methodId: 'ExtendWork',
              actionLabel: 'Z轴下压',
              targetDiscreteState: 'AtWork',
              sclStatement: '#DB_CYL_Z.ExtendWork();',
              waitPredicateScl: '"DB_CYL_Z".o_bAtWork',
            },
          ],
        },
        {
          id: 'S20',
          stepNo: 20,
          title: 'X轴带Z轴撞模横移',
          fromNode: 'CYL_Z',
          fromPort: 'OUT_DONE',
          invocations: [
            {
              targetNodeId: 'AXIS_X',
              targetPortId: 'IN_EXEC',
              methodId: 'MovePress',
              actionLabel: 'X轴移至245mm',
              targetDiscreteState: 'Pos_Press_245',
              sclStatement: '#DB_AXIS_X.MoveAbs(245.0);',
              waitPredicateScl: '"DB_AXIS_X".o_bInPos',
            },
          ],
        },
      ],
    };

    const report = verifyStationHyperGraph(collisionStation);
    expect(report.passed).toBe(false);
    expect(report.violations.some((v) => v.kind === 'COLLISION_REACHABLE')).toBe(true);
    const col = report.violations.find((v) => v.kind === 'COLLISION_REACHABLE')!;
    expect(col.stepNo).toBe(20);
    expect(col.nodeId).toBe('AXIS_X');
    expect(col.interferingNodeId).toBe('CYL_Z');
  });

  it('detects ACTUATOR_CONTENTION, GUARD_CYCLE_DEADLOCK, and unreachable step warnings', () => {
    const ws = createDefaultAfStudioWorkspace();
    const st20 = ws.stationGraphs.ST20;

    const contentionAndCycleTx: GhostGraphTransaction = {
      txId: 'TX_ERR',
      stationId: 'ST20',
      summary: '并发竞争 + 护栏环 + 孤立步',
      addedNodes: [],
      addedGuardEdges: [
        {
          id: 'G_CYCLE_X_TO_Z',
          fromNode: 'INST_ST20_X',
          fromPort: 'OUT_DONE',
          toNode: 'INST_ST20_Z',
          toPort: 'IN_EXEC',
          requiredSourceState: 'Pos_Home_0',
          diagCodeHex: '16#0299',
          humanDescription: '非法反向互锁构成死锁环',
        },
      ],
      addedTemporalSteps: [
        {
          id: 'T_CONTENTION',
          stepNo: 25,
          title: '同拍双目标竞争',
          fromNode: 'INST_ST20_CAM',
          fromPort: 'OUT_NG',
          invocations: [
            {
              targetNodeId: 'INST_ST20_X',
              targetPortId: 'IN_EXEC',
              methodId: 'MovePick',
              actionLabel: '移至取料位',
              targetDiscreteState: 'Pos_Pick_120',
              sclStatement: '#DB_ST20_AxisX.MoveAbs(120.0);',
              waitPredicateScl: '"DB_ST20_AxisX".o_bInPos',
            },
            {
              targetNodeId: 'INST_ST20_X',
              targetPortId: 'IN_EXEC',
              methodId: 'MoveReject',
              actionLabel: '同时移至抛料位',
              targetDiscreteState: 'Pos_Reject_410',
              sclStatement: '#DB_ST20_AxisX.MoveAbs(410.0);',
              waitPredicateScl: '"DB_ST20_AxisX".o_bInPos',
            },
          ],
        },
        {
          id: 'T_ISOLATED',
          stepNo: 90,
          title: '孤立未接入步',
          fromNode: 'NON_EXISTENT_SOURCE',
          fromPort: 'OUT_DONE',
          invocations: [
            {
              targetNodeId: 'INST_ST20_GRIP',
              targetPortId: 'IN_EXEC',
              methodId: 'GripOpen',
              actionLabel: '张开',
              targetDiscreteState: 'Opened',
              sclStatement: '#DB_ST20_Gripper1.OpenGrip();',
              waitPredicateScl: '"DB_ST20_Gripper1".o_bOpened',
            },
          ],
        },
      ],
      verificationPassed: false,
      verifierWarnings: [],
    };

    const report = verifyStationHyperGraph(st20, contentionAndCycleTx);
    expect(report.passed).toBe(false);
    expect(report.elapsedMs).toBeLessThan(30);

    const contention = report.violations.find((v) => v.kind === 'ACTUATOR_CONTENTION');
    expect(contention).toBeDefined();
    expect(contention!.stepNo).toBe(25);
    expect(contention!.nodeId).toBe('INST_ST20_X');

    const cycle = report.violations.find((v) => v.kind === 'GUARD_CYCLE_DEADLOCK');
    expect(cycle).toBeDefined();

    expect(report.warnings.length).toBeGreaterThanOrEqual(1);
    expect(report.warnings.some((w) => w.includes('S90'))).toBe(true);
  });

  it('validates Ghost NG branch under 30ms on a scaled 25-node station', () => {
    const ws = createDefaultAfStudioWorkspace();
    const st20 = ws.stationGraphs.ST20;

    // Ghost NG branch proposed by AI
    const ngTx: GhostGraphTransaction = {
      txId: 'TX_NG',
      stationId: 'ST20',
      summary: '视觉 NG 去抛料位分支',
      addedNodes: [],
      addedGuardEdges: [],
      addedTemporalSteps: [
        {
          id: 'GW_NG_1',
          stepNo: 35,
          title: 'NG移至抛料位',
          fromNode: 'INST_ST20_CAM',
          fromPort: 'OUT_NG',
          branchPredicate: 'NG',
          invocations: [
            {
              targetNodeId: 'INST_ST20_X',
              targetPortId: 'IN_EXEC',
              methodId: 'MoveReject',
              actionLabel: '移至NG抛料位 (410mm)',
              targetDiscreteState: 'Pos_Reject_410',
              sclStatement: '#DB_ST20_AxisX.MoveAbs(410.0);',
              waitPredicateScl: '"DB_ST20_AxisX".o_bInPos',
            },
          ],
        },
        {
          id: 'GW_NG_2',
          stepNo: 36,
          title: 'NG张开夹爪抛料',
          fromNode: 'INST_ST20_X',
          fromPort: 'OUT_DONE',
          invocations: [
            {
              targetNodeId: 'INST_ST20_GRIP',
              targetPortId: 'IN_EXEC',
              methodId: 'GripOpen',
              actionLabel: '张开释放NG电芯',
              targetDiscreteState: 'Opened',
              sclStatement: '#DB_ST20_Gripper1.OpenGrip();',
              waitPredicateScl: '"DB_ST20_Gripper1".o_bOpened',
            },
          ],
        },
      ],
      verificationPassed: true,
      verifierWarnings: [],
    };
    const ngReport = verifyStationHyperGraph(st20, ngTx);
    expect(ngReport.passed).toBe(true);
    expect(ngReport.elapsedMs).toBeLessThan(30);

    // 25-actuator stress test stays well below 30ms
    const extraNodes = Array.from({ length: 20 }, (_, i) =>
      makeActuator(`EXTRA_GRIP_${i}`, `夹爪_${i}`, 'FB_AF_Gripper')
    );
    const stressSteps: TemporalStepHyperEdge[] = extraNodes.map((n, i) => ({
      id: `T_STRESS_${i}`,
      stepNo: 100 + i * 10,
      title: `Stress ${i}`,
      fromNode: i === 0 ? 'INST_ST20_Z' : `EXTRA_GRIP_${i - 1}`,
      fromPort: 'OUT_DONE',
      invocations: [
        {
          targetNodeId: n.id,
          targetPortId: 'IN_EXEC',
          methodId: 'GripClose',
          actionLabel: '闭合',
          targetDiscreteState: 'Closed',
          sclStatement: `#${n.instanceDb}.CloseGrip();`,
          waitPredicateScl: `"${n.instanceDb}".o_bClosed`,
        },
      ],
    }));

    const stressReport = verifyStationHyperGraph(st20, {
      txId: 'TX_STRESS',
      stationId: 'ST20',
      summary: '压力测试',
      addedNodes: extraNodes,
      addedGuardEdges: [],
      addedTemporalSteps: stressSteps,
      verificationPassed: true,
      verifierWarnings: [],
    });
    expect(stressReport.passed).toBe(true);
    expect(stressReport.elapsedMs).toBeLessThan(30);
  });
});

describe('Algorithm 3: minimalCutSetTracer', () => {
  it('prunes healthy %I10.0 branch and traces cross-station %I0.4 / X12:04 with 3-stage camera fly-to', () => {
    const ws: AfStudioWorkspaceData = createDefaultAfStudioWorkspace();

    // Default seed without explicit liveSignals
    const traceDefault = traceMinimalFalsifyingCutSet(
      ws.projectGraph,
      ws.stationGraphs,
      'ST20',
      30
    );
    expect(traceDefault.blockedStationId).toBe('ST20');
    expect(traceDefault.blockedStepNo).toBe(30);
    expect(traceDefault.blockedNodeId).toBe('INST_ST20_X');
    expect(traceDefault.prunedHealthyEdgeIds).toEqual(['G_ST20_Z_TO_X']);
    expect(traceDefault.falsifiedEdgeIds).toEqual(['G_ST20_ST10_TO_X']);
    expect(traceDefault.l1CutSetEdgeId).toBe('E_L1_2');
    expect(traceDefault.rootCauseStationId).toBe('ST10');
    expect(traceDefault.rootCauseNodeId).toBe('INST_ST10_TRANS');
    expect(traceDefault.rootPhysicalTerminal).toBe('%I0.4');
    expect(traceDefault.rootCabinetWireTag).toBe('X12:04');
    expect(traceDefault.flyToStages).toHaveLength(3);
    expect(traceDefault.flyToStages.map((s) => [s.stageIndex, s.layer])).toEqual([
      [1, 'STATION'],
      [2, 'PROJECT'],
      [3, 'STATION'],
    ]);
    expect(traceDefault.flyToStages[0].stationId).toBe('ST20');
    expect(traceDefault.flyToStages[0].focusEntityId).toBe('INST_ST20_X');
    expect(traceDefault.flyToStages[1].focusEntityId).toBe('E_L1_2');
    expect(traceDefault.flyToStages[2].stationId).toBe('ST10');
    expect(traceDefault.flyToStages[2].focusEntityId).toBe('INST_ST10_TRANS');

    // Explicit liveSignals { '%I10.0': true, '%I0.4': false }
    const traceLive = traceMinimalFalsifyingCutSet(
      ws.projectGraph,
      ws.stationGraphs,
      'ST20',
      30,
      { '%I10.0': true, '%I0.4': false }
    );
    expect(traceLive.prunedHealthyEdgeIds).toEqual(['G_ST20_Z_TO_X']);
    expect(traceLive.falsifiedEdgeIds).toEqual(['G_ST20_ST10_TO_X']);
    expect(traceLive.rootPhysicalTerminal).toBe('%I0.4');

    // After repairing %I0.4 = true, both guardrails are pruned as healthy
    const traceRepaired = traceMinimalFalsifyingCutSet(
      ws.projectGraph,
      ws.stationGraphs,
      'ST20',
      30,
      { '%I10.0': true, '%I0.4': true }
    );
    expect(traceRepaired.prunedHealthyEdgeIds).toEqual([
      'G_ST20_Z_TO_X',
      'G_ST20_ST10_TO_X',
    ]);
    expect(traceRepaired.falsifiedEdgeIds).toEqual([]);

    // Local Z-axis failure (%I10.0 = false, %I0.4 = true)
    const traceLocalFault = traceMinimalFalsifyingCutSet(
      ws.projectGraph,
      ws.stationGraphs,
      'ST20',
      30,
      { '%I10.0': false, '%I0.4': true }
    );
    expect(traceLocalFault.prunedHealthyEdgeIds).toEqual(['G_ST20_ST10_TO_X']);
    expect(traceLocalFault.falsifiedEdgeIds).toEqual(['G_ST20_Z_TO_X']);
    expect(traceLocalFault.rootCauseStationId).toBe('ST20');
    expect(traceLocalFault.rootCauseNodeId).toBe('INST_ST20_Z');
    expect(traceLocalFault.rootPhysicalTerminal).toBe('%I10.0');
  });

  it('recursively traces multi-hop cross-station boolean DAG to upstream root cause', () => {
    const ws = createDefaultAfStudioWorkspace();
    // Inject an upstream ST00 feeding ST10's INST_ST10_TRANS
    ws.stationGraphs.ST00 = {
      stationId: 'ST00',
      stationName: 'ST00 · 上料机',
      spatialNodes: [
        makeActuator('INST_ST00_FEED', '上料推杆', 'FB_AF_Actuator2Pos', {
          cohesiveIoMap: { diHome: '%I0.1', cabinetTerminal: 'X10:01' },
        }),
      ],
      guardEdges: [],
      temporalSteps: [],
    };
    ws.stationGraphs.ST10.guardEdges.push({
      id: 'G_ST10_FROM_ST00',
      fromNode: 'BOUND_IN_ST10',
      fromPort: 'OUT_ST00_HOME',
      toNode: 'INST_ST10_TRANS',
      toPort: 'IN_GUARD',
      requiredSourceState: 'AtHome',
      diagCodeHex: '16#0105',
      humanDescription: 'ST00 上料推杆在原位 (%I0.1)',
      isHealthy: false,
      crossStationRef: {
        upstreamStationId: 'ST00',
        upstreamInstanceId: 'INST_ST00_FEED',
        physicalTerminal: '%I0.1',
        cabinetWireTag: 'X10:01',
      },
    });

    const trace = traceMinimalFalsifyingCutSet(
      ws.projectGraph,
      ws.stationGraphs,
      'ST20',
      30,
      { '%I10.0': true, '%I0.4': false, '%I0.1': false }
    );
    expect(trace.falsifiedEdgeIds).toEqual(['G_ST20_ST10_TO_X', 'G_ST10_FROM_ST00']);
    expect(trace.rootCauseStationId).toBe('ST00');
    expect(trace.rootCauseNodeId).toBe('INST_ST00_FEED');
    expect(trace.rootPhysicalTerminal).toBe('%I0.1');
    expect(trace.rootCabinetWireTag).toBe('X10:01');
  });
});

describe('Algorithm 4: pinnedSugiyama', () => {
  it('keeps all isPinned nodes at strictly 0px shift and places added nodes without overlap', () => {
    const ws = createDefaultAfStudioWorkspace();
    const st20 = ws.stationGraphs.ST20;
    const pinnedSnapshot = st20.spatialNodes.map((n) => ({
      id: n.id,
      x: n.position.x,
      y: n.position.y,
    }));

    const addedNodes: SpatialInstanceNode[] = [
      makeActuator('ADD_GRIP_2', '2号辅助夹爪', 'FB_AF_Gripper', {
        isPinned: false,
        position: { x: 285, y: 65 }, // Intentionally collides with INST_ST20_GRIP
      }),
      makeActuator('ADD_CYL_2', '侧推气缸', 'FB_AF_Actuator2Pos', {
        isPinned: false,
        position: { x: 590, y: 80 }, // Intentionally collides with INST_ST20_X
      }),
      makeActuator('ADD_CAM_2', '3D复检传感器', 'FB_AF_VisionSensor', {
        isPinned: false,
        position: { x: 590, y: 315 }, // Intentionally collides with INST_ST20_Z
      }),
      makeActuator('ADD_AXIS_2', '辅助搬运轴', 'FB_AF_AxisMotion', {
        isPinned: false,
        position: { x: 0, y: 0 },
      }),
    ];

    const extraSteps: TemporalStepHyperEdge[] = [
      {
        id: 'T_ADD_1',
        stepNo: 60,
        title: '新增步序',
        fromNode: 'INST_ST20_CAM',
        fromPort: 'OUT_OK',
        invocations: [
          {
            targetNodeId: 'ADD_GRIP_2',
            targetPortId: 'IN_EXEC',
            methodId: 'GripClose',
            actionLabel: '闭合',
            targetDiscreteState: 'Closed',
            sclStatement: '#DB_ADD_GRIP_2.CloseGrip();',
            waitPredicateScl: '"DB_ADD_GRIP_2".o_bClosed',
          },
        ],
      },
      {
        id: 'T_ADD_2',
        stepNo: 70,
        title: '新增步序2',
        fromNode: 'ADD_GRIP_2',
        fromPort: 'OUT_DONE',
        invocations: [
          {
            targetNodeId: 'ADD_CYL_2',
            targetPortId: 'IN_EXEC',
            methodId: 'ExtendWork',
            actionLabel: '伸出',
            targetDiscreteState: 'AtWork',
            sclStatement: '#DB_ADD_CYL_2.ExtendWork();',
            waitPredicateScl: '"DB_ADD_CYL_2".o_bAtWork',
          },
        ],
      },
    ];

    const extraGuards: SafetyGuardEdge[] = [
      makeGuard('G_ADD_1', 'ADD_CYL_2', 'ADD_AXIS_2'),
    ];

    const nodeWidth = 252;
    const nodeHeight = 170;
    const layout = layoutWithPinnedAnchors(
      st20.spatialNodes,
      addedNodes,
      [...st20.guardEdges, ...extraGuards],
      [...st20.temporalSteps, ...extraSteps],
      { canvasWidth: 1200, canvasHeight: 760, nodeWidth, nodeHeight }
    );

    expect(layout.nodes).toHaveLength(st20.spatialNodes.length + addedNodes.length);
    expect(layout.placedAddedNodes).toHaveLength(addedNodes.length);

    // 1. Absolute invariant: all isPinned === true nodes have exact 0px shift
    for (const snap of pinnedSnapshot) {
      const outNode = layout.nodes.find((n) => n.id === snap.id)!;
      expect(outNode.position.x).toBe(snap.x);
      expect(outNode.position.y).toBe(snap.y);
    }

    // 2. Added unpinned nodes do not overlap with any pinned node or each other
    for (let i = 0; i < layout.placedAddedNodes.length; i++) {
      const a = layout.placedAddedNodes[i];
      for (const existing of st20.spatialNodes) {
        expect(boxesOverlap(a.position, existing.position, nodeWidth, nodeHeight)).toBe(
          false
        );
      }
      for (let j = i + 1; j < layout.placedAddedNodes.length; j++) {
        const b = layout.placedAddedNodes[j];
        expect(boxesOverlap(a.position, b.position, nodeWidth, nodeHeight)).toBe(false);
      }
    }
  });

  it('overflows gracefully into non-overlapping slots when adding many nodes on a compact canvas', () => {
    const ws = createDefaultAfStudioWorkspace();
    const st20 = ws.stationGraphs.ST20;
    const manyNodes = Array.from({ length: 12 }, (_, idx) =>
      makeActuator(`MANY_${idx}`, `执行器_${idx}`, 'FB_AF_Actuator2Pos', {
        isPinned: false,
        position: { x: 100, y: 100 },
      })
    );

    const nodeWidth = 252;
    const nodeHeight = 170;
    const layout = layoutWithPinnedAnchors(
      st20.spatialNodes,
      manyNodes,
      st20.guardEdges,
      st20.temporalSteps,
      { canvasWidth: 800, canvasHeight: 500, nodeWidth, nodeHeight }
    );

    expect(layout.placedAddedNodes).toHaveLength(12);
    for (let i = 0; i < layout.placedAddedNodes.length; i++) {
      const a = layout.placedAddedNodes[i];
      for (const existing of st20.spatialNodes) {
        expect(boxesOverlap(a.position, existing.position, nodeWidth, nodeHeight)).toBe(
          false
        );
      }
      for (let j = i + 1; j < layout.placedAddedNodes.length; j++) {
        const b = layout.placedAddedNodes[j];
        expect(boxesOverlap(a.position, b.position, nodeWidth, nodeHeight)).toBe(false);
      }
    }
  });
});
