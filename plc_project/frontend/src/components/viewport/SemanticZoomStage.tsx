import React, { useEffect, useRef, useState } from 'react';
import '../../styles/afStudioV5.css';
import type {
  CameraFlyToStage,
  CutSetTraceResult,
  GhostGraphTransaction,
  ProjectCompoundStation,
  ProjectHyperGraph,
  RadialMethodOption,
  SelectedHyperEntity,
  SpatialInstanceNode,
  StationHyperGraph,
  VerificationReport,
} from '../../core/ir/afHyperGraph.types';
import { getRadialMethodsForClass } from '../../core/ir/motherClassRegistry';
import { HyperEdgeSvgLayer, type Point2D, type RubberBandState } from './HyperEdgeSvgLayer';
import { RadialCraftMenu } from './RadialCraftMenu';
import { SpatialNodeCard } from './SpatialNodeCard';
import type { RouteBox } from './orthogonalRoutes';
import { ProjectRelationDetails, ProjectRelationsLayer, visibleProjectRelations } from './ProjectRelations';

export const ZOOM_SCALE_MIN = 0.65;
export const ZOOM_SCALE_MAX = 1.85;
export const L1_TO_L2_THRESHOLD = 1.35;
export const L2_TO_L1_THRESHOLD = 0.85;

export function clampZoomScale(scale: number): number {
  return Math.max(ZOOM_SCALE_MIN, Math.min(ZOOM_SCALE_MAX, Number(scale.toFixed(2))));
}

/**
 * 评估语义缩放阈值越界切换：
 * - L1 (PROJECT) 下 nextScale > 1.35 -> 推入 L2 (STATION) 玻璃盒展开
 * - L2 (STATION) 下 nextScale < 0.85 -> 收拢返回 L1 (PROJECT) 产线总图
 */
export function evaluateSemanticZoomTransition(
  currentLayer: 'PROJECT' | 'STATION',
  nextScale: number
): { nextLayer: 'PROJECT' | 'STATION'; crossedThreshold: boolean } {
  if (currentLayer === 'PROJECT' && nextScale > L1_TO_L2_THRESHOLD) {
    return { nextLayer: 'STATION', crossedThreshold: true };
  }
  if (currentLayer === 'STATION' && nextScale < L2_TO_L1_THRESHOLD) {
    return { nextLayer: 'PROJECT', crossedThreshold: true };
  }
  return { nextLayer: currentLayer, crossedThreshold: false };
}

function areMeasuredPortsEqual(
  prev: Record<string, Point2D>,
  next: Record<string, Point2D>
): boolean {
  const prevKeys = Object.keys(prev);
  const nextKeys = Object.keys(next);
  if (prevKeys.length !== nextKeys.length) return false;
  for (const key of nextKeys) {
    const a = prev[key];
    const b = next[key];
    if (!a || Math.round(a.x) !== Math.round(b.x) || Math.round(a.y) !== Math.round(b.y)) {
      return false;
    }
  }
  return true;
}

export interface RadialApplyPayload {
  fromNodeId: string;
  fromPortId: string;
  portType: 'SEQ' | 'GUARD';
  portLabel: string;
  targetNode: SpatialInstanceNode;
  option: RadialMethodOption;
}

export interface SemanticZoomStageProps {
  layer: 'PROJECT' | 'STATION';
  zoomScale: number;
  projectGraph: ProjectHyperGraph;
  projectName?: string;
  station?: StationHyperGraph | null;
  focusedStepNo: number | null;
  showStationWireLabels?: boolean;
  selectedEntity: SelectedHyperEntity;
  ghostTransaction?: GhostGraphTransaction | null;
  verifierReport?: VerificationReport | null;
  cutSetTrace?: CutSetTraceResult | null;
  faultFlyActive: boolean;
  flyToStage?: CameraFlyToStage | null;
  st10SensorHealthy?: boolean;
  ghostBannerSlot?: React.ReactNode;
  onZoomScaleChange: (nextScale: number) => void;
  onSwitchLayer: (layer: 'PROJECT' | 'STATION', stationId?: string) => void;
  onSelectEntity: (entity: SelectedHyperEntity) => void;
  onOpenNode?: (nodeId: string) => void;
  onMoveAndPinNode: (
    layer: 'PROJECT' | 'STATION',
    nodeId: string,
    position: { x: number; y: number }
  ) => void;
  onApplyRadialOption: (payload: RadialApplyPayload) => void;
  onCreateProjectEdge?: (payload: {
    fromNode: string;
    fromPort: string;
    toNode: string;
    toPort: string;
    kind: 'SEQ' | 'GUARD';
    label: string;
  }) => void;
  onAutoFixCollision?: () => void;
  onRepairRootCause?: () => void;
  onStopFaultFly?: () => void;
  onSelectStepNo?: (stepNo: number | null) => void;
  onDeleteNode?: (nodeId: string) => void;
  onDeleteGuard?: (edgeId: string) => void;
  onDeleteStep?: (stepId: string) => void;
  onDeleteProjectEdge?: (edgeId: string) => void;
  onDeleteProjectStation?: (nodeId: string) => void;
  onCopyProjectStation?: (station: ProjectCompoundStation) => void;
  onArrangeProjectStations?: () => void;
}

interface DraggingNodeState {
  layer: 'PROJECT' | 'STATION';
  nodeId: string;
  startX: number;
  startY: number;
  offsetX: number;
  offsetY: number;
  cardWidth: number;
}

interface ActiveRubberDrag {
  fromNodeId: string;
  fromPortId: string;
  portType: 'SEQ' | 'GUARD';
  portLabel: string;
  rubberBand: RubberBandState;
}

interface RadialMenuContext {
  centerX: number;
  centerY: number;
  targetNode: SpatialInstanceNode;
  methods: RadialMethodOption[];
  fromNodeId: string;
  fromPortId: string;
  portType: 'SEQ' | 'GUARD';
  portLabel: string;
}

export const SemanticZoomStage: React.FC<SemanticZoomStageProps> = ({
  layer,
  zoomScale,
  projectGraph,
  projectName,
  station,
  focusedStepNo,
  showStationWireLabels = false,
  selectedEntity,
  ghostTransaction,
  verifierReport,
  cutSetTrace,
  faultFlyActive,
  flyToStage,
  st10SensorHealthy = false,
  ghostBannerSlot,
  onZoomScaleChange,
  onSwitchLayer,
  onSelectEntity,
  onOpenNode,
  onMoveAndPinNode,
  onApplyRadialOption,
  onCreateProjectEdge,
  onAutoFixCollision,
  onRepairRootCause,
  onStopFaultFly,
  onSelectStepNo,
  onDeleteNode,
  onDeleteGuard,
  onDeleteStep,
  onDeleteProjectEdge,
  onDeleteProjectStation,
  onCopyProjectStation,
  onArrangeProjectStations,
}) => {
  const viewportRef = useRef<HTMLElement | null>(null);
  const prevLayerRef = useRef<'PROJECT' | 'STATION'>(layer);
  const [isZoomFlashing, setIsZoomFlashing] = useState(false);
  const [draggingNode, setDraggingNode] = useState<DraggingNodeState | null>(null);
  const [rubberDrag, setRubberDrag] = useState<ActiveRubberDrag | null>(null);
  const [dropHoverNodeId, setDropHoverNodeId] = useState<string | null>(null);
  const [radialContext, setRadialContext] = useState<RadialMenuContext | null>(null);
  const [measuredPorts, setMeasuredPorts] = useState<Record<string, Point2D>>({});
  const [nodeBoxes, setNodeBoxes] = useState<RouteBox[]>([]);
  const [showAllRelations, setShowAllRelations] = useState(false);

  // 语义缩放转场闪光动画
  useEffect(() => {
    if (prevLayerRef.current !== layer) {
      prevLayerRef.current = layer;
      setIsZoomFlashing(true);
      const timer = setTimeout(() => setIsZoomFlashing(false), 340);
      return () => clearTimeout(timer);
    }
    return undefined;
  }, [layer]);

  // Ctrl/Meta + Wheel 非被动监听：平滑语义缩放并在阈值处切换 L1/L2
  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return undefined;

    const handleWheel = (e: WheelEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      e.preventDefault();

      const direction = e.deltaY < 0 ? 1 : -1;
      const stepMag = Math.max(0.14, Math.min(0.36, Math.abs(e.deltaY) * 0.003));
      const nextScale = clampZoomScale(zoomScale + direction * stepMag);
      const transition = evaluateSemanticZoomTransition(layer, nextScale);

      if (transition.crossedThreshold) {
        if (transition.nextLayer === 'STATION') {
          const targetEl = e.target as HTMLElement | null;
          const hoveredStationId =
            targetEl?.closest?.('[data-station-id]')?.getAttribute('data-station-id') ??
            undefined;
          const nextStationId =
            hoveredStationId ??
            station?.stationId ??
            projectGraph.stations[0]?.stationId;
          onZoomScaleChange(Math.max(nextScale, 1.5));
          onSwitchLayer('STATION', nextStationId);
        } else {
          onZoomScaleChange(Math.min(nextScale, 0.8));
          onSwitchLayer('PROJECT');
        }
      } else {
        onZoomScaleChange(nextScale);
      }
    };

    el.addEventListener('wheel', handleWheel, { passive: false });
    return () => el.removeEventListener('wheel', handleWheel);
  }, [
    layer,
    zoomScale,
    station?.stationId,
    projectGraph.stations,
    onZoomScaleChange,
    onSwitchLayer,
  ]);

  // 节点拖拽与橡皮筋拉线全局鼠标跟随
  useEffect(() => {
    if ((!draggingNode && !rubberDrag) || typeof window === 'undefined') {
      return undefined;
    }

    let hasMoved = false;
    const handleMouseMove = (e: MouseEvent) => {
      const vp = viewportRef.current;
      if (!vp) return;
      const vpRect = vp.getBoundingClientRect();

      if (draggingNode) {
        if (!hasMoved && Math.hypot(e.clientX - draggingNode.startX, e.clientY - draggingNode.startY) < 4) return;
        hasMoved = true;
        const maxX = Math.max(960, vp.scrollWidth - draggingNode.cardWidth - 12);
        const maxY = Math.max(520, vp.scrollHeight - 155);
        const rawX = e.clientX - vpRect.left + vp.scrollLeft - draggingNode.offsetX;
        const rawY = e.clientY - vpRect.top + vp.scrollTop - draggingNode.offsetY;
        const clampedX = Math.round(Math.max(16, Math.min(maxX, rawX)));
        const clampedY = Math.round(Math.max(58, Math.min(maxY, rawY)));
        onMoveAndPinNode(draggingNode.layer, draggingNode.nodeId, {
          x: clampedX,
          y: clampedY,
        });
      } else if (rubberDrag) {
        const endX = e.clientX - vpRect.left + vp.scrollLeft;
        const endY = e.clientY - vpRect.top + vp.scrollTop;
        setRubberDrag((prev) =>
          prev
            ? {
                ...prev,
                rubberBand: {
                  ...prev.rubberBand,
                  endX,
                  endY,
                },
              }
            : null
        );
      }
    };

    const handleMouseUp = () => {
      if (draggingNode) setDraggingNode(null);
      if (rubberDrag) {
        setRubberDrag(null);
        setDropHoverNodeId(null);
      }
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [draggingNode, rubberDrag, onMoveAndPinNode]);

  // 测量真实 DOM 端口圆点坐标（浏览器环境下精确对齐；SSR 下自动走 HyperEdgeSvgLayer 回退推导）
  useEffect(() => {
    if (typeof window === 'undefined') return undefined;
    const vp = viewportRef.current;
    if (!vp) return undefined;

    const measure = () => {
      const vpRect = vp.getBoundingClientRect();
      if (vpRect.width === 0 && vpRect.height === 0) return;

      const next: Record<string, Point2D> = {};
      const boxes: RouteBox[] = [];
      const nodeList =
        layer === 'PROJECT'
          ? projectGraph.stations
          : [
              ...(station?.spatialNodes ?? []),
              ...(ghostTransaction &&
              (!station || ghostTransaction.stationId === station.stationId)
                ? ghostTransaction.addedNodes
                : []),
            ];

      for (const n of nodeList) {
        const card = document.getElementById(`dom-node-${n.id}`)?.getBoundingClientRect();
        if (card) boxes.push({
          left: n.position.x, right: n.position.x + card.width,
          top: n.position.y, bottom: n.position.y + card.height,
        });
        const allPorts = [...n.inPorts, ...n.outPorts];
        for (const p of allPorts) {
          const portEl = document.getElementById(`port-${n.id}-${p.id}`);
          if (!portEl) continue;
          const pr = portEl.getBoundingClientRect();
          next[`${n.id}:${p.id}`] = {
            x: pr.left - vpRect.left + vp.scrollLeft + pr.width / 2,
            y: pr.top - vpRect.top + vp.scrollTop + pr.height / 2,
          };
        }
      }

      if (Object.keys(next).length > 0) {
        setMeasuredPorts((prev) => (areMeasuredPortsEqual(prev, next) ? prev : next));
      }
      setNodeBoxes((previous) => previous.length === boxes.length && previous.every((box, i) =>
        box.left === boxes[i].left && box.right === boxes[i].right &&
        box.top === boxes[i].top && box.bottom === boxes[i].bottom) ? previous : boxes);
    };

    const rafId = window.requestAnimationFrame(measure);
    window.addEventListener('resize', measure);
    return () => {
      window.cancelAnimationFrame(rafId);
      window.removeEventListener('resize', measure);
    };
  }, [layer, zoomScale, projectGraph, station, ghostTransaction, focusedStepNo, faultFlyActive, isZoomFlashing]);

  const beginNodeDrag = (
    e: React.MouseEvent,
    targetLayer: 'PROJECT' | 'STATION',
    nodeId: string,
    cardWidth: number
  ) => {
    if (e.button !== 0) return;
    const vp = viewportRef.current;
    const cardEl = e.currentTarget as HTMLElement;
    const cardRect = cardEl.getBoundingClientRect();
    const offsetX = vp ? e.clientX - cardRect.left : 24;
    const offsetY = vp ? e.clientY - cardRect.top : 16;

    onSelectEntity({
      kind: targetLayer === 'PROJECT' ? 'STATION' : 'NODE',
      id: nodeId,
    });
    setDraggingNode({
      layer: targetLayer,
      nodeId,
      startX: e.clientX,
      startY: e.clientY,
      offsetX,
      offsetY,
      cardWidth,
    });
  };

  const handleStartRubberWire = (
    e: React.MouseEvent,
    nodeId: string,
    portId: string,
    portType: 'SEQ' | 'GUARD',
    portLabel: string
  ) => {
    const vp = viewportRef.current;
    let startX = e.clientX;
    let startY = e.clientY;

    if (vp) {
      const vpRect = vp.getBoundingClientRect();
      const measured = measuredPorts[`${nodeId}:${portId}`];
      if (measured) {
        startX = measured.x;
        startY = measured.y;
      } else {
        startX = e.clientX - vpRect.left + vp.scrollLeft;
        startY = e.clientY - vpRect.top + vp.scrollTop;
      }
    }

    setRubberDrag({
      fromNodeId: nodeId,
      fromPortId: portId,
      portType,
      portLabel,
      rubberBand: {
        startX,
        startY,
        endX: startX,
        endY: startY,
      },
    });
  };

  const handleDropWireOnNode = (
    clientX: number,
    clientY: number,
    targetNode: SpatialInstanceNode
  ) => {
    if (!rubberDrag || rubberDrag.fromNodeId === targetNode.id) {
      setRubberDrag(null);
      setDropHoverNodeId(null);
      return;
    }

    const methods = getRadialMethodsForClass(targetNode.driverClass, targetNode);
    const source = rubberDrag;
    setRubberDrag(null);
    setDropHoverNodeId(null);

    if (methods.length === 0) return;

    setRadialContext({
      centerX: clientX,
      centerY: clientY,
      targetNode,
      methods,
      fromNodeId: source.fromNodeId,
      fromPortId: source.fromPortId,
      portType: source.portType,
      portLabel: source.portLabel,
    });
  };

  const handleSelectRadialMethod = (option: RadialMethodOption) => {
    if (!radialContext) return;
    onApplyRadialOption({
      fromNodeId: radialContext.fromNodeId,
      fromPortId: radialContext.fromPortId,
      portType: radialContext.portType,
      portLabel: radialContext.portLabel,
      targetNode: radialContext.targetNode,
      option,
    });
    setRadialContext(null);
  };

  const activeGhostNodes =
    layer === 'STATION' &&
    station &&
    ghostTransaction &&
    ghostTransaction.stationId === station.stationId
      ? ghostTransaction.addedNodes
      : [];

  const allL2Nodes: SpatialInstanceNode[] =
    layer === 'STATION' && station
      ? [...station.spatialNodes, ...activeGhostNodes]
      : [];
  const nodes = layer === 'PROJECT' ? projectGraph.stations : allL2Nodes;
  const diagramWidth = Math.max(0, ...nodes.map(({ position }) => position.x + (layer === 'PROJECT' ? 280 : 267)));
  const diagramHeight = Math.max(0, ...nodes.map(({ position }) => position.y + (layer === 'PROJECT' ? 150 : 190)));
  const projectView = layer === 'PROJECT' && !faultFlyActive;
  const showRelationDetails = projectView && (showAllRelations ||
    selectedEntity?.kind === 'STATION' || selectedEntity?.kind === 'L1_EDGE');
  const relatedEdges = showRelationDetails ? visibleProjectRelations(projectGraph, selectedEntity, showAllRelations) : [];
  const projectHeights = new Map(projectGraph.stations.map(({ id, position }, i) => {
    const box = layer === 'PROJECT' ? nodeBoxes[i] : undefined;
    return [id, box && box.left === position.x && box.top === position.y ? box.bottom - box.top : 138];
  }));
  const relatedStations = new Set(relatedEdges.flatMap(({ fromNode, toNode }) => [fromNode, toNode]));

  const activeStepObj =
    layer === 'STATION' && station && focusedStepNo !== null && !faultFlyActive
      ? station.temporalSteps.find((s) => s.stepNo === focusedStepNo) ?? null
      : null;

  const hasCollisionViolation = Boolean(verifierReport && !verifierReport.passed);
  const firstViolationMessage =
    verifierReport?.violations[0]?.message ??
    '检测到当前步序触发时缺少防撞护栏保护，存在机械干涉风险！';

  return (
    <div className="af5-stage-frame">
    <main
      ref={viewportRef}
      className={`af5-blueprint-canvas ${isZoomFlashing ? 'af5-zoom-flash' : ''}`}
      data-layer={layer}
      data-zoom-scale={zoomScale.toFixed(2)}
      onClick={() => {
        if (layer === 'PROJECT') setShowAllRelations(false);
        if (layer === 'STATION' && focusedStepNo !== null) onSelectStepNo?.(null);
        onSelectEntity(null);
      }}
    >
      {/* 顶部悬浮上下文与三段算法提示横幅 */}
      <div className="af5-hud">
        <div className="af5-hud-strip">
          <div className="af5-context-chip">
            <span
              className={`af5-mode-badge ${
                layer === 'PROJECT' ? 'af5-mode-badge--l1' : 'af5-mode-badge--l2'
              }`}
            >
              {layer === 'PROJECT' ? 'L1 产线复合总图' : 'L2 空间唯一实例网'}
            </span>
            <span className="af5-context-title">
              {layer === 'PROJECT'
                ? `${projectName ?? '工程'} · 双击进入工位`
                : station?.stationName ?? '未选择工站'}
            </span>
            <span className="af5-context-hint">
              {layer === 'PROJECT'
                ? '单击工位查看相关关系'
                : '从右侧 ● 端口按住拖向任意目标节点松手，即弹「工艺径向菜单」'}
            </span>
            <span className="af5-zoom-pill">
              {zoomScale.toFixed(2)}x ({layer === 'PROJECT' ? 'L1' : 'L2'})
            </span>
          </div>

          {projectView ? (
            <button type="button" className="af5-btn af5-show-relations" aria-pressed={showAllRelations}
              onClick={(event) => {
                event.stopPropagation();
                setShowAllRelations(!showAllRelations);
              }}>显示全部关系</button>
          ) : <div className="af5-legend-chip">
            <span className="af5-legend-item">
              <span className="af5-legend-line af5-legend-line--seq" />
              <span>步序超边</span>
            </span>
            <span className="af5-legend-item">
              <span className="af5-legend-line af5-legend-line--guard" />
              <span>永久护栏</span>
            </span>
            <span className="af5-legend-item">
              <span className="af5-legend-line af5-legend-line--ghost" />
              <span style={{ color: 'var(--af5-indigo)', fontWeight: 600 }}>AI 虚影预览</span>
            </span>
          </div>}
        </div>

        {layer === 'PROJECT' && onArrangeProjectStations && (
          <button type="button" className="af5-btn af5-arrange-stations" onClick={(event) => {
            event.stopPropagation();
            viewportRef.current?.scrollTo(0, 0);
            onArrangeProjectStations();
          }}>整理工位</button>
        )}
        {/* AI 虚影差分预览槽位 (由 Wave 3 Copilot GhostDiffBanner 传入) */}
        {ghostBannerSlot}

        {/* 算法二：静态符号验证碰撞拦截横幅 */}
        {hasCollisionViolation && (
          <div className="af5-banner af5-banner--collision" role="alert">
            <div className="af5-banner-body">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <path d="M12 3 4 7v5c0 5 3.4 8.7 8 9.9 4.6-1.2 8-4.9 8-9.9V7l-8-4Z" />
                <path d="M12 8v5" />
                <circle cx="12" cy="16" r="1" fill="currentColor" />
              </svg>
              <div>
                <div className="af5-banner-title">
                  静态符号验证拦截 (Symbolic BFS Reachability Violation)
                </div>
                <div className="af5-banner-desc">{firstViolationMessage}</div>
              </div>
            </div>
            {onAutoFixCollision && (
              <div className="af5-banner-actions">
                <button
                  type="button"
                  className="af5-banner-btn af5-banner-btn--white-amber"
                  onClick={(e) => {
                    e.stopPropagation();
                    onAutoFixCollision();
                  }}
                >
                  🛡️ 一键补齐防撞护栏
                </button>
              </div>
            )}
          </div>
        )}

        {/* 算法三：跨站最小证伪割集与三段式停机追光横幅 */}
        {faultFlyActive && (
          <div className="af5-banner af5-banner--fault" role="status">
            <div className="af5-banner-body">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <circle cx="12" cy="12" r="9" />
                <circle cx="12" cy="12" r="3" />
                <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
              </svg>
              <div>
                <div className="af5-banner-title">
                  <span className="af5-banner-tag">
                    {flyToStage?.stageTag ?? '跨站最小证伪割集追踪'}
                  </span>
                  <span>
                    {cutSetTrace
                      ? `表象：${cutSetTrace.blockedStationId}_${cutSetTrace.blockedNodeId} Step ${cutSetTrace.blockedStepNo} 卡死超时`
                      : '表象：ST20_X轴搬运伺服 Step 30 卡死超时 (阻断码 #0203)'}
                  </span>
                </div>
                <div className="af5-banner-desc">
                  {flyToStage?.description ??
                    cutSetTrace?.diagnosisSummary ??
                    '已剪枝健康护栏分支，正在沿唯一 FALSE 割集穿透工站边界...'}
                </div>
              </div>
            </div>
            <div className="af5-banner-actions">
              {onRepairRootCause && (
                <button
                  type="button"
                  className="af5-banner-btn af5-banner-btn--emerald"
                  onClick={(e) => {
                    e.stopPropagation();
                    onRepairRootCause();
                  }}
                >
                  {`模拟拧紧端子 ${cutSetTrace?.rootCabinetWireTag ?? 'X12:04'} (${
                    cutSetTrace?.rootPhysicalTerminal ?? '%I0.4'
                  }=1)`}
                </button>
              )}
              {onStopFaultFly && (
                <button
                  type="button"
                  className="af5-banner-btn af5-banner-btn--ghost"
                  onClick={(e) => {
                    e.stopPropagation();
                    onStopFaultFly();
                  }}
                >
                  退出追光
                </button>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="af5-diagram" style={{ width: diagramWidth, height: diagramHeight }}>
      {projectView && <ProjectRelationsLayer graph={projectGraph} heights={projectHeights}
        edges={relatedEdges} expanded={showRelationDetails} />}
      {/* SVG 超边、永久护栏、AI 虚影与橡皮筋拉线层 */}
      {(!projectView || rubberDrag) && <HyperEdgeSvgLayer
        layer={layer}
        projectGraph={projectView ? { ...projectGraph, edges: [] } : projectGraph}
        station={station}
        ghostTransaction={ghostTransaction}
        focusedStepNo={focusedStepNo}
        compactStationWires
        showStationWireLabels={showStationWireLabels}
        faultTrace={cutSetTrace}
        faultFlyActive={faultFlyActive}
        st10SensorHealthy={st10SensorHealthy}
        rubberBand={rubberDrag?.rubberBand ?? null}
        portPositions={measuredPorts}
        nodeBoxes={nodeBoxes}
        onSelectGuard={(guard) => onSelectEntity({ kind: 'GUARD', id: guard.id })}
        onSelectStep={(step) => {
          onSelectEntity({ kind: 'STEP', id: step.id });
          onSelectStepNo?.(focusedStepNo === step.stepNo ? null : step.stepNo);
        }}
        onSelectProjectEdge={(edge) => onSelectEntity({ kind: 'L1_EDGE', id: edge.id })}
        onDeleteGuard={onDeleteGuard}
        onDeleteStep={onDeleteStep}
        onDeleteProjectEdge={onDeleteProjectEdge}
      />}

      {/* 空间节点卡片层 (L1 复合工站 或 L2 唯一空间实例) */}
      <div className="af5-nodes-layer">
        {layer === 'PROJECT' &&
          projectGraph.stations.map((st: ProjectCompoundStation) => {
            const isSelected =
              selectedEntity?.kind === 'STATION' && selectedEntity.id === st.id;
            const isFaultStation =
              faultFlyActive &&
              !st10SensorHealthy &&
              (cutSetTrace
                ? cutSetTrace.rootCauseStationId === st.stationId
                : st.stationId === 'ST10');
            const isActiveHighlight = st.stationId === (station?.stationId ?? 'ST20');
            const isL1DropTarget = Boolean(
              rubberDrag && rubberDrag.fromNodeId !== st.id && dropHoverNodeId === st.id
            );

            const cardClasses = [
              'af5-spatial-node',
              'af5-compound-station',
              isSelected ? 'is-selected' : '',
              showRelationDetails && !showAllRelations && relatedStations.size > 0 &&
                !relatedStations.has(st.id) && !rubberDrag ? 'is-relation-context' : '',
              isFaultStation ? 'is-fault-root' : '',
              isL1DropTarget ? 'is-drop-target' : '',
            ]
              .filter(Boolean)
              .join(' ');

            return (
              <div
                key={st.id}
                id={`dom-node-${st.id}`}
                data-station-id={st.stationId}
                tabIndex={0}
                title="拖动调整位置，双击进入工位"
                className={cardClasses}
                style={{
                  left: `${st.position.x}px`,
                  top: `${st.position.y}px`,
                  width: '264px',
                }}
                onMouseDown={(e) => {
                  const target = e.target as HTMLElement | null;
                  if (
                    target &&
                    typeof target.closest === 'function' &&
                    (target.closest('.af5-port-socket') || target.closest('button'))
                  ) {
                    return;
                  }
                  beginNodeDrag(e, 'PROJECT', st.id, 264);
                }}
                onMouseEnter={() => {
                  if (rubberDrag && rubberDrag.fromNodeId !== st.id) {
                    setDropHoverNodeId(st.id);
                  }
                }}
                onMouseLeave={() => {
                  if (dropHoverNodeId === st.id) {
                    setDropHoverNodeId(null);
                  }
                }}
                onMouseUp={(e) => {
                  if (rubberDrag && rubberDrag.fromNodeId !== st.id) {
                    const targetInPort =
                      st.inPorts.find((p) => p.type === rubberDrag.portType) ?? st.inPorts[0];
                    if (targetInPort) {
                      e.stopPropagation();
                      onCreateProjectEdge?.({
                        fromNode: rubberDrag.fromNodeId,
                        fromPort: rubberDrag.fromPortId,
                        toNode: st.id,
                        toPort: targetInPort.id,
                        kind: rubberDrag.portType,
                        label:
                          rubberDrag.portType === 'GUARD'
                            ? '跨站安全护栏'
                            : '物流交接握手',
                      });
                    }
                    setRubberDrag(null);
                    setDropHoverNodeId(null);
                  }
                }}
                onClick={(e) => {
                  e.stopPropagation();
                  onSelectEntity({ kind: 'STATION', id: st.id });
                }}
                onDoubleClick={(e) => {
                  e.stopPropagation();
                  if ((e.target as Element | null)?.closest('button, .af5-port-socket')) return;
                  onSwitchLayer('STATION', st.stationId);
                }}
                onKeyDown={(e) => {
                  if (e.target !== e.currentTarget) return;
                  if (e.key === 'Enter') onSwitchLayer('STATION', st.stationId);
                  if (e.key === ' ') {
                    e.preventDefault();
                    onSelectEntity({ kind: 'STATION', id: st.id });
                  }
                }}
              >
                <div
                  className={`af5-node-header ${
                    isActiveHighlight ? 'af5-node-header--l1-active' : 'af5-node-header--ink'
                  }`}
                >
                  <span className="af5-node-title">{st.title}</span>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0 }}>
                    {onCopyProjectStation && (
                      <button
                        type="button"
                        className="af5-btn af5-station-copy"
                        aria-label={`复制工位 ${st.title}`}
                        onDoubleClick={(event) => event.stopPropagation()}
                        onClick={(event) => {
                          event.stopPropagation();
                          onCopyProjectStation(st);
                        }}
                      >
                        复制
                      </button>
                    )}
                    {onDeleteProjectStation && (
                      <button
                        type="button"
                        title="删除该工站及其跨站连线"
                        aria-label={`删除工站 ${st.title}`}
                        data-testid={`canvas-delete-station-${st.id}`}
                        onMouseDown={(e) => e.stopPropagation()}
                        onClick={(e) => {
                          e.stopPropagation();
                          onDeleteProjectStation(st.id);
                        }}
                        style={{
                          padding: '0 5px',
                          height: 18,
                          borderRadius: 4,
                          border: '1px solid rgba(255,255,255,0.38)',
                          background: 'rgba(220, 38, 38, 0.88)',
                          color: '#FFFFFF',
                          fontSize: 10,
                          fontWeight: 700,
                          lineHeight: '16px',
                          cursor: 'pointer',
                        }}
                      >
                        ✕
                      </button>
                    )}
                  </div>
                </div>

                <div className="af5-station-instances">
                  <div className="af5-station-instances-eyebrow">{st.kind === 'LOGIC' ? '虚拟逻辑工位' : '实体工位'}</div>
                  {st.instanceSummaries.map((summary) => (
                    <div key={summary} className="af5-station-instance-line">
                      {`• ${summary}`}
                    </div>
                  ))}
                </div>

                <div className="af5-node-ports">
                  {st.inPorts.map((port) => (
                    <div key={port.id} className="af5-port-row">
                      <div
                        id={`port-${st.id}-${port.id}`}
                        className={`af5-port-socket af5-port-socket--in ${
                          port.type === 'GUARD' ? 'is-guard' : 'is-seq-in'
                        }`}
                      />
                      <span
                        className={`af5-port-label ${
                          port.type === 'GUARD' ? 'is-guard' : ''
                        }`}
                      >
                        {port.label}
                      </span>
                    </div>
                  ))}
                  {st.inPorts.length > 0 && st.outPorts.length > 0 && (
                    <div className="af5-ports-divider" />
                  )}
                  {st.outPorts.map((port) => (
                    <div key={port.id} className="af5-port-row af5-port-row--out">
                      <span
                        className={`af5-port-label ${
                          port.type === 'GUARD' ? 'is-guard' : ''
                        }`}
                      >
                        {port.label}
                      </span>
                      <div
                        id={`port-${st.id}-${port.id}`}
                        data-port-id={port.id}
                        data-port-role="out"
                        title="按住拖向其他工站可建立跨站连线"
                        className={`af5-port-socket af5-port-socket--out ${
                          isFaultStation && port.isFaultLeaf
                            ? 'is-fault-leaf'
                            : port.type === 'GUARD'
                              ? 'is-guard'
                              : 'is-seq-out'
                        }`}
                        onMouseDown={(e) => {
                          e.stopPropagation();
                          e.preventDefault();
                          handleStartRubberWire(e, st.id, port.id, port.type, port.label);
                        }}
                      />
                    </div>
                  ))}
                </div>
              </div>
            );
          })}

        {layer === 'STATION' &&
          station &&
          allL2Nodes.map((node) => {
            const isGhost = activeGhostNodes.some((gn) => gn.id === node.id);
            const invokeCount = station.temporalSteps.filter((step) =>
              step.invocations.some((inv) => inv.targetNodeId === node.id)
            ).length;

            const matchingInv = activeStepObj?.invocations.find(
              (inv) => inv.targetNodeId === node.id
            );
            const isTarget = Boolean(matchingInv);
            const isSource = activeStepObj?.fromNode === node.id;
            const isGuardSource = Boolean(
              activeStepObj &&
                station.guardEdges.some(
                  (g) =>
                    g.fromNode === node.id &&
                    activeStepObj.invocations.some((inv) => inv.targetNodeId === g.toNode)
                )
            );
            const isDimmed = Boolean(
              activeStepObj && !isTarget && !isSource && !isGuardSource
            );
            const isFaultRoot = Boolean(
              faultFlyActive &&
                !st10SensorHealthy &&
                (node.isPhysicalRootCause || cutSetTrace?.rootCauseNodeId === node.id)
            );

            return (
              <SpatialNodeCard
                key={node.id}
                node={node}
                invokeCount={invokeCount}
                isSelected={
                  selectedEntity?.kind === 'NODE' && selectedEntity.id === node.id
                }
                isDimmed={isDimmed}
                isActiveStep={isTarget}
                activeStepBanner={
                  showStationWireLabels && matchingInv && activeStepObj
                    ? {
                        stepNo: activeStepObj.stepNo,
                        actionLabel: matchingInv.actionLabel,
                      }
                    : null
                }
                isDropTargetHover={dropHoverNodeId === node.id}
                isFaultRoot={isFaultRoot}
                isRubberDragActive={
                  Boolean(rubberDrag) && rubberDrag?.fromNodeId !== node.id
                }
                isGhostNode={isGhost}
                onMouseDownMove={(e, target) =>
                  beginNodeDrag(e, 'STATION', target.id, 252)
                }
                onStartRubberWire={handleStartRubberWire}
                onDropWireOnNode={handleDropWireOnNode}
                onHoverDropTarget={(hoveredId) => setDropHoverNodeId(hoveredId)}
                onSelect={(nodeId) => onSelectEntity({ kind: 'NODE', id: nodeId })}
                onOpen={onOpenNode}
                onDelete={onDeleteNode}
              />
            );
          })}
      </div>

      </div>
      {/* 拉线松手即弹「极坐标工艺径向菜单」 */}
      <RadialCraftMenu
        isOpen={Boolean(radialContext)}
        centerX={radialContext?.centerX ?? 0}
        centerY={radialContext?.centerY ?? 0}
        targetNode={radialContext?.targetNode ?? null}
        methods={radialContext?.methods ?? []}
        onSelectMethod={handleSelectRadialMethod}
        onClose={() => setRadialContext(null)}
      />
    </main>
    {showRelationDetails && <ProjectRelationDetails graph={projectGraph} edges={relatedEdges}
      selected={selectedEntity} all={showAllRelations} onSelect={onSelectEntity} />}
    </div>
  );
};
