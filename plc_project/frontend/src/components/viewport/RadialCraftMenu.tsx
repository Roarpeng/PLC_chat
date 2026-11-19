import React, { useEffect } from 'react';
import type {
  RadialMethodOption,
  SpatialInstanceNode,
} from '../../core/ir/afHyperGraph.types';

export interface RadialViewportSize {
  width: number;
  height: number;
}

export interface RadialMenuItemLayout {
  option: RadialMethodOption;
  index: number;
  angle: number;
  radius: number;
  offsetX: number;
  offsetY: number;
  x: number;
  y: number;
}

export interface RadialMenuLayout {
  centerX: number;
  centerY: number;
  radius: number;
  items: RadialMenuItemLayout[];
}

export interface RadialCraftMenuProps {
  isOpen: boolean;
  centerX: number;
  centerY: number;
  targetNode: SpatialInstanceNode | null;
  methods: RadialMethodOption[];
  onSelectMethod: (option: RadialMethodOption) => void;
  onClose: () => void;
}

/**
 * 极坐标计算「工艺径向菜单」各动作胶囊位置：
 * θ_i = -π/2 + 2πi / N, x = cos(θ_i) * R, y = sin(θ_i) * R (默认半径 R = 112px)
 */
export function computeRadialMenuItems(
  centerX: number,
  centerY: number,
  methods: RadialMethodOption[],
  radius = 112,
  viewportSize?: RadialViewportSize
): RadialMenuLayout {
  let safeCenterX = centerX;
  let safeCenterY = centerY;

  if (viewportSize) {
    const padX = Math.min(180, viewportSize.width / 2);
    const padY = Math.min(160, viewportSize.height / 2);
    safeCenterX = Math.max(padX, Math.min(viewportSize.width - padX, centerX));
    safeCenterY = Math.max(padY, Math.min(viewportSize.height - padY, centerY));
  }

  const count = methods.length;
  const items: RadialMenuItemLayout[] = methods.map((option, index) => {
    const angle = -Math.PI / 2 + (count > 0 ? (2 * Math.PI * index) / count : 0);
    const offsetX = Math.cos(angle) * radius;
    const offsetY = Math.sin(angle) * radius;
    return {
      option,
      index,
      angle,
      radius,
      offsetX,
      offsetY,
      x: safeCenterX + offsetX,
      y: safeCenterY + offsetY,
    };
  });

  return {
    centerX: safeCenterX,
    centerY: safeCenterY,
    radius,
    items,
  };
}

export const RadialCraftMenu: React.FC<RadialCraftMenuProps> = ({
  isOpen,
  centerX,
  centerY,
  targetNode,
  methods,
  onSelectMethod,
  onClose,
}) => {
  useEffect(() => {
    if (!isOpen || typeof window === 'undefined') return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen || !targetNode || methods.length === 0) {
    return null;
  }

  const viewportSize: RadialViewportSize | undefined =
    typeof window !== 'undefined'
      ? { width: window.innerWidth, height: window.innerHeight }
      : undefined;

  const layout = computeRadialMenuItems(centerX, centerY, methods, 112, viewportSize);

  return (
    <div
      className="af5-radial-overlay"
      role="dialog"
      aria-label={`工艺径向菜单 - ${targetNode.title}`}
      onClick={onClose}
    >
      <div
        className="af5-radial-bloom"
        style={{
          left: `${layout.centerX}px`,
          top: `${layout.centerY}px`,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="af5-radial-hub">
          <span className="af5-radial-hub-eyebrow">RADIAL CRAFT</span>
          <span className="af5-radial-hub-title">{targetNode.title}</span>
        </div>

        {layout.items.map((item) => (
          <button
            key={item.option.methodId}
            type="button"
            data-method-id={item.option.methodId}
            data-is-guard={item.option.isGuard ? 'true' : undefined}
            className={`af5-radial-pill ${item.option.isGuard ? 'is-guard' : ''}`}
            style={{
              transform: `translate(calc(-50% + ${item.offsetX}px), calc(-50% + ${item.offsetY}px))`,
            }}
            onClick={() => onSelectMethod(item.option)}
          >
            {item.option.label}
          </button>
        ))}
      </div>
    </div>
  );
};
