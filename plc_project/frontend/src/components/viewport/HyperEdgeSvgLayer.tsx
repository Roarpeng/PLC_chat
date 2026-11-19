import React from 'react';
import type {
  CutSetTraceResult,
  GhostGraphTransaction,
  ProjectCompoundEdge,
  ProjectHyperGraph,
  SafetyGuardEdge,
  SpatialInstanceNode,
  StationHyperGraph,
  TemporalStepHyperEdge,
} from '../../core/ir/afHyperGraph.types';
import { orthogonalPath, routeOrthogonalEdges, type Point2D, type RouteBox } from './orthogonalRoutes';

export type { Point2D } from './orthogonalRoutes';

export interface RubberBandState {
  startX: number;
  startY: number;
  endX: number;
  endY: number;
}

export interface HyperEdgeSvgLayerProps {
  layer: 'PROJECT' | 'STATION';
  projectGraph?: ProjectHyperGraph | null;
  station?: StationHyperGraph | null;
  ghostTransaction?: GhostGraphTransaction | null;
  focusedStepNo: number | null;
  faultTrace?: CutSetTraceResult | null;
  faultFlyActive: boolean;
  st10SensorHealthy?: boolean;
  rubberBand?: RubberBandState | null;
  portPositions?: Record<string, Point2D>;
  nodeBoxes?: RouteBox[];
  compactStationWires?: boolean;
  showStationWireLabels?: boolean;
  onSelectGuard?: (guard: SafetyGuardEdge) => void;
  onSelectStep?: (step: TemporalStepHyperEdge) => void;
  onSelectProjectEdge?: (edge: ProjectCompoundEdge) => void;
  onDeleteGuard?: (edgeId: string) => void;
  onDeleteStep?: (stepId: string) => void;
  onDeleteProjectEdge?: (edgeId: string) => void;
}


/** 根据节点空间坐标推算确定性端口锚点坐标（保障 SSR 与首帧零延迟渲染 SVG 边） */
export function computeFallbackPortPositions(params: {
  layer: 'PROJECT' | 'STATION';
  projectGraph?: ProjectHyperGraph | null;
  station?: StationHyperGraph | null;
  ghostNodes?: SpatialInstanceNode[];
}): Record<string, Point2D> {
  const positions: Record<string, Point2D> = {};

  if (params.layer === 'PROJECT' && params.projectGraph) {
    for (const st of params.projectGraph.stations) {
      const cardWidth = 264;
      const baseTop = st.position.y + 72 + st.instanceSummaries.length * 14;
      st.inPorts.forEach((port, idx) => {
        positions[`${st.id}:${port.id}`] = {
          x: st.position.x,
          y: baseTop + idx * 19,
        };
      });
      st.outPorts.forEach((port, idx) => {
        positions[`${st.id}:${port.id}`] = {
          x: st.position.x + cardWidth,
          y: baseTop + idx * 19,
        };
      });
    }
    return positions;
  }

  const nodes = [
    ...(params.station?.spatialNodes ?? []),
    ...(params.ghostNodes ?? []),
  ];
  const cardWidth = 252;
  for (const node of nodes) {
    const baseTop = node.position.y + 78;
    node.inPorts.forEach((port, idx) => {
      positions[`${node.id}:${port.id}`] = {
        x: node.position.x,
        y: baseTop + idx * 24,
      };
    });
    const outStartTop =
      baseTop + (node.inPorts.length > 0 ? node.inPorts.length * 24 + 12 : 0);
    node.outPorts.forEach((port, idx) => {
      positions[`${node.id}:${port.id}`] = {
        x: node.position.x + cardWidth,
        y: outStartTop + idx * 24,
      };
    });
  }

  return positions;
}

function resolvePortPoint(
  nodeId: string,
  portId: string,
  measured: Record<string, Point2D> | undefined,
  fallback: Record<string, Point2D>
): Point2D | null {
  const canonical = `${nodeId}:${portId}`;
  const dashKey = `${nodeId}-${portId}`;
  const domKey = `port-${nodeId}-${portId}`;
  return (
    measured?.[canonical] ??
    measured?.[dashKey] ??
    measured?.[domKey] ??
    fallback[canonical] ??
    null
  );
}

function resolveTargetInputPortId(
  nodes: SpatialInstanceNode[],
  targetNodeId: string,
  preferredPortId?: string
): string {
  if (preferredPortId) return preferredPortId;
  const targetNode = nodes.find((n) => n.id === targetNodeId);
  if (!targetNode) return 'IN_EXEC';
  return (
    targetNode.inPorts.find((p) => p.type === 'SEQ')?.id ??
    targetNode.inPorts[0]?.id ??
    'IN_EXEC'
  );
}

function truncateBadge(text: string): string {
  return text.length > 26 ? `${text.slice(0, 25)}…` : text;
}

function estimateBadgeWidth(text: string): number {
  let visualUnits = 0;
  for (const ch of text) {
    visualUnits += ch.charCodeAt(0) > 127 ? 1.55 : 0.92;
  }
  return Math.min(Math.max(Math.round(visualUnits * 7.2 + 18), 84), 240);
}

interface RenderedEdgeDescriptor {
  key: string;
  edgeId: string;
  edgeKind: 'guard' | 'step' | 'ghost-guard' | 'ghost-step' | 'l1-edge';
  stepNo?: number;
  p1: Point2D;
  p2: Point2D;
  stroke: string;
  markerId: string;
  wireClassName: string;
  strokeWidth: number;
  opacity: number;
  badgeText: string;
  isFault?: boolean;
  isGhost?: boolean;
  isPruned?: boolean;
  onClick?: () => void;
  onDelete?: () => void;
}

function renderOrthogonalEdge(edge: RenderedEdgeDescriptor, route: { d: string; label: Point2D; leader?: string }): React.ReactNode {
  const label = truncateBadge(edge.badgeText);
  const bw = estimateBadgeWidth(label);
  const hasDelete = Boolean(edge.onDelete);
  const totalBw = hasDelete ? bw + 20 : bw;
  const textCenterX = hasDelete ? route.label.x - 9 : route.label.x;
  const delX = route.label.x + totalBw / 2 - 10;

  const badgeFill = edge.isFault
    ? '#DC2626'
    : edge.isGhost
      ? '#EEF2FF'
      : '#FFFFFF';
  const badgeTextColor = edge.isFault
    ? '#FFFFFF'
    : edge.isGhost
      ? '#4338CA'
      : '#181816';

  const groupClass = ['af5-wire-edge', edge.onClick ? 'is-interactive' : '']
    .filter(Boolean)
    .join(' ');

  return (
    <g
      key={edge.key}
      className={groupClass}
      style={{ opacity: edge.opacity }}
      data-edge-kind={edge.edgeKind}
      data-edge-id={edge.edgeId}
      data-step-no={edge.stepNo}
      data-pruned={edge.isPruned ? 'true' : undefined}
      data-falsified={edge.isFault ? 'true' : undefined}
      onClick={
        edge.onClick
          ? (e) => {
              e.stopPropagation();
              edge.onClick?.();
            }
          : undefined
      }
    >
      <path
        d={route.d}
        fill="none"
        stroke="transparent"
        strokeWidth={14}
      />
      <path
        d={route.d}
        fill="none"
        stroke={edge.stroke}
        strokeWidth={edge.strokeWidth}
        className={edge.wireClassName || undefined}
        markerEnd={`url(#${edge.markerId})`}
      />
      {label && <>
      {route.leader && <path d={route.leader} fill="none" stroke={edge.stroke} strokeDasharray="3 3" />}
      <rect
        x={route.label.x - totalBw / 2}
        y={route.label.y - 10.5}
        width={totalBw}
        height={21}
        rx={2}
        fill={badgeFill}
        stroke={edge.stroke}
        strokeWidth={1.4}
      />
      <text
        x={textCenterX}
        y={route.label.y + 3.5}
        textAnchor="middle"
        fill={badgeTextColor}
        fontSize={10}
        className="af5-edge-badge-text"
        style={{ pointerEvents: 'none' }}
      >
        {label}
      </text>
      </>}
      {edge.onDelete && (
        <g
          data-testid={`canvas-delete-edge-${edge.edgeId}`}
          style={{ cursor: 'pointer', pointerEvents: 'all' }}
          onMouseDown={(e) => e.stopPropagation()}
          onClick={(e) => {
            e.stopPropagation();
            edge.onDelete?.();
          }}
        >
          <title>删除此连线</title>
          <circle
            cx={delX}
            cy={route.label.y}
            r={7}
            fill="#DC2626"
            style={{ pointerEvents: 'all' }}
          />
          <text
            x={delX}
            y={route.label.y + 3.2}
            textAnchor="middle"
            fill="#FFFFFF"
            fontSize={9}
            fontWeight={700}
            style={{ pointerEvents: 'none', userSelect: 'none' }}
          >
            ✕
          </text>
        </g>
      )}
    </g>
  );
}

export const HyperEdgeSvgLayer: React.FC<HyperEdgeSvgLayerProps> = ({
  layer,
  projectGraph,
  station,
  ghostTransaction,
  focusedStepNo,
  faultTrace,
  faultFlyActive,
  st10SensorHealthy = false,
  rubberBand,
  portPositions,
  nodeBoxes,
  compactStationWires = false,
  showStationWireLabels = false,
  onSelectGuard,
  onSelectStep,
  onSelectProjectEdge,
  onDeleteGuard,
  onDeleteStep,
  onDeleteProjectEdge,
}) => {
  const ghostNodes =
    ghostTransaction && (!station || ghostTransaction.stationId === station.stationId)
      ? ghostTransaction.addedNodes
      : [];

  const fallbackPorts = computeFallbackPortPositions({
    layer,
    projectGraph,
    station,
    ghostNodes,
  });

  const edgeDescriptors: RenderedEdgeDescriptor[] = [];
  const compact = layer === 'STATION' && compactStationWires && !faultFlyActive;
  const hideStationLabels = compact && !showStationWireLabels;

  if (layer === 'PROJECT' && projectGraph) {
    for (const edge of projectGraph.edges) {
      const p1 = resolvePortPoint(edge.fromNode, edge.fromPort, portPositions, fallbackPorts);
      const p2 = resolvePortPoint(edge.toNode, edge.toPort, portPositions, fallbackPorts);
      if (!p1 || !p2) continue;

      const isFault =
        faultFlyActive &&
        !st10SensorHealthy &&
        (faultTrace?.l1CutSetEdgeId === edge.id || Boolean(edge.isFaultCutSet));

      const isGuard = edge.kind === 'GUARD';

      edgeDescriptors.push({
        key: `l1-${edge.id}`,
        edgeId: edge.id,
        edgeKind: 'l1-edge',
        p1,
        p2,
        stroke: isFault ? '#DC2626' : isGuard ? '#D97706' : '#2563EB',
        markerId: isFault
          ? 'af5-arrow-vermilion'
          : isGuard
            ? 'af5-arrow-amber'
            : 'af5-arrow-klein',
        wireClassName: isFault
          ? 'af5-wire-fault'
          : isGuard
            ? 'af5-wire-guard'
            : '',
        strokeWidth: isFault ? 3.8 : edge.managedByOrchestration ? 1.6 : 2.4,
        opacity: faultFlyActive && !isFault ? 0.22 : edge.managedByOrchestration ? 0.68 : 1,
        badgeText: isFault ? `🚨 最小证伪割集 ${edge.label}` : edge.label,
        isFault,
        onClick: !edge.managedByOrchestration && onSelectProjectEdge ? () => onSelectProjectEdge(edge) : undefined,
        onDelete: !edge.managedByOrchestration && onDeleteProjectEdge ? () => onDeleteProjectEdge(edge.id) : undefined,
      });
    }
  } else if (layer === 'STATION' && station) {
    const allStationNodes = [...station.spatialNodes, ...ghostNodes];
    const activeStep =
      focusedStepNo !== null
        ? station.temporalSteps.find((s) => s.stepNo === focusedStepNo) ?? null
        : null;
    const activeControlledNodeIds = new Set(
      activeStep?.invocations.map((inv) => inv.targetNodeId) ?? []
    );

    // 1. 永久安全护栏边 (E_guard)
    for (const g of station.guardEdges) {
      if (compact && activeStep && !activeControlledNodeIds.has(g.toNode)) continue;
      const p1 = resolvePortPoint(g.fromNode, g.fromPort, portPositions, fallbackPorts);
      const p2 = resolvePortPoint(g.toNode, g.toPort, portPositions, fallbackPorts);
      if (!p1 || !p2) continue;

      let isFalsified = false;
      let isPrunedHealthy = false;
      if (faultFlyActive) {
        if (faultTrace) {
          isFalsified =
            faultTrace.falsifiedEdgeIds.includes(g.id) &&
            !(g.crossStationRef && st10SensorHealthy);
          isPrunedHealthy =
            faultTrace.prunedHealthyEdgeIds.includes(g.id) || !isFalsified;
        } else {
          isFalsified =
            Boolean(g.crossStationRef || g.isHealthy === false) && !st10SensorHealthy;
          isPrunedHealthy = !isFalsified;
        }
      }

      let opacity = 0.9;
      if (faultFlyActive) {
        opacity = isFalsified ? 1 : 0.16;
      } else if (activeStep) {
        opacity = activeControlledNodeIds.has(g.toNode) ? 1 : 0.15;
      }
      if (compact && !activeStep) opacity = 0.45;

      const badgeText = isFalsified
        ? `🚨 阻断割集 ${g.diagCodeHex}`
        : isPrunedHealthy
          ? `✔ 已剪枝健康项 ${g.diagCodeHex}`
          : `🛡️ 护栏 ${g.diagCodeHex}`;

      edgeDescriptors.push({
        key: `guard-${g.id}`,
        edgeId: g.id,
        edgeKind: 'guard',
        p1,
        p2,
        stroke: isFalsified ? '#DC2626' : '#D97706',
        markerId: isFalsified ? 'af5-arrow-vermilion' : 'af5-arrow-amber',
        wireClassName: isFalsified ? 'af5-wire-fault' : 'af5-wire-guard',
        strokeWidth: isFalsified ? 3.8 : 2.1,
        opacity,
        badgeText: hideStationLabels ? '' : badgeText,
        isFault: isFalsified,
        isPruned: isPrunedHealthy,
        onClick: onSelectGuard ? () => onSelectGuard(g) : undefined,
        onDelete: !hideStationLabels && onDeleteGuard ? () => onDeleteGuard(g.id) : undefined,
      });
    }

    // 2. 时序控制超边 (T_seq)
    station.temporalSteps.forEach((step) => {
      const isFocused = focusedStepNo === step.stepNo;
      if (compact && activeStep && !isFocused) return;

      step.invocations.forEach((inv, invIdx) => {
        const targetPortId = resolveTargetInputPortId(
          allStationNodes,
          inv.targetNodeId,
          inv.targetPortId
        );
        const p1 = resolvePortPoint(step.fromNode, step.fromPort, portPositions, fallbackPorts);
        const p2 = resolvePortPoint(inv.targetNodeId, targetPortId, portPositions, fallbackPorts);
        if (!p1 || !p2) return;

        let opacity = 0.92;
        let wireClassName = '';
        let stroke = '#2563EB';
        let markerId = 'af5-arrow-klein';
        let strokeWidth = 2.3;

        if (faultFlyActive) {
          const isBlockedStep = faultTrace
            ? step.stepNo === faultTrace.blockedStepNo &&
              station.stationId === faultTrace.blockedStationId
            : station.stationId === 'ST20' && step.stepNo === 30;
          opacity = isBlockedStep ? 0.95 : 0.12;
        } else if (focusedStepNo !== null) {
          if (isFocused) {
            opacity = 1;
            wireClassName = 'af5-wire-active';
            stroke = '#059669';
            markerId = 'af5-arrow-emerald';
            strokeWidth = 3.6;
          } else {
            opacity = 0.12;
          }
        }
        if (compact && !activeStep) {
          opacity = 0.4;
          strokeWidth = 1.5;
        }

        edgeDescriptors.push({
          key: `step-${step.id}-${inv.targetNodeId}-${invIdx}`,
          edgeId: step.id,
          edgeKind: 'step',
          stepNo: step.stepNo,
          p1,
          p2,
          stroke,
          markerId,
          wireClassName,
          strokeWidth,
          opacity,
          badgeText: hideStationLabels ? '' : `S${step.stepNo}: ${inv.actionLabel}`,
          onClick: onSelectStep ? () => onSelectStep(step) : undefined,
          onDelete: !hideStationLabels && onDeleteStep ? () => onDeleteStep(step.id) : undefined,
        });
      });
    });

    // 3. 神经符号 AI 虚影预览补丁 (Ghost Wire Diff)
    if (ghostTransaction && ghostTransaction.stationId === station.stationId) {
      ghostTransaction.addedGuardEdges.forEach((g) => {
        const p1 = resolvePortPoint(g.fromNode, g.fromPort, portPositions, fallbackPorts);
        const p2 = resolvePortPoint(g.toNode, g.toPort, portPositions, fallbackPorts);
        if (!p1 || !p2) return;

        edgeDescriptors.push({
          key: `ghost-guard-${g.id}`,
          edgeId: g.id,
          edgeKind: 'ghost-guard',
          p1,
          p2,
          stroke: '#6366F1',
          markerId: 'af5-arrow-indigo',
          wireClassName: 'af5-wire-ghost',
          strokeWidth: 3,
          opacity: 0.95,
          badgeText: `✨ 虚影护栏 ${g.diagCodeHex}`,
          isGhost: true,
        });
      });

      ghostTransaction.addedTemporalSteps.forEach((step) => {
        step.invocations.forEach((inv, invIdx) => {
          const targetPortId = resolveTargetInputPortId(
            allStationNodes,
            inv.targetNodeId,
            inv.targetPortId
          );
          const p1 = resolvePortPoint(step.fromNode, step.fromPort, portPositions, fallbackPorts);
          const p2 = resolvePortPoint(inv.targetNodeId, targetPortId, portPositions, fallbackPorts);
          if (!p1 || !p2) return;

          edgeDescriptors.push({
            key: `ghost-step-${step.id}-${inv.targetNodeId}-${invIdx}`,
            edgeId: step.id,
            edgeKind: 'ghost-step',
            stepNo: step.stepNo,
            p1,
            p2,
            stroke: '#6366F1',
            markerId: 'af5-arrow-indigo',
            wireClassName: 'af5-wire-ghost',
            strokeWidth: 3,
            opacity: 0.95,
            badgeText: `✨ 虚影预览 S${step.stepNo}: ${inv.actionLabel}`,
            isGhost: true,
          });
        });
      });
    }
  }

  const layoutNodes = layer === 'PROJECT' ? projectGraph?.stations ?? [] : [...(station?.spatialNodes ?? []), ...ghostNodes];
  const boxes = nodeBoxes?.length ? nodeBoxes : layoutNodes.map(({ position, inPorts, outPorts }) => ({
    left: position.x, right: position.x + (layer === 'PROJECT' ? 264 : 252), top: position.y,
    bottom: position.y + (layer === 'PROJECT' ? 138 : 85 + (inPorts.length + outPorts.length) * 24),
  }));
  const routes = routeOrthogonalEdges(edgeDescriptors.map((edge) => ({
    ...edge, labelWidth: edge.badgeText ? estimateBadgeWidth(truncateBadge(edge.badgeText)) + (edge.onDelete ? 20 : 0) : 0,
  })), boxes);
  const rubberPath = rubberBand ? orthogonalPath([
    { x: rubberBand.startX, y: rubberBand.startY },
    { x: (rubberBand.startX + rubberBand.endX) / 2, y: rubberBand.startY },
    { x: (rubberBand.startX + rubberBand.endX) / 2, y: rubberBand.endY },
    { x: rubberBand.endX, y: rubberBand.endY },
  ]) : null;

  return (
    <svg className="af5-svg-layer" aria-label="AF-Studio 超边连线层">
      <defs>
        <marker
          id="af5-arrow-klein"
          viewBox="0 0 10 10"
          refX="7"
          refY="5"
          markerWidth="6"
          markerHeight="6"
          orient="auto-start-reverse"
        >
          <path d="M 0 1 L 8 5 L 0 9 z" fill="#2563EB" />
        </marker>
        <marker
          id="af5-arrow-emerald"
          viewBox="0 0 10 10"
          refX="7"
          refY="5"
          markerWidth="6"
          markerHeight="6"
          orient="auto-start-reverse"
        >
          <path d="M 0 1 L 8 5 L 0 9 z" fill="#059669" />
        </marker>
        <marker
          id="af5-arrow-amber"
          viewBox="0 0 10 10"
          refX="7"
          refY="5"
          markerWidth="6"
          markerHeight="6"
          orient="auto-start-reverse"
        >
          <path d="M 0 1 L 8 5 L 0 9 z" fill="#D97706" />
        </marker>
        <marker
          id="af5-arrow-indigo"
          viewBox="0 0 10 10"
          refX="7"
          refY="5"
          markerWidth="6"
          markerHeight="6"
          orient="auto-start-reverse"
        >
          <path d="M 0 1 L 8 5 L 0 9 z" fill="#6366F1" />
        </marker>
        <marker
          id="af5-arrow-vermilion"
          viewBox="0 0 10 10"
          refX="7"
          refY="5"
          markerWidth="7"
          markerHeight="7"
          orient="auto-start-reverse"
        >
          <path d="M 0 1 L 8 5 L 0 9 z" fill="#DC2626" />
        </marker>
      </defs>

      <g className="af5-wire-group">{edgeDescriptors.map((edge) => renderOrthogonalEdge(edge, routes.get(edge.key)!))}</g>

      {rubberPath && (
        <path
          className="af5-rubber-band"
          d={rubberPath}
          fill="none"
          stroke="#6366F1"
          strokeWidth={2.8}
          strokeDasharray="6 4"
          markerEnd="url(#af5-arrow-indigo)"
        />
      )}
    </svg>
  );
};
