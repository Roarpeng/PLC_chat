import React, { type ReactElement, type ReactNode } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import type {
  CutSetTraceResult,
  GhostGraphTransaction,
  VerificationReport,
} from '../../../core/ir/afHyperGraph.types';
import { getRadialMethodsForClass } from '../../../core/ir/motherClassRegistry';
import { createDefaultAfStudioWorkspace } from '../../../core/ir/seedHyperGraphs';
import { TimeRibbonScrubber } from '../../timeline/TimeRibbonScrubber';
import { HyperEdgeSvgLayer } from '../HyperEdgeSvgLayer';
import { routeOrthogonalEdges } from '../orthogonalRoutes';
import {
  RadialCraftMenu,
  computeRadialMenuItems,
} from '../RadialCraftMenu';
import {
  SemanticZoomStage,
  evaluateSemanticZoomTransition,
} from '../SemanticZoomStage';
import { SpatialNodeCard } from '../SpatialNodeCard';

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

function extractText(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(extractText).join('');
  if (React.isValidElement<Record<string, unknown>>(node)) {
    return extractText(node.props.children as ReactNode);
  }
  return '';
}

function renderComponentTree<P>(
  Component: (props: P) => any,
  props: P
): { tree: ReactNode; markup: string } {
  let tree: ReactNode = null;
  function Harness() {
    tree = (Component as any)(props);
    return tree as React.ReactElement;
  }
  const markup = renderToStaticMarkup(<Harness />);
  return { tree, markup };
}

describe('HyperEdgeSvgLayer & Time-Ribbon single-step focus', () => {
  it('keeps the compact overview unlabeled and renders only the focused step and its guards', () => {
    const station = createDefaultAfStudioWorkspace().stationGraphs.ST20;
    const base = { layer: 'STATION' as const, station, faultFlyActive: false, compactStationWires: true };
    const overview = renderComponentTree(HyperEdgeSvgLayer, { ...base, focusedStepNo: null });
    const overviewWires = collectElements(overview.tree, (el) => el.props['data-edge-kind'] === 'step');
    expect(overviewWires.length).toBeGreaterThan(1);
    expect(overview.markup).not.toContain('af5-edge-badge-text');
    const focused = renderComponentTree(HyperEdgeSvgLayer, { ...base, focusedStepNo: 30 });
    const wires = collectElements(focused.tree, (el) => el.props['data-edge-kind'] === 'step');
    expect(wires.map(({ props }) => props['data-step-no'])).toEqual([30]);
    const guards = collectElements(focused.tree, (el) => el.props['data-edge-kind'] === 'guard');
    expect(guards.map(({ props }) => props['data-edge-id'])).toContain('G_ST20_Z_TO_X');
    const labeled = renderComponentTree(HyperEdgeSvgLayer, {
      ...base, focusedStepNo: 30, showStationWireLabels: true,
      onDeleteStep: vi.fn(), onDeleteGuard: vi.fn(),
    });
    expect(collectElements(labeled.tree, (el) => el.props['data-edge-kind'] === 'step')).toHaveLength(1);
    expect(labeled.markup).toContain('af5-edge-badge-text');
    expect(labeled.markup).toContain('canvas-delete-edge-');
  });

  it('dims non-S30 edges to 0.12 and highlights S30 in 3.6px emerald when focusedStepNo = 30', () => {
    const ws = createDefaultAfStudioWorkspace();
    const st20 = ws.stationGraphs.ST20;
    // Add an extra guard edge targeting another node to verify non-active guardrail dims to 0.15
    st20.guardEdges.push({
      id: 'G_OTHER_GUARD',
      fromNode: 'INST_ST20_GRIP',
      fromPort: 'OUT_DONE',
      toNode: 'INST_ST20_Z',
      toPort: 'IN_EXEC',
      requiredSourceState: 'Opened',
      diagCodeHex: '16#0299',
      humanDescription: '其他非当前拍护栏',
      isHealthy: true,
    });

    const { tree } = renderComponentTree(HyperEdgeSvgLayer, {
      layer: 'STATION',
      station: st20,
      focusedStepNo: 30,
      faultFlyActive: false,
    });

    const stepGroups = collectElements(
      tree,
      (el) => el.type === 'g' && el.props['data-edge-kind'] === 'step'
    );
    expect(stepGroups.length).toBeGreaterThanOrEqual(5);

    const s30Group = stepGroups.find((g) => g.props['data-step-no'] === 30)!;
    expect(s30Group).toBeDefined();
    expect((s30Group.props.style as { opacity: number }).opacity).toBe(1);

    const s30Path = findElement(
      s30Group,
      (el) => el.type === 'path' && el.props.stroke !== 'transparent'
    )!;
    expect(s30Path.props.stroke).toBe('#059669');
    expect(s30Path.props.strokeWidth).toBe(3.6);
    expect(s30Path.props.className).toBe('af5-wire-active');

    const nonS30Groups = stepGroups.filter((g) => g.props['data-step-no'] !== 30);
    expect(nonS30Groups.length).toBeGreaterThan(0);
    for (const g of nonS30Groups) {
      expect((g.props.style as { opacity: number }).opacity).toBe(0.12);
    }

    // Guard edges protecting INST_ST20_X stay opacity 1, others dim to 0.15
    const guardGroups = collectElements(
      tree,
      (el) => el.type === 'g' && el.props['data-edge-kind'] === 'guard'
    );
    const activeGuard = guardGroups.find((g) => g.props['data-edge-id'] === 'G_ST20_Z_TO_X')!;
    const otherGuard = guardGroups.find((g) => g.props['data-edge-id'] === 'G_OTHER_GUARD')!;
    expect((activeGuard.props.style as { opacity: number }).opacity).toBe(1);
    expect((otherGuard.props.style as { opacity: number }).opacity).toBe(0.15);
  });

  it('shows the S30 action label when labels are enabled and dims unrelated nodes', () => {
    const ws = createDefaultAfStudioWorkspace();
    const st20 = ws.stationGraphs.ST20;

    const { tree, markup } = renderComponentTree(SemanticZoomStage, {
      layer: 'STATION',
      zoomScale: 1.5,
      projectGraph: ws.projectGraph,
      station: st20,
      focusedStepNo: 30,
      selectedEntity: { kind: 'STEP', id: 'T_S30' },
      faultFlyActive: false,
      onZoomScaleChange: vi.fn(),
      showStationWireLabels: true,
      onSwitchLayer: vi.fn(),
      onSelectEntity: vi.fn(),
      onMoveAndPinNode: vi.fn(),
      onApplyRadialOption: vi.fn(),
    });

    expect(markup).toContain('S30 · 当前工步');

    const nodeCards = collectElements(tree, (el) => el.type === SpatialNodeCard);
    const xCard = nodeCards.find(
      (c) => (c.props.node as { id: string }).id === 'INST_ST20_X'
    )!;
    const gripCard = nodeCards.find(
      (c) => (c.props.node as { id: string }).id === 'INST_ST20_GRIP'
    )!;

    expect(xCard.props.isActiveStep).toBe(true);
    expect(xCard.props.isDimmed).toBe(false);
    expect(xCard.props.activeStepBanner).toEqual({
      stepNo: 30,
      actionLabel: '移至压装位 (245mm)',
    });
    expect(gripCard.props.isDimmed).toBe(true);
  });

  it('prunes healthy guardrails to 0.16 with ✔ 已剪枝健康项 and highlights falsified cut-set during faultFlyActive', () => {
    const ws = createDefaultAfStudioWorkspace();
    const st20 = ws.stationGraphs.ST20;

    const faultTrace: CutSetTraceResult = {
      blockedStationId: 'ST20',
      blockedStepNo: 30,
      blockedNodeId: 'INST_ST20_X',
      prunedHealthyEdgeIds: ['G_ST20_Z_TO_X'],
      falsifiedEdgeIds: ['G_ST20_ST10_TO_X'],
      l1CutSetEdgeId: 'E_L1_2',
      rootCauseStationId: 'ST10',
      rootCauseNodeId: 'INST_ST10_TRANS',
      rootPhysicalTerminal: '%I0.4',
      rootCabinetWireTag: 'X12:04',
      diagnosisSummary: 'ST10 移载气缸原位磁开脱落 (%I0.4=0)',
      flyToStages: [],
    };

    const { tree, markup } = renderComponentTree(HyperEdgeSvgLayer, {
      layer: 'STATION',
      station: st20,
      focusedStepNo: null,
      faultTrace,
      faultFlyActive: true,
      st10SensorHealthy: false,
    });

    const guardGroups = collectElements(
      tree,
      (el) => el.type === 'g' && el.props['data-edge-kind'] === 'guard'
    );
    const healthyEdge = guardGroups.find((g) => g.props['data-edge-id'] === 'G_ST20_Z_TO_X')!;
    const falsifiedEdge = guardGroups.find(
      (g) => g.props['data-edge-id'] === 'G_ST20_ST10_TO_X'
    )!;

    expect((healthyEdge.props.style as { opacity: number }).opacity).toBe(0.16);
    expect(extractText(healthyEdge)).toContain('✔ 已剪枝健康项');
    expect(markup).toContain('✔ 已剪枝健康项 16#0201');

    expect((falsifiedEdge.props.style as { opacity: number }).opacity).toBe(1);
    const faultPath = findElement(
      falsifiedEdge,
      (el) => el.type === 'path' && el.props.stroke !== 'transparent'
    )!;
    expect(faultPath.props.stroke).toBe('#DC2626');
    expect(faultPath.props.strokeWidth).toBe(3.8);
    expect(faultPath.props.className).toBe('af5-wire-fault');
    expect(extractText(falsifiedEdge)).toContain('🚨 阻断割集');
  });

  it('renders GhostGraphTransaction edges in #6366F1 indigo dashed flow', () => {
    const ws = createDefaultAfStudioWorkspace();
    const st20 = ws.stationGraphs.ST20;
    const ghostTx: GhostGraphTransaction = {
      txId: 'tx_ng_branch',
      stationId: 'ST20',
      summary: '新增 NG 抛料分支',
      addedNodes: [],
      addedGuardEdges: [],
      addedTemporalSteps: [
        {
          id: 'T_GHOST_35',
          stepNo: 35,
          title: 'NG移至抛料位',
          fromNode: 'INST_ST20_CAM',
          fromPort: 'OUT_NG',
          invocations: [
            {
              targetNodeId: 'INST_ST20_X',
              targetPortId: 'IN_EXEC',
              methodId: 'MoveReject',
              actionLabel: '移至NG抛料位 (410mm)',
              targetDiscreteState: 'Pos_Reject_410',
              sclStatement: '#DB_ST20_AxisX.MoveAbs(410.0);',
              waitPredicateScl: 'TRUE',
            },
          ],
          branchPredicate: 'NG',
        },
      ],
      verificationPassed: true,
      verifierWarnings: [],
    };

    const { tree, markup } = renderComponentTree(HyperEdgeSvgLayer, {
      layer: 'STATION',
      station: st20,
      ghostTransaction: ghostTx,
      focusedStepNo: null,
      faultFlyActive: false,
    });

    const ghostEdge = findElement(
      tree,
      (el) => el.type === 'g' && el.props['data-edge-kind'] === 'ghost-step'
    )!;
    const ghostPath = findElement(
      ghostEdge,
      (el) => el.type === 'path' && el.props.stroke !== 'transparent'
    )!;
    expect(ghostPath.props.stroke).toBe('#6366F1');
    expect(ghostPath.props.className).toBe('af5-wire-ghost');
    expect(markup).toContain('✨ 虚影预览 S35');
  });

  it('routes reciprocal and parallel edges with distinct orthogonal paths and non-overlapping labels', () => {
    const east = { x: 90, y: 150 };
    const west = { x: 310, y: 150 };
    const edges = [
      { key: 'A', p1: east, p2: west, labelWidth: 100, opacity: 1 },
      { key: 'B', p1: west, p2: east, labelWidth: 100, opacity: 1 },
      { key: 'C', p1: east, p2: west, labelWidth: 100, opacity: 1 },
    ];
    const routes = [...routeOrthogonalEdges(edges, []).values()];
    expect(new Set(routes.map(({ d }) => d)).size).toBe(3);
    routes.forEach((route, index) => {
      expect(route.d).toMatch(/^M [\d.]+ [\d.]+(?: [HV] [\d.]+)+$/);
      for (const previous of routes.slice(0, index)) {
        expect(Math.abs(previous.label.x - route.label.x) >= 108 ||
          Math.abs(previous.label.y - route.label.y) >= 28).toBe(true);
      }
    });
  });
});

describe('RadialCraftMenu & polar coordinate layout', () => {
  it('computes polar positions with radius 112px starting at theta_0 = -pi/2', () => {
    const methods = getRadialMethodsForClass('FB_AF_Actuator2Pos');
    const layout = computeRadialMenuItems(500, 400, methods, 112);

    expect(layout.radius).toBe(112);
    expect(layout.items).toHaveLength(3);

    const first = layout.items[0];
    expect(first.angle).toBeCloseTo(-Math.PI / 2, 6);
    expect(first.offsetX).toBeCloseTo(0, 6);
    expect(first.offsetY).toBeCloseTo(-112, 6);
    expect(first.x).toBeCloseTo(500, 6);
    expect(first.y).toBeCloseTo(288, 6);

    const second = layout.items[1];
    expect(Math.hypot(second.offsetX, second.offsetY)).toBeCloseTo(112, 6);
  });

  it('renders radial craft pills and invokes onSelectMethod when clicked', () => {
    const ws = createDefaultAfStudioWorkspace();
    const axisNode = ws.stationGraphs.ST20.spatialNodes.find((n) => n.id === 'INST_ST20_X')!;
    const methods = getRadialMethodsForClass(axisNode.driverClass, axisNode);
    const onSelectMethod = vi.fn();
    const onClose = vi.fn();

    const { tree } = renderComponentTree(RadialCraftMenu, {
      isOpen: true,
      centerX: 480,
      centerY: 320,
      targetNode: axisNode,
      methods,
      onSelectMethod,
      onClose,
    });

    const buttons = collectElements(
      tree,
      (el) => el.type === 'button' && typeof el.props['data-method-id'] === 'string'
    );
    expect(buttons).toHaveLength(methods.length);

    const pressBtn = buttons.find((b) => b.props['data-method-id'] === 'MovePress')!;
    (pressBtn.props.onClick as () => void)();
    expect(onSelectMethod).toHaveBeenCalledTimes(1);
    expect(onSelectMethod).toHaveBeenCalledWith(
      expect.objectContaining({ methodId: 'MovePress', targetDiscreteState: 'Pos_Press_245' })
    );
  });
});

describe('SemanticZoomStage threshold transitions & banners', () => {
  it('transitions PROJECT -> STATION when scale > 1.35 and STATION -> PROJECT when scale < 0.85', () => {
    expect(evaluateSemanticZoomTransition('PROJECT', 1.35)).toEqual({
      nextLayer: 'PROJECT',
      crossedThreshold: false,
    });
    expect(evaluateSemanticZoomTransition('PROJECT', 1.36)).toEqual({
      nextLayer: 'STATION',
      crossedThreshold: true,
    });
    expect(evaluateSemanticZoomTransition('STATION', 0.85)).toEqual({
      nextLayer: 'STATION',
      crossedThreshold: false,
    });
    expect(evaluateSemanticZoomTransition('STATION', 0.84)).toEqual({
      nextLayer: 'PROJECT',
      crossedThreshold: true,
    });
  });

  it('renders collision verifier banner and fault fly-to controls with callbacks', () => {
    const ws = createDefaultAfStudioWorkspace();
    const st20 = ws.stationGraphs.ST20;
    const onAutoFixCollision = vi.fn();
    const onRepairRootCause = vi.fn();
    const onStopFaultFly = vi.fn();

    const verifierReport: VerificationReport = {
      passed: false,
      elapsedMs: 12,
      exploredStateCount: 16,
      violations: [
        {
          kind: 'MISSING_GUARDRAIL',
          stepNo: 30,
          nodeId: 'INST_ST20_X',
          interferingNodeId: 'INST_ST20_Z',
          message: 'Step 30 缺少 Z轴顶升原位防撞护栏',
        },
      ],
      warnings: [],
    };

    const { tree, markup } = renderComponentTree(SemanticZoomStage, {
      layer: 'STATION',
      zoomScale: 1.5,
      projectGraph: ws.projectGraph,
      station: st20,
      focusedStepNo: null,
      selectedEntity: { kind: 'NODE', id: 'INST_ST20_X' },
      verifierReport,
      faultFlyActive: true,
      st10SensorHealthy: false,
      onZoomScaleChange: vi.fn(),
      onSwitchLayer: vi.fn(),
      onSelectEntity: vi.fn(),
      onMoveAndPinNode: vi.fn(),
      onApplyRadialOption: vi.fn(),
      onAutoFixCollision,
      onRepairRootCause,
      onStopFaultFly,
    });

    expect(markup).toContain('🛡️ 一键补齐防撞护栏');
    expect(markup).toContain('退出追光');

    const fixBtn = findElement(
      tree,
      (el) => el.type === 'button' && extractText(el).includes('一键补齐防撞护栏')
    )!;
    (fixBtn.props.onClick as (e: { stopPropagation: () => void }) => void)({
      stopPropagation: vi.fn(),
    });
    expect(onAutoFixCollision).toHaveBeenCalledOnce();

    const repairBtn = findElement(
      tree,
      (el) => el.type === 'button' && extractText(el).includes('模拟拧紧端子')
    )!;
    (repairBtn.props.onClick as (e: { stopPropagation: () => void }) => void)({
      stopPropagation: vi.fn(),
    });
    expect(onRepairRootCause).toHaveBeenCalledOnce();

    const stopBtn = findElement(
      tree,
      (el) => el.type === 'button' && extractText(el).includes('退出追光')
    )!;
    (stopBtn.props.onClick as (e: { stopPropagation: () => void }) => void)({
      stopPropagation: vi.fn(),
    });
    expect(onStopFaultFly).toHaveBeenCalledOnce();
  });

  it('dives from L1 PROJECT station card double-click into L2 STATION and highlights L1 fault cut-set', () => {
    const ws = createDefaultAfStudioWorkspace();
    const onSwitchLayer = vi.fn();

    const { tree, markup } = renderComponentTree(SemanticZoomStage, {
      layer: 'PROJECT',
      zoomScale: 0.8,
      projectGraph: ws.projectGraph,
      station: ws.stationGraphs.ST20,
      focusedStepNo: null,
      selectedEntity: { kind: 'STATION', id: 'NODE_ST20' },
      faultFlyActive: true,
      st10SensorHealthy: false,
      onZoomScaleChange: vi.fn(),
      onSwitchLayer,
      onSelectEntity: vi.fn(),
      onMoveAndPinNode: vi.fn(),
      onApplyRadialOption: vi.fn(),
    });

    expect(markup).toContain('L1 产线复合总图');
    expect(markup).toContain('🚨 最小证伪割集');

    const st20Card = findElement(
      tree,
      (el) => el.props['data-station-id'] === 'ST20'
    )!;
    (st20Card.props.onDoubleClick as (e: { stopPropagation: () => void }) => void)({
      stopPropagation: vi.fn(),
    });
    expect(onSwitchLayer).toHaveBeenCalledWith('STATION', 'ST20');
  });
});

describe('SpatialNodeCard interactions & fault display', () => {
  it('triggers onStartRubberWire from output socket and onDropWireOnNode on card mouseUp', () => {
    const ws = createDefaultAfStudioWorkspace();
    const st10Trans = ws.stationGraphs.ST10.spatialNodes.find(
      (n) => n.id === 'INST_ST10_TRANS'
    )!;
    const onStartRubberWire = vi.fn();
    const onDropWireOnNode = vi.fn();

    const { tree, markup } = renderComponentTree(SpatialNodeCard, {
      node: st10Trans,
      invokeCount: 1,
      isSelected: false,
      isDimmed: false,
      isActiveStep: false,
      isDropTargetHover: false,
      isFaultRoot: true,
      isRubberDragActive: true,
      onMouseDownMove: vi.fn(),
      onStartRubberWire,
      onDropWireOnNode,
    });

    expect(markup).toContain('🚨 故障端子脱落');
    expect(markup).toContain('DB_ST10_CylTransfer');
    expect(markup).toContain('1拍复用');
    expect(markup).toContain('is-fault-root');

    const outSocket = findElement(
      tree,
      (el) => el.props['data-port-id'] === 'OUT_DONE' && el.props['data-port-dir'] === 'out'
    )!;
    (outSocket.props.onMouseDown as (e: { stopPropagation: () => void; preventDefault: () => void }) => void)({
      stopPropagation: vi.fn(),
      preventDefault: vi.fn(),
    });
    expect(onStartRubberWire).toHaveBeenCalledWith(
      expect.any(Object),
      'INST_ST10_TRANS',
      'OUT_DONE',
      'SEQ',
      '● 送料完成握手 →'
    );

    const cardRoot = findElement(
      tree,
      (el) => el.props['data-node-id'] === 'INST_ST10_TRANS'
    )!;
    (cardRoot.props.onMouseUp as (e: { clientX: number; clientY: number; stopPropagation: () => void }) => void)({
      clientX: 460,
      clientY: 210,
      stopPropagation: vi.fn(),
    });
    expect(onDropWireOnNode).toHaveBeenCalledWith(460, 210, st10Trans);
  });
});

describe('TimeRibbonScrubber ordering, step switching, and prompt submission', () => {
  it('renders steps sorted ascending by stepNo and triggers focus & prompt callbacks', () => {
    const ws = createDefaultAfStudioWorkspace();
    const st20 = ws.stationGraphs.ST20;
    // Deliberately shuffle steps to verify ascending sort by stepNo
    st20.temporalSteps = [
      st20.temporalSteps[3], // S40
      st20.temporalSteps[0], // S10
      st20.temporalSteps[4], // S50
      st20.temporalSteps[2], // S30
      st20.temporalSteps[1], // S20
    ];

    const onFocusStep = vi.fn();
    const onSubmitPrompt = vi.fn();

    const { tree } = renderComponentTree(TimeRibbonScrubber, {
      layer: 'STATION',
      station: st20,
      focusedStepNo: 20,
      onFocusStep,
      onSubmitPrompt,
    });

    const stepButtons = collectElements(
      tree,
      (el) => el.type === 'button' && typeof el.props['data-step-no'] === 'number'
    );
    expect(stepButtons.map((b) => b.props['data-step-no'])).toEqual([10, 20, 30, 40, 50]);

    const s30Btn = stepButtons.find((b) => b.props['data-step-no'] === 30)!;
    (s30Btn.props.onClick as () => void)();
    expect(onFocusStep).toHaveBeenCalledWith(30);

    const allBtn = findElement(
      tree,
      (el) => el.type === 'button' && el.props['data-step-filter'] === 'all'
    )!;
    (allBtn.props.onClick as () => void)();
    expect(onFocusStep).toHaveBeenCalledWith(null);

    const input = findElement(tree, (el) => el.type === 'input')!;
    const submitBtn = findElement(
      tree,
      (el) => el.type === 'button' && extractText(el) === '预览'
    )!;

    (input.props.onChange as (e: { target: { value: string } }) => void)({
      target: { value: '增加视觉NG抛料分支' },
    });
    (submitBtn.props.onClick as () => void)();
    expect(onSubmitPrompt).toHaveBeenCalledWith('增加视觉NG抛料分支');

    (input.props.onChange as (e: { target: { value: string } }) => void)({
      target: { value: '补齐Z轴护栏' },
    });
    (input.props.onKeyDown as (e: { key: string; preventDefault: () => void }) => void)({
      key: 'Enter',
      preventDefault: vi.fn(),
    });
    expect(onSubmitPrompt).toHaveBeenCalledWith('补齐Z轴护栏');
  });
});
