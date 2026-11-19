import React from 'react';
import type { SpatialInstanceNode, SpatialNodeTheme } from '../../core/ir/afHyperGraph.types';
import { cmProfiles } from '../../core/ir/fieldIo';

export interface SpatialNodeCardProps {
  node: SpatialInstanceNode;
  invokeCount: number;
  isSelected: boolean;
  isDimmed: boolean;
  isActiveStep: boolean;
  activeStepBanner?: { stepNo: number; actionLabel: string } | null;
  isDropTargetHover: boolean;
  isFaultRoot: boolean;
  isRubberDragActive: boolean;
  isGhostNode?: boolean;
  onMouseDownMove: (e: React.MouseEvent, node: SpatialInstanceNode) => void;
  onStartRubberWire: (
    e: React.MouseEvent,
    nodeId: string,
    portId: string,
    portType: 'SEQ' | 'GUARD',
    portLabel: string
  ) => void;
  onDropWireOnNode: (clientX: number, clientY: number, targetNode: SpatialInstanceNode) => void;
  onHoverDropTarget?: (nodeId: string | null) => void;
  onSelect?: (nodeId: string) => void;
  onOpen?: (nodeId: string) => void;
  onDelete?: (nodeId: string) => void;
}

export const SPATIAL_NODE_CARD_WIDTH = 252;

function resolveTheme(node: SpatialInstanceNode): SpatialNodeTheme {
  if (node.role !== 'ACTUATOR') return 'ink';
  return node.theme ?? 'klein';
}

function formatCohesiveIoFooter(node: SpatialInstanceNode, isFaultRoot: boolean): string | null {
  if (isFaultRoot) {
    const terminalParts: string[] = [];
    if (node.cohesiveIoMap?.diHome) terminalParts.push(node.cohesiveIoMap.diHome);
    if (node.cohesiveIoMap?.cabinetTerminal) {
      terminalParts.push(`端子 ${node.cohesiveIoMap.cabinetTerminal}`);
    }
    const suffix = terminalParts.length > 0 ? ` (${terminalParts.join(' · ')})` : '';
    return `🚨 故障端子脱落${suffix}`;
  }

  if (node.ioSummaryText) return node.ioSummaryText;

  if (node.cmProfile) {
    const required = cmProfiles[node.cmProfile].ports.filter((port) => !port.optional);
    return required.length ? `CM I/O ${required.filter((port) => node.fieldBindings?.[port.id]).length}/${required.length} 已绑定` : '通讯接口待定义';
  }
  const entries = Object.entries(node.cohesiveIoMap ?? {});
  if (entries.length === 0) return null;
  return entries.map(([k, v]) => `${k}: ${v || '待绑定'}`).join(' · ');
}

export const SpatialNodeCard: React.FC<SpatialNodeCardProps> = ({
  node,
  invokeCount,
  isSelected,
  isDimmed,
  isActiveStep,
  activeStepBanner,
  isDropTargetHover,
  isFaultRoot,
  isRubberDragActive,
  isGhostNode = false,
  onMouseDownMove,
  onStartRubberWire,
  onDropWireOnNode,
  onHoverDropTarget,
  onSelect,
  onOpen,
  onDelete,
}) => {
  const theme = resolveTheme(node);
  const ioFooterText = formatCohesiveIoFooter(node, isFaultRoot);
  const canAcceptWireDrop = isRubberDragActive && node.role !== 'BOUNDARY_IN';

  const cardClasses = [
    'af5-spatial-node',
    isSelected ? 'is-selected' : '',
    isDimmed ? 'is-dimmed' : '',
    isActiveStep ? 'is-active-step' : '',
    isDropTargetHover ? 'is-drop-hover' : '',
    isFaultRoot ? 'is-fault-root' : '',
    isGhostNode ? 'is-ghost-node' : '',
  ]
    .filter(Boolean)
    .join(' ');

  const handleMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement | null;
    if (target && typeof target.closest === 'function' && target.closest('.af5-port-socket')) {
      return;
    }
    onMouseDownMove(e, node);
  };

  const handleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    e.stopPropagation();
    onSelect?.(node.id);
  };

  const handleMouseEnter = () => {
    if (canAcceptWireDrop) {
      onHoverDropTarget?.(node.id);
    }
  };

  const handleMouseLeave = () => {
    if (isRubberDragActive) {
      onHoverDropTarget?.(null);
    }
  };

  const handleMouseUp = (e: React.MouseEvent<HTMLDivElement>) => {
    if (canAcceptWireDrop) {
      e.stopPropagation();
      onHoverDropTarget?.(null);
      onDropWireOnNode(e.clientX, e.clientY, node);
    }
  };

  return (
    <div
      id={`dom-node-${node.id}`}
      data-node-id={node.id}
      data-driver-class={node.driverClass}
      data-cm-profile={node.cmProfile}
      tabIndex={0}
      title="拖动调整位置，双击查看属性"
      className={cardClasses}
      style={{
        left: `${node.position.x}px`,
        top: `${node.position.y}px`,
        width: `${SPATIAL_NODE_CARD_WIDTH}px`,
      }}
      onMouseDown={handleMouseDown}
      onClick={handleClick}
      onDoubleClick={(event) => {
        event.stopPropagation();
        if (!(event.target as Element | null)?.closest('button, .af5-port-socket')) {
          onOpen?.(node.id);
        }
      }}
      onKeyDown={(event) => {
        if (event.key === 'Enter' && event.target === event.currentTarget) {
          onOpen?.(node.id);
        }
      }}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      onMouseUp={handleMouseUp}
    >
      {/* 母版色标头 + isPinned 图钉标记 + driverClass 徽章 */}
      <div className={`af5-node-header af5-node-header--${theme}`}>
        <div className="af5-node-title-group">
          <span className="af5-node-title">{node.title}</span>
          {node.isPinned && (
            <span
              className="af5-pin-badge"
              title="锚点已锁定：AI 增量排版时零位移"
              aria-label="已锁定锚点"
            >
              <svg width="11" height="11" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
                <path d="M9.828 1.5a.75.75 0 0 1 1.06 0l3.612 3.612a.75.75 0 0 1-.27 1.236l-2.392.86-1.888 1.888.452 2.41a.75.75 0 0 1-1.268.672L6.682 9.726 3.03 13.38a.75.75 0 1 1-1.06-1.06l3.653-3.653L3.17 6.215a.75.75 0 0 1 .672-1.268l2.41.452 1.888-1.888.86-2.392a.75.75 0 0 1 .828-.489Z" />
              </svg>
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0 }}>
          <span className={`af5-class-pill af5-class-pill--${theme}`} title={node.driverClass}>
            {node.role === 'ACTUATOR' ? node.driverClass : '工站边界'}
          </span>
          {onDelete && (
            <button
              type="button"
              title="删除此节点及其连线"
              aria-label={`删除节点 ${node.title}`}
              data-testid={`canvas-delete-node-${node.id}`}
              onMouseDown={(e) => e.stopPropagation()}
              onClick={(e) => {
                e.stopPropagation();
                onDelete(node.id);
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

      {/* 实例 DB 与多拍复用计数 */}
      <div className="af5-node-meta">
        <span className="af5-node-db">
          DB: <strong>{node.instanceDb}</strong>
        </span>
        {node.role === 'ACTUATOR' && (
          <span className="af5-reuse-pill" title="唯一空间实例被多拍步序复用">
            {invokeCount}拍复用
          </span>
        )}
      </div>

      {/* 单拍活跃执行横幅 */}
      {activeStepBanner && (
        <div className="af5-node-banner" data-active-step={activeStepBanner.stepNo}>
          <svg width="11" height="11" viewBox="0 0 16 16" fill="#FDE68A" aria-hidden="true">
            <path d="M9.2 1.2a.5.5 0 0 1 .46.69L8.1 6.2h4.15a.5.5 0 0 1 .4.81l-6.1 7.8a.5.5 0 0 1-.87-.46L7.3 9.8H3.75a.5.5 0 0 1-.4-.8l5.85-7.8Z" />
          </svg>
          <span className="af5-node-banner-text">
            {`S${activeStepBanner.stepNo} · 当前工步 · ${activeStepBanner.actionLabel}`}
          </span>
        </div>
      )}

      {/* 输入与输出端口槽 */}
      <div className="af5-node-ports">
        <div className="af5-node-port-group">
        {node.inPorts.map((port) => (
          <div key={port.id} className="af5-port-row">
            <div
              id={`port-${node.id}-${port.id}`}
              data-port-id={port.id}
              data-port-dir="in"
              data-port-type={port.type}
              className={`af5-port-socket af5-port-socket--in ${
                port.type === 'GUARD' ? 'is-guard' : 'is-seq-in'
              }`}
            />
            <span title={port.label} className={`af5-port-label ${port.type === 'GUARD' ? 'is-guard' : ''}`}>
              {port.label}
            </span>
          </div>
        ))}
        </div>

        {!node.cmProfile && node.inPorts.length > 0 && node.outPorts.length > 0 && (
          <div className="af5-ports-divider" />
        )}

        <div className="af5-node-port-group">
        {node.outPorts.map((port) => {
          const isFaultDot = isFaultRoot && Boolean(port.isFaultLeaf);
          const socketKindClass = isFaultDot
            ? 'is-fault-leaf'
            : port.type === 'GUARD'
              ? 'is-guard'
              : 'is-seq-out';
          return (
            <div key={port.id} className="af5-port-row af5-port-row--out">
              <span title={port.label} className={`af5-port-label ${port.type === 'GUARD' ? 'is-guard' : ''}`}>
                {port.label}
              </span>
              <div
                id={`port-${node.id}-${port.id}`}
                data-port-id={port.id}
                data-port-dir="out"
                data-port-type={port.type}
                title="按住拖向任意目标节点卡片松手，弹出工艺径向菜单"
                className={`af5-port-socket af5-port-socket--out ${socketKindClass}`}
                onMouseDown={(e) => {
                  e.stopPropagation();
                  e.preventDefault();
                  onStartRubberWire(e, node.id, port.id, port.type, port.label);
                }}
              />
            </div>
          );
        })}
        </div>
      </div>

      {/* 底部内聚 IO / 故障根因告警 */}
      {ioFooterText && (
        <div
          className={`af5-node-io ${isFaultRoot ? 'is-fault' : ''}`}
          title={ioFooterText}
        >
          {ioFooterText}
        </div>
      )}
    </div>
  );
};
