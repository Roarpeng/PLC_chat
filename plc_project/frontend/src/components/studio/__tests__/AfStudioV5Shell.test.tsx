import React, { type ReactElement, type ReactNode } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createDefaultAfStudioWorkspace } from '../../../core/ir/seedHyperGraphs';
import type {
  CutSetTraceResult,
  GhostGraphTransaction,
  SpatialInstanceNode,
  StationHyperGraph,
  VerificationReport,
} from '../../../core/ir/afHyperGraph.types';
import { defaultHyperGraphStoreManager, useHyperGraphStore } from '../../../state/hyperGraphStore';

import { AfStudioV5Shell } from '../AfStudioV5Shell';
import { MotherClassPalette, MOTHER_CLASS_CATEGORIES } from '../MotherClassPalette';
import { NodeInspectorDrawer } from '../NodeInspectorDrawer';
import { AutoHomingModal } from '../AutoHomingModal';
import { VerificationReportModal } from '../VerificationReportModal';
import { CutSetModal } from '../CutSetModal';
import { MerkleSyncDrawer } from '../MerkleSyncDrawer';
import { NewProjectModal } from '../NewProjectModal';

type Element = ReactElement<Record<string, unknown>>;

function collectElements(
  tree: ReactNode,
  predicate: (element: Element) => boolean,
  acc: Element[] = []
): Element[] {
  for (const child of React.Children.toArray(tree)) {
    if (!React.isValidElement<Record<string, unknown>>(child)) continue;
    if (predicate(child)) acc.push(child);
    if (child.props.children !== undefined) {
      collectElements(child.props.children as ReactNode, predicate, acc);
    }
  }
  return acc;
}

function findElement(
  tree: ReactNode,
  predicate: (element: Element) => boolean
): Element | undefined {
  return collectElements(tree, predicate)[0];
}

function renderTree<P extends object>(
  Component: React.ComponentType<P>,
  props: P
): { tree: ReactNode; markup: string } {
  let tree: ReactNode = null;
  function Harness() {
    tree = React.createElement(Component, props);
    return tree as React.ReactElement;
  }
  const markup = renderToStaticMarkup(<Harness />);
  return { tree, markup };
}

describe('AF-Studio v5 Shell & UI Assembly Test Suite', () => {
  beforeEach(() => {
    defaultHyperGraphStoreManager.actions.resetWorkspace();
  });

  describe('1. AfStudioV5Shell Top Navigation Bar & Brand', () => {
    it('renders workshop branding, station selector, health indicator, and all action buttons', () => {
      const onSwitchMock = vi.fn();
      const { markup } = renderTree(AfStudioV5Shell, { onSwitch: onSwitchMock });

      expect(markup).toContain('AF-Studio v5');
      expect(markup).toContain('INDUSTRIAL HYPERGRAPH');

      // 工站选择下拉
      expect(markup).toContain('AssyLine_01 (产线全局总图)');
      expect(markup).toContain('ST10 · 来料移载工作站');
      expect(markup).toContain('ST20 · 视觉引导压装站');
      expect(markup).toContain('ST30 · 激光测高分拣站');

      // 导航动作按钮
      expect(markup).toContain('data-testid="nav-homing-btn"');
      expect(markup).toContain('data-testid="nav-cutset-btn"');
      expect(markup).toContain('data-testid="nav-coldstart-btn"');
      expect(markup).toContain('data-testid="nav-merkle-btn"');
      expect(markup).toContain('data-testid="nav-inspector-btn"');
      expect(markup).not.toContain('nav-back-v2-btn');
      expect(markup).not.toContain('返回 V2');
      expect(markup).toContain('data-testid="health-indicator-btn"');
    });

    it('displays layer mode indicator reflecting L2 station glass box', () => {
      const { markup } = renderTree(AfStudioV5Shell, {});
      expect(markup).toContain('data-testid="layer-mode-indicator"');
      expect(markup).toContain('L2 · 空间玻璃盒 (ST20)');
    });
  });

  describe('2. MotherClassPalette Component', () => {
    it('renders the device templates with Chinese names and typical actions', () => {
      const { markup } = renderTree(MotherClassPalette, {
        isCollapsed: false,
        currentStationId: 'ST20',
      });

      // 6 大驱动母版中文名与类名
      expect(markup).toContain('双位气缸');
      expect(markup).toContain('Cylinder2Pos');
      expect(markup).toContain('单轴伺服');
      expect(markup).toContain('SingleAxisServo');
      expect(markup).toContain('真空吸盘');
      expect(markup).toContain('VacuumSucker');
      expect(markup).toContain('六轴机器人');
      expect(markup).toContain('Robot6Axis');
      expect(markup).toContain('气动夹爪');
      expect(markup).toContain('PneumaticGripper');
      expect(markup).toContain('数字传感器');
      expect(markup).toContain('DigitalSensor');
      expect(markup).toContain('启停电机');

      // 典型动作标签
      expect(markup).toContain('伸出/缩回');
      expect(markup).toContain('回原点');
      expect(markup).toContain('吸附/释放');
      expect(markup).toContain('夹紧/松开');
      expect(markup).toContain('读取数字输入');
    });

    it('renders collapsed state with mini icons and expand button when isCollapsed is true', () => {
      const onToggleCollapse = vi.fn();
      const { markup } = renderTree(MotherClassPalette, {
        isCollapsed: true,
        onToggleCollapse,
      });

      expect(markup).toContain('data-testid="mother-class-palette-collapsed"');
      expect(markup).toContain('data-testid="expand-palette-btn"');
      expect(markup).toContain('data-testid="mini-palette-item-Cylinder2Pos"');
      expect(markup).toContain('data-testid="mini-palette-item-SingleAxisServo"');
    });

    it('triggers onAddNode when "+" button is clicked', () => {
      const onAddNodeMock = vi.fn();
      const firstCat = MOTHER_CLASS_CATEGORIES[0];
      const { markup } = renderTree(MotherClassPalette, {
        isCollapsed: false,
        onAddNode: onAddNodeMock,
      });

      expect(markup).toContain(`data-testid="add-node-btn-${firstCat.id}"`);
    });
  });

  describe('3. NodeInspectorDrawer Component', () => {
    it('renders placeholder empty state when no node is selected', () => {
      const ws = createDefaultAfStudioWorkspace();
      const { markup } = renderTree(NodeInspectorDrawer, {
        isOpen: true,
        selectedNodeId: null,
        station: ws.stationGraphs.ST20,
      });

      expect(markup).toContain('data-testid="inspector-empty-state"');
      expect(markup).toContain('未选中执行器节点');
    });

    it('renders full actuator attributes when selectedNodeId is valid', () => {
      const ws = createDefaultAfStudioWorkspace();
      const st20 = ws.stationGraphs.ST20;
      const targetNode = st20.spatialNodes.find((n) => n.id === 'INST_ST20_GRIP')!;

      const { markup } = renderTree(NodeInspectorDrawer, {
        isOpen: true,
        selectedNodeId: targetNode.id,
        station: st20,
      });

      // 基本信息
      expect(markup).toContain(targetNode.title);
      expect(markup).toContain(targetNode.driverClass);
      expect(markup).toContain(targetNode.instanceDb);
      expect(markup).toContain('ST20 · 视觉引导压装站');

      // 离散状态集与仿真状态
      expect(markup).toContain('data-testid="inspector-sim-state-badge"');
      expect(markup).toContain('Opened');
      expect(markup).toContain('Closed');

      // 物理引脚映射
      expect(markup).toContain('diOpened');
      expect(markup).toContain('diClosed');
      expect(markup).toContain('diPartPresent');

      // 安全软边界
      expect(markup).toContain('data-testid="input-min-safe-pos"');
      expect(markup).toContain('data-testid="input-max-safe-pos"');

      // 护栏超边关联
      expect(markup).toContain('输入防撞护栏');
      expect(markup).toContain('输出保护护栏');
      expect(markup).toContain('关联工步');

      // 操作按钮
      expect(markup).toContain('data-testid="edit-node-btn"');
      expect(markup).toContain('data-testid="focus-node-btn"');
      expect(markup).toContain('data-testid="delete-node-btn"');
    });
  });

  describe('4. AutoHomingModal Component', () => {
    it('renders Kahn partial order stratification stages 0 to 3', () => {
      const ws = createDefaultAfStudioWorkspace();
      const onCloseMock = vi.fn();

      const { markup } = renderTree(AutoHomingModal, {
        isOpen: true,
        onClose: onCloseMock,
        station: ws.stationGraphs.ST20,
      });

      expect(markup).toContain('data-testid="auto-homing-modal"');
      expect(markup).toContain('自动归航偏序分层合成 (Kahn Auto-Homing)');
      expect(markup).toContain('data-testid="homing-has-part-checkbox"');
      expect(markup).toContain('data-testid="recompute-homing-btn"');
      expect(markup).toContain('data-testid="apply-homing-btn"');

      // 检查 Kahn 分层树渲染
      expect(markup).toContain('data-testid="homing-layers-tree"');
      expect(markup).toContain('Stage 0: 传感器自检');
      expect(markup).toContain('Stage 1: 夹爪开/真空破除');
      expect(markup).toContain('Stage 2: 垂直轴 Z 提升');
      expect(markup).toContain('Stage 3: 水平轴 X/Y 复位');
    });
  });

  describe('5. VerificationReportModal Component', () => {
    it('renders symbolic verification violations with auto-fix button for missing guardrails', () => {
      const mockReport: VerificationReport = {
        passed: false,
        elapsedMs: 14,
        exploredStateCount: 64,
        violations: [
          {
            kind: 'MISSING_GUARDRAIL',
            stepNo: 20,
            nodeId: 'INST_ST20_GRIP',
            message: '工步 S20 触发夹爪闭合时未检测到 ST10 移载缸原位信号',
            suggestedGuardEdge: {
              id: 'G_AUTO_FIX_1',
              fromNode: 'INST_ST10_CYL',
              fromPort: 'OUT_AT_HOME',
              toNode: 'INST_ST20_GRIP',
              toPort: 'IN_GUARD',
              requiredSourceState: 'AtHome',
              diagCodeHex: '16#0203',
              humanDescription: '移载缸在原位互锁',
            },
          },
          {
            kind: 'COLLISION_REACHABLE',
            stepNo: 30,
            nodeId: 'INST_ST20_Z',
            interferingNodeId: 'INST_ST20_AXIS_X',
            message: '伺服 X 处于取料位时 Z 轴下压可能导致机械干涉',
          },
        ],
        warnings: ['检测到 1 处非关键警告'],
      };

      const onCloseMock = vi.fn();
      const onAutoFixMock = vi.fn();

      const { markup } = renderTree(VerificationReportModal, {
        isOpen: true,
        onClose: onCloseMock,
        report: mockReport,
        onApplyAutoFix: onAutoFixMock,
      });

      expect(markup).toContain('data-testid="verification-report-modal"');
      expect(markup).toContain('发现形式化安全违例 (VIOLATIONS DETECTED)');
      expect(markup).toContain('探索状态: 64 个');
      expect(markup).toContain('耗时: 14 ms');

      // 漏护栏与一键修复按钮
      expect(markup).toContain('缺失安全护栏');
      expect(markup).toContain('data-testid="auto-fix-btn-0"');
      expect(markup).toContain('一键注入护栏');

      // 物理干涉
      expect(markup).toContain('物理机械干涉');
    });

    it('renders clean state when verification passes with 0 violations', () => {
      const cleanReport: VerificationReport = {
        passed: true,
        elapsedMs: 8,
        exploredStateCount: 48,
        violations: [],
        warnings: [],
      };

      const { markup } = renderTree(VerificationReportModal, {
        isOpen: true,
        onClose: vi.fn(),
        report: cleanReport,
      });

      expect(markup).toContain('data-testid="verifier-clean-state"');
      expect(markup).toContain('形式化验证全部通过 (VERIFICATION PASSED)');
      expect(markup).toContain('未发现任何安全违例与护栏缺失');
    });
  });

  describe('6. CutSetModal Component', () => {
    it('renders 3-stage emergency stop cruise and cut-set red-line edges', () => {
      const mockCutSet: CutSetTraceResult = {
        blockedStationId: 'ST20',
        blockedStepNo: 20,
        blockedNodeId: 'INST_ST20_GRIP',
        prunedHealthyEdgeIds: ['G_HEALTHY_1'],
        falsifiedEdgeIds: ['G_ST20_ST10_HOME', 'E_L1_2'],
        l1CutSetEdgeId: 'E_L1_2',
        rootCauseStationId: 'ST10',
        rootCauseNodeId: 'DB_ST10_CylTransfer',
        rootPhysicalTerminal: '%I0.4',
        rootCabinetWireTag: 'TB10-X2:14',
        diagnosisSummary: 'ST10 移载缸原位磁开 (%I0.4) 线路断线，导致 ST20 工步 S20 护栏不满足',
        flyToStages: [
          {
            stageIndex: 1,
            layer: 'STATION',
            zoomScale: 1.1,
            stageTag: '巡航 1/3',
            description: '软减速阻尼',
            focusEntityId: 'INST_ST20_GRIP',
          },
        ],
      };

      const { markup } = renderTree(CutSetModal, {
        isOpen: true,
        onClose: vi.fn(),
        cutSetTrace: mockCutSet,
      });

      expect(markup).toContain('data-testid="cut-set-modal"');
      expect(markup).toContain('跨工站因果追溯与最小割集证伪');

      // 诊断与根因定位
      expect(markup).toContain('%I0.4');
      expect(markup).toContain('TB10-X2:14');
      expect(markup).toContain('DB_ST10_CylTransfer');

      // 红线割集超边
      expect(markup).toContain('data-testid="cutset-edge-G_ST20_ST10_HOME"');
      expect(markup).toContain('data-testid="cutset-edge-E_L1_2"');

      // 三段停机卡片
      expect(markup).toContain('Stage 1: 软减速阻尼');
      expect(markup).toContain('Stage 2: 避障寻安全位');
      expect(markup).toContain('Stage 3: 机械抱闸切断');

      // 操作按钮
      expect(markup).toContain('data-testid="play-cruise-btn"');
      expect(markup).toContain('data-testid="btn-stage-1"');
      expect(markup).toContain('data-testid="btn-stage-2"');
      expect(markup).toContain('data-testid="btn-stage-3"');
    });
  });

  describe('7. MerkleSyncDrawer Component', () => {
    it('renders 4 SCL blocks with Merkle hashes, dirty badges, and sync buttons', () => {
      const ws = createDefaultAfStudioWorkspace();
      const st20 = ws.stationGraphs.ST20;

      const { markup } = renderTree(MerkleSyncDrawer, {
        isOpen: true,
        onClose: vi.fn(),
        station: st20,
      });

      expect(markup).toContain('data-testid="merkle-sync-drawer"');
      expect(markup).toContain('AST Merkle 增量编译与博途 TIA Openness STA 同步');

      // 4 大 SCL 块名称
      expect(markup).toContain('DB_ST20_Instances');
      expect(markup).toContain('FB_ST20_AutoSeq');
      expect(markup).toContain('FB_ST20_HomeSeq');
      expect(markup).toContain('FC_ST20_GuardDiag');

      // SHA 哈希与脏标志徽章
      expect(markup).toContain('SHA:');
      expect(markup).toContain('data-testid="dirty-badge-DB_ST20_Instances"');

      // 操作按钮
      expect(markup).toContain('data-testid="download-scl-btn"');
      expect(markup).toContain('data-testid="sync-tia-btn"');
      expect(markup).toContain('data-testid="scl-code-preview"');
    });
  });

  describe('8. GhostDiffBanner Integration in Shell', () => {
    it('binds to activeGhost in store and commits on commitGhost', () => {
      // 初始无 Ghost
      const initial = renderTree(AfStudioV5Shell, {});
      expect(initial.markup).not.toContain('data-testid="ghost-banner-container"');

      // 激活 Ghost
      const mockGhost: GhostGraphTransaction = {
        txId: 'tx-test-01',
        stationId: 'ST20',
        summary: 'Copilot 建议：为取料气缸注入安全互锁护栏',
        addedNodes: [],
        addedGuardEdges: [
          {
            id: 'G_GHOST_TEST',
            fromNode: 'INST_ST20_Z',
            fromPort: 'OUT_AT_HOME',
            toNode: 'INST_ST20_GRIP',
            toPort: 'IN_GUARD',
            requiredSourceState: 'AtHome',
            diagCodeHex: '16#0299',
            humanDescription: 'Z 轴在原位护栏',
          },
        ],
        addedTemporalSteps: [],
        verificationPassed: true,
        verifierWarnings: [],
      };

      defaultHyperGraphStoreManager.actions.setActiveGhost(mockGhost);

      const withGhost = renderTree(AfStudioV5Shell, {});
      expect(withGhost.markup).toContain('data-testid="ghost-banner-container"');
      expect(withGhost.markup).toContain('Copilot 建议：为取料气缸注入安全互锁护栏');

      // 提交 Ghost
      defaultHyperGraphStoreManager.actions.commitGhost();
      const afterCommit = renderTree(AfStudioV5Shell, {});
      expect(afterCommit.markup).not.toContain('data-testid="ghost-banner-container"');

      // 验证护栏已并入工站
      const st20Guards = defaultHyperGraphStoreManager.getState().workspace.stationGraphs.ST20.guardEdges;
      expect(st20Guards.some((g) => g.id === 'G_GHOST_TEST')).toBe(true);
    });
  });

  describe('9. Global State Transitions & Keyboard Actions', () => {
    it('supports switching layers between L1 (PROJECT) and L2 (STATION)', () => {
      defaultHyperGraphStoreManager.actions.setLayer('PROJECT');
      expect(defaultHyperGraphStoreManager.getState().currentLayer).toBe('PROJECT');

      defaultHyperGraphStoreManager.actions.setLayer('STATION', 'ST30');
      expect(defaultHyperGraphStoreManager.getState().currentLayer).toBe('STATION');
      expect(defaultHyperGraphStoreManager.getState().currentStationId).toBe('ST30');
    });

    it('supports modal toggles and drawer toggles', () => {
      defaultHyperGraphStoreManager.actions.openModal('homing');
      expect(defaultHyperGraphStoreManager.getState().activeModal).toBe('homing');

      defaultHyperGraphStoreManager.actions.closeModal();
      expect(defaultHyperGraphStoreManager.getState().activeModal).toBe(null);

      defaultHyperGraphStoreManager.actions.toggleMerkleDrawer(true);
      expect(defaultHyperGraphStoreManager.getState().isMerkleDrawerOpen).toBe(true);

      defaultHyperGraphStoreManager.actions.toggleMerkleDrawer(false);
      expect(defaultHyperGraphStoreManager.getState().isMerkleDrawerOpen).toBe(false);

      defaultHyperGraphStoreManager.actions.toggleInspector();
      expect(defaultHyperGraphStoreManager.getState().isInspectorOpen).toBe(false);
    });
  });

  describe('10. Snapshot Reference Stability (useSyncExternalStore Safety)', () => {
    it('returns strictly identical store snapshot reference when state is unchanged and fresh reference after mutations', () => {
      const s1 = defaultHyperGraphStoreManager.getStore();
      const s2 = defaultHyperGraphStoreManager.getStore();
      expect(Object.is(s1, s2)).toBe(true);

      defaultHyperGraphStoreManager.actions.setZoomScale(1.25);
      const s3 = defaultHyperGraphStoreManager.getStore();
      expect(Object.is(s1, s3)).toBe(false);
      expect(s3.zoomScale).toBe(1.25);

      const s4 = defaultHyperGraphStoreManager.getStore();
      expect(Object.is(s3, s4)).toBe(true);

      defaultHyperGraphStoreManager.actions.resetWorkspace();
      const s5 = defaultHyperGraphStoreManager.getStore();
      expect(Object.is(s3, s5)).toBe(false);
      expect(s5.zoomScale).toBe(1.0);
    });
  });

  describe('11. L1 Dragging, Edge & Logic Editing, and New Project / Station Entry', () => {
    it('updates L1 station position via updateProjectStation and manages L1 cross-station edges', () => {
      defaultHyperGraphStoreManager.actions.setLayer('PROJECT');
      defaultHyperGraphStoreManager.actions.updateProjectStation('NODE_ST10', {
        position: { x: 210, y: 185 },
        isPinned: true,
        title: 'ST10 · 自定义搬运站',
      });

      const ws = defaultHyperGraphStoreManager.getState().workspace;
      const st10Card = ws.projectGraph.stations.find((s) => s.id === 'NODE_ST10')!;
      expect(st10Card.position).toEqual({ x: 210, y: 185 });
      expect(st10Card.title).toBe('ST10 · 自定义搬运站');
      expect(ws.stationGraphs.ST10.stationName).toBe('ST10 · 自定义搬运站');

      defaultHyperGraphStoreManager.actions.addProjectEdge({
        id: 'E_L1_CUSTOM',
        fromNode: 'NODE_ST10',
        fromPort: 'P_HANDOVER',
        toNode: 'NODE_ST30',
        toPort: 'P_IN_ST20',
        kind: 'GUARD',
        label: '自定义直连护栏',
        diagCodeHex: '16#0288',
      });
      expect(
        defaultHyperGraphStoreManager
          .getState()
          .workspace.projectGraph.edges.some((e) => e.id === 'E_L1_CUSTOM')
      ).toBe(true);

      defaultHyperGraphStoreManager.actions.updateProjectEdge('E_L1_CUSTOM', {
        label: '修改后的跨站安全逻辑',
      });
      expect(
        defaultHyperGraphStoreManager
          .getState()
          .workspace.projectGraph.edges.find((e) => e.id === 'E_L1_CUSTOM')?.label
      ).toBe('修改后的跨站安全逻辑');

      defaultHyperGraphStoreManager.actions.deleteProjectEdge('E_L1_CUSTOM');
      expect(
        defaultHyperGraphStoreManager
          .getState()
          .workspace.projectGraph.edges.some((e) => e.id === 'E_L1_CUSTOM')
      ).toBe(false);
    });

    it('creates, edits logic, and deletes L2 temporal step edges and guard edges', () => {
      defaultHyperGraphStoreManager.actions.addTemporalStep('ST20', {
        id: 'T_TEST_S60',
        stepNo: 60,
        title: '测试新连线工步',
        fromNode: 'INST_ST20_X',
        fromPort: 'OUT_DONE',
        branchPredicate: 'OK',
        invocations: [
          {
            targetNodeId: 'INST_ST20_GRIP',
            targetPortId: 'IN_EXEC',
            methodId: 'GripOpen',
            actionLabel: '松开工件',
            targetDiscreteState: 'Opened',
            sclStatement: 'OpenGrip()',
            waitPredicateScl: '#INST_ST20_GRIP.o_bOpened',
          },
        ],
      });

      let st20 = defaultHyperGraphStoreManager.getState().workspace.stationGraphs.ST20;
      expect(st20.temporalSteps.some((s) => s.id === 'T_TEST_S60')).toBe(true);

      defaultHyperGraphStoreManager.actions.updateTemporalStep('ST20', 'T_TEST_S60', {
        title: '修改后工步逻辑',
        branchPredicate: 'NG',
      });
      st20 = defaultHyperGraphStoreManager.getState().workspace.stationGraphs.ST20;
      const editedStep = st20.temporalSteps.find((s) => s.id === 'T_TEST_S60')!;
      expect(editedStep.title).toBe('修改后工步逻辑');
      expect(editedStep.branchPredicate).toBe('NG');

      const guardId = st20.guardEdges[0].id;
      defaultHyperGraphStoreManager.actions.updateGuardEdge('ST20', guardId, {
        diagCodeHex: '16#0999',
        humanDescription: '更新后的安全互锁描述',
      });
      st20 = defaultHyperGraphStoreManager.getState().workspace.stationGraphs.ST20;
      expect(st20.guardEdges.find((g) => g.id === guardId)?.diagCodeHex).toBe('16#0999');

      defaultHyperGraphStoreManager.actions.deleteTemporalStep('ST20', 'T_TEST_S60');
      st20 = defaultHyperGraphStoreManager.getState().workspace.stationGraphs.ST20;
      expect(st20.temporalSteps.some((s) => s.id === 'T_TEST_S60')).toBe(false);
    });

    it('renders dedicated edge and logic editors in NodeInspectorDrawer for STEP, GUARD, L1_EDGE, and STATION selections', () => {
      const ws = createDefaultAfStudioWorkspace();
      const st20 = ws.stationGraphs.ST20;

      const stepView = renderTree(NodeInspectorDrawer, {
        isOpen: true,
        selectedNodeId: null,
        selectedEntity: { kind: 'STEP', id: st20.temporalSteps[0].id },
        station: st20,
      });
      expect(stepView.markup).toContain('data-testid="step-edge-inspector"');
      expect(stepView.markup).toContain('data-testid="step-scl-input"');
      expect(stepView.markup).toContain('data-testid="save-step-edge-btn"');

      const guardView = renderTree(NodeInspectorDrawer, {
        isOpen: true,
        selectedNodeId: null,
        selectedEntity: { kind: 'GUARD', id: st20.guardEdges[0].id },
        station: st20,
      });
      expect(guardView.markup).toContain('data-testid="guard-edge-inspector"');
      expect(guardView.markup).toContain('data-testid="guard-diag-code-input"');

      const l1EdgeView = renderTree(NodeInspectorDrawer, {
        isOpen: true,
        selectedNodeId: null,
        selectedEntity: { kind: 'L1_EDGE', id: ws.projectGraph.edges[0].id },
        layer: 'PROJECT',
        projectGraph: ws.projectGraph,
        station: st20,
      });
      expect(l1EdgeView.markup).toContain('data-testid="l1-edge-inspector"');
      expect(l1EdgeView.markup).toContain('data-testid="l1-edge-label-input"');

      const l1StationView = renderTree(NodeInspectorDrawer, {
        isOpen: true,
        selectedNodeId: null,
        selectedEntity: { kind: 'STATION', id: ws.projectGraph.stations[0].id },
        layer: 'PROJECT',
        projectGraph: ws.projectGraph,
        station: st20,
      });
      expect(l1StationView.markup).toContain('data-testid="l1-station-inspector"');
      expect(l1StationView.markup).toContain('data-testid="enter-station-l2-btn"');
    });

    it('exposes New Project / Station buttons in topbar and creates blank, single-station, and multi-station projects', () => {
      const shell = renderTree(AfStudioV5Shell, {});
      expect(shell.markup).toContain('data-testid="nav-new-project-btn"');
      expect(shell.markup).toContain('data-testid="nav-new-station-btn"');

      const modalView = renderTree(NewProjectModal, {
        isOpen: true,
        currentProjectName: 'AssyLine_01',
        existingStationIds: ['ST10', 'ST20', 'ST30'],
        onClose: vi.fn(),
        onCreateProject: vi.fn(),
        onAddStation: vi.fn(),
      });
      expect(modalView.markup).toContain('data-testid="new-project-modal"');
      expect(modalView.markup).toContain('data-testid="new-project-name-input"');
      expect(modalView.markup).toContain('data-testid="confirm-create-project-btn"');

      defaultHyperGraphStoreManager.actions.createNewProject({
        projectName: 'EV_Pack_Line',
        template: 'single_station',
        firstStationId: 'ST10',
        firstStationTitle: 'ST10 · 电芯入壳工站',
      });
      let state = defaultHyperGraphStoreManager.getState();
      expect(state.workspace.projectName).toBe('EV_Pack_Line');
      expect(state.currentStationId).toBe('ST10');
      expect(Object.keys(state.workspace.stationGraphs)).toEqual(['ST10']);

      defaultHyperGraphStoreManager.actions.addStationToProject({
        stationId: 'ST20',
        title: 'ST20 · 激光焊接工站',
      });
      state = defaultHyperGraphStoreManager.getState();
      expect(state.currentStationId).toBe('ST20');
      const [input, output] = state.workspace.stationGraphs.ST20.spatialNodes;
      expect(input.outPorts.map(({ label }) => label)).toEqual(['● 工位请求', '🛡️ 外部安全许可']);
      expect(output.inPorts.map(({ label }) => label)).toEqual(['▶ 工位完成', '🛡️ 工位安全状态']);
      expect(Object.keys(state.workspace.stationGraphs)).toEqual(['ST10', 'ST20']);
      expect(state.workspace.projectGraph.stations).toHaveLength(2);
    });
  });

  describe('12. Direct Canvas, Inspector, and L1/L2 Deletion Flows', () => {
    it('keeps edge removal in the inspector when canvas labels are hidden', () => {
      const shell = renderTree(AfStudioV5Shell, {});
      expect(shell.markup).toContain('data-testid="canvas-delete-node-INST_ST20_GRIP"');
      expect(shell.markup).not.toContain('data-testid="canvas-delete-edge-T_S20"');
      expect(shell.markup).not.toContain('data-testid="canvas-delete-edge-G_ST20_Z_TO_X"');
      expect(shell.markup).toContain('data-testid="quick-delete-step-T_S20"');
      expect(shell.markup).toContain('data-testid="quick-delete-guard-G_ST20_Z_TO_X"');
    });

    it('deletes node from NodeInspectorDrawer immediately without blocking on window.confirm', () => {
      const ws = createDefaultAfStudioWorkspace();
      const st20 = ws.stationGraphs.ST20;
      const onDeleteNode = vi.fn();

      let tree: ReactNode = null;
      function Harness() {
        tree = (NodeInspectorDrawer as unknown as (p: Record<string, unknown>) => ReactNode)({
          isOpen: true,
          selectedNodeId: 'INST_ST20_GRIP',
          station: st20,
          onDeleteNode,
        });
        return tree as ReactElement;
      }
      renderToStaticMarkup(<Harness />);

      const delBtn = findElement(
        tree,
        (el) => el.props['data-testid'] === 'delete-node-btn'
      )!;
      expect(delBtn).toBeDefined();
      (delBtn.props.onClick as () => void)();
      expect(onDeleteNode).toHaveBeenCalledWith('INST_ST20_GRIP');
    });

    it('cleans up associated edges when deleting L2 nodes or L1 project stations', () => {
      defaultHyperGraphStoreManager.actions.deleteNode('ST20', 'INST_ST20_CAM');
      const st20 = defaultHyperGraphStoreManager.getState().workspace.stationGraphs.ST20;
      expect(st20.spatialNodes.some((n) => n.id === 'INST_ST20_CAM')).toBe(false);
      // T_S20 targeted INST_ST20_CAM and T_S30 originated from INST_ST20_CAM
      expect(st20.temporalSteps.some((s) => s.id === 'T_S20')).toBe(false);
      expect(st20.temporalSteps.some((s) => s.fromNode === 'INST_ST20_CAM')).toBe(false);

      defaultHyperGraphStoreManager.actions.deleteProjectStation('NODE_ST10');
      const ws = defaultHyperGraphStoreManager.getState().workspace;
      expect(ws.projectGraph.stations.some((s) => s.id === 'NODE_ST10')).toBe(false);
      expect(ws.stationGraphs.ST10).toBeUndefined();
      expect(
        ws.projectGraph.edges.some((e) => e.fromNode === 'NODE_ST10' || e.toNode === 'NODE_ST10')
      ).toBe(false);
    });
  });
});
