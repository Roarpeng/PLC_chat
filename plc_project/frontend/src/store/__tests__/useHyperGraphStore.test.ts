import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { hyperGraphStore } from '../useHyperGraphStore';
import type { GhostGraphTransaction, SafetyGuardEdge } from '../../core/ir/afHyperGraph.types';

describe('useHyperGraphStore - Reactive State & Action Lifecycle', () => {
  beforeEach(() => {
    hyperGraphStore.resetToDefaultWorkspace();
    // 隔离网络，全部走离线确定性逻辑
    globalThis.fetch = vi.fn().mockRejectedValue(new Error('Network offline in store test'));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('1. initializes with default seed workspace and reactive subscription', () => {
    const state = hyperGraphStore.getState();
    expect(state.currentStationId).toBe('ST20');
    expect(state.currentLayer).toBe('STATION');
    expect(state.viewportTransform).toEqual({ x: 0, y: 0, scale: 1.0 });
    expect(state.selectedNodeId).toBeNull();
    expect(state.workspace.projectName).toBe('AssyLine_01');
    expect(Object.keys(state.workspace.stationGraphs)).toEqual(['ST10', 'ST20', 'ST30']);

    let callCount = 0;
    const unsub = hyperGraphStore.subscribe(() => {
      callCount += 1;
    });

    hyperGraphStore.setLayer('LINE');
    expect(hyperGraphStore.getState().currentLayer).toBe('LINE');
    expect(callCount).toBe(1);

    unsub();
    hyperGraphStore.setLayer('STATION');
    expect(hyperGraphStore.getState().currentLayer).toBe('STATION');
    expect(callCount).toBe(1); // 解除订阅后不再通知
  });

  it('2. adds and removes spatial nodes from mother classes', () => {
    const initialNodeCount = hyperGraphStore.getState().workspace.stationGraphs['ST20'].spatialNodes.length;

    // 添加气缸执行器
    const cylNode = hyperGraphStore.addNodeFromMotherClass('CYLINDER', '辅助顶升气缸');
    expect(cylNode).not.toBeNull();
    expect(cylNode?.driverClass).toBe('FB_AF_Actuator2Pos');
    expect(cylNode?.title).toBe('辅助顶升气缸');
    expect(cylNode?.id).toContain('INST_ST20_');
    expect(cylNode?.instanceDb).toContain('DB_ST20_');

    const stateAfterAdd = hyperGraphStore.getState();
    const st20AfterAdd = stateAfterAdd.workspace.stationGraphs['ST20'];
    expect(st20AfterAdd.spatialNodes.length).toBe(initialNodeCount + 1);
    expect(stateAfterAdd.selectedNodeId).toBe(cylNode?.id);
    expect(stateAfterAdd.inspectorOpen).toBe(true);

    // 删除刚添加的节点
    hyperGraphStore.removeNode(cylNode!.id);
    const stateAfterRemove = hyperGraphStore.getState();
    const st20AfterRemove = stateAfterRemove.workspace.stationGraphs['ST20'];
    expect(st20AfterRemove.spatialNodes.length).toBe(initialNodeCount);
    expect(stateAfterRemove.selectedNodeId).toBeNull();
  });

  it('3. opens radial menu and appends craft steps with polar timing hyperedge', () => {
    const state = hyperGraphStore.getState();
    const gripNode = state.workspace.stationGraphs['ST20'].spatialNodes.find(
      (n) => n.driverClass === 'FB_AF_Gripper'
    )!;

    // 打开径向菜单
    hyperGraphStore.openRadialMenu(gripNode.id, 320, 240);
    expect(hyperGraphStore.getState().radialMenuState).toEqual({
      nodeId: gripNode.id,
      x: 320,
      y: 240,
    });

    // 从径向菜单触发动作 "OpenGrip"
    const prevStepsCount = state.workspace.stationGraphs['ST20'].temporalSteps.length;
    hyperGraphStore.addCraftStepFromRadial(gripNode.id, 'OpenGrip', 'Opened');

    const nextState = hyperGraphStore.getState();
    expect(nextState.radialMenuState).toBeNull(); // 触发后自动关闭菜单
    const st20Steps = nextState.workspace.stationGraphs['ST20'].temporalSteps;
    expect(st20Steps.length).toBe(prevStepsCount + 1);

    const lastStep = st20Steps[st20Steps.length - 1];
    expect(lastStep.stepNo).toBe(60); // 默认前 5 步最大 50 -> 下一步 60
    expect(lastStep.invocations[0].targetNodeId).toBe(gripNode.id);
    expect(lastStep.invocations[0].methodId).toBe('OpenGrip');
    expect(lastStep.invocations[0].targetDiscreteState).toBe('Opened');
  });

  it('4. sets, discards, and applies GhostGraphTransaction diff patches', () => {
    const mockGhost: GhostGraphTransaction = {
      txId: 'TX_TEST_001',
      stationId: 'ST20',
      summary: '测试 AI 虚影补丁',
      addedNodes: [],
      addedGuardEdges: [
        {
          id: 'G_TEST_GHOST_EDGE',
          fromNode: 'INST_ST20_X',
          fromPort: 'OUT_DONE',
          toNode: 'INST_ST20_Z',
          toPort: 'IN_EXEC',
          requiredSourceState: 'Pos_Home_0',
          diagCodeHex: '16#0298',
          humanDescription: '测试虚影互锁边',
        },
      ],
      addedTemporalSteps: [
        {
          id: 'T_TEST_GHOST_STEP',
          stepNo: 55,
          title: '测试虚影工艺步',
          fromNode: 'INST_ST20_Z',
          fromPort: 'OUT_DONE',
          invocations: [
            {
              targetNodeId: 'INST_ST20_GRIP',
              methodId: 'OpenGrip',
              actionLabel: '松开夹爪',
              targetDiscreteState: 'Opened',
              sclStatement: '#DB_ST20_Grip.OpenGrip();',
              waitPredicateScl: '"DB_ST20_Grip".o_bDone',
            },
          ],
        },
      ],
      verificationPassed: true,
      verifierWarnings: [],
    };

    hyperGraphStore.setGhostTransaction(mockGhost);
    expect(hyperGraphStore.getState().activeGhost).toBe(mockGhost);

    // 丢弃测试
    hyperGraphStore.discardActiveGhost();
    expect(hyperGraphStore.getState().activeGhost).toBeNull();
    expect(
      hyperGraphStore
        .getState()
        .workspace.stationGraphs['ST20'].guardEdges.some((g) => g.id === 'G_TEST_GHOST_EDGE')
    ).toBe(false);

    // 重新设置并提交
    hyperGraphStore.setGhostTransaction(mockGhost);
    hyperGraphStore.applyActiveGhost();

    const stateAfterApply = hyperGraphStore.getState();
    expect(stateAfterApply.activeGhost).toBeNull();
    const st20Guards = stateAfterApply.workspace.stationGraphs['ST20'].guardEdges;
    expect(st20Guards.some((g) => g.id === 'G_TEST_GHOST_EDGE')).toBe(true);
    const st20Steps = stateAfterApply.workspace.stationGraphs['ST20'].temporalSteps;
    expect(st20Steps.some((s) => s.id === 'T_TEST_GHOST_STEP')).toBe(true);
  });

  it('5. runs verification and applies one-click auto-fix patch', async () => {
    // 先人为删掉 Z 到 X 的互锁护栏
    const s = hyperGraphStore.getState();
    s.workspace.stationGraphs['ST20'].guardEdges = s.workspace.stationGraphs[
      'ST20'
    ].guardEdges.filter((g) => g.id !== 'G_ST20_Z_TO_X');

    // 触发验证 -> 校验失败，报告中给出建议修复边
    const report = await hyperGraphStore.runVerification();
    expect(report).not.toBeNull();
    expect(report?.passed).toBe(false);
    expect(hyperGraphStore.getState().verificationReport?.passed).toBe(false);

    // 一键补齐防撞护栏
    hyperGraphStore.applyAutoFix();

    // 校验护栏已补齐且图重新验证通过
    const fixedGuards = hyperGraphStore.getState().workspace.stationGraphs['ST20'].guardEdges;
    expect(fixedGuards.some((g) => g.fromNode === 'INST_ST20_Z' && g.toNode === 'INST_ST20_X')).toBe(
      true
    );
  });

  it('6. runs cut-set trace and controls 3-stage fault cruise camera', async () => {
    const cutSet = await hyperGraphStore.runCutSetTrace('INST_ST20_X');
    expect(cutSet).not.toBeNull();
    expect(cutSet?.blockedStationId).toBe('ST20');
    expect(hyperGraphStore.getState().faultCruiseStep).toBe(1);

    // Stage 1: 受阻现场 (ST20, scale = 1.5)
    hyperGraphStore.stepFaultCruise(1);
    let st = hyperGraphStore.getState();
    expect(st.currentLayer).toBe('STATION');
    expect(st.currentStationId).toBe('ST20');
    expect(st.viewportTransform.scale).toBe(1.5);

    // Stage 2: L1 跨站逆向穿越 (LINE, scale = 0.8)
    hyperGraphStore.stepFaultCruise(2);
    st = hyperGraphStore.getState();
    expect(st.currentLayer).toBe('LINE');
    expect(st.viewportTransform.scale).toBe(0.8);

    // Stage 3: 上游物理端子锁定 (STATION, ST10, scale = 1.65, focusNode = INST_ST10_TRANS)
    hyperGraphStore.stepFaultCruise(3);
    st = hyperGraphStore.getState();
    expect(st.currentLayer).toBe('STATION');
    expect(st.currentStationId).toBe('ST10');
    expect(st.selectedNodeId).toBe('INST_ST10_TRANS');
    expect(st.viewportTransform.scale).toBe(1.65);
  });

  it('7. synthesizes homing and applies homing plan to station metadata', async () => {
    const plan = await hyperGraphStore.runHomingSynthesis();
    expect(plan).not.toBeNull();
    expect(plan?.hasCycleDeadlock).toBe(false);
    expect(plan?.concurrentLayers.length).toBe(2);
    expect(hyperGraphStore.getState().activeModal).toBe('homing');

    hyperGraphStore.applyHomingPlan();
    expect(hyperGraphStore.getState().activeModal).toBeNull();
    const st20 = hyperGraphStore.getState().workspace.stationGraphs['ST20'];
    expect((st20 as any).homingLayers).toBe(2);
  });

  it('8. compiles and synchronizes Merkle AST manifest', async () => {
    const manifest = await hyperGraphStore.compileAndSyncMerkle('TIA_V19_STA');
    expect(manifest).not.toBeNull();
    expect(manifest?.stationId).toBe('ST20');
    expect(manifest?.dirtyCount).toBe(4);
    expect(hyperGraphStore.getState().isCompiling).toBe(false);
    expect(hyperGraphStore.getState().isSyncingMerkle).toBe(false);
    expect(hyperGraphStore.getState().merkleManifest).toEqual(manifest);
  });

  it('9. toggles inspector, modals, and viewport transforms', () => {
    hyperGraphStore.toggleInspector(true);
    expect(hyperGraphStore.getState().inspectorOpen).toBe(true);
    hyperGraphStore.toggleInspector();
    expect(hyperGraphStore.getState().inspectorOpen).toBe(false);

    hyperGraphStore.openModal('merkle');
    expect(hyperGraphStore.getState().activeModal).toBe('merkle');
    hyperGraphStore.closeModal();
    expect(hyperGraphStore.getState().activeModal).toBeNull();

    hyperGraphStore.setViewportTransform({ x: 120, y: -45, scale: 2.2 });
    expect(hyperGraphStore.getState().viewportTransform).toEqual({
      x: 120,
      y: -45,
      scale: 2.2,
    });
  });
});
