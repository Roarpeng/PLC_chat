import type { SpatialPort } from './afHyperGraph.types';

export const stationBoundaryLabels = {
  request: '● 工位请求',
  permit: '🛡️ 外部安全许可',
  done: '▶ 工位完成',
  safe: '🛡️ 工位安全状态',
} as const;

const previousDefaults: Record<string, [previous: string, current: string]> = {
  OUT_PART_ARRIVED: ['● 托盘到位触发', stationBoundaryLabels.request],
  OUT_SAFE_IN: ['🛡️ 上游安全允许', stationBoundaryLabels.permit],
  IN_HANDOVER: ['▶ 放行下游握手', stationBoundaryLabels.done],
  IN_SAFE_OUT: ['🛡️ 放行安全确认', stationBoundaryLabels.safe],
};

export function refreshBoundaryPortLabel(port: SpatialPort): SpatialPort {
  const labels = previousDefaults[port.id];
  return labels && port.label === labels[0] ? { ...port, label: labels[1] } : port;
}
