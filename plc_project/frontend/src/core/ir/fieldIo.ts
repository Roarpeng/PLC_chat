import type { AfStudioWorkspaceData, RadialMethodOption, SpatialInstanceNode, SpatialPort, StationHyperGraph } from './afHyperGraph.types';

export const fieldIoTypes = ['BOOL', 'BYTE', 'WORD', 'DWORD', 'INT', 'UINT', 'DINT', 'UDINT', 'REAL'] as const;
export type FieldIoType = typeof fieldIoTypes[number];
export type FieldIoDirection = 'INPUT' | 'OUTPUT';
export type CmDeviceProfile = 'Cylinder2Pos@1' | 'DigitalInput@1' | 'Robot6Axis@1'
  | 'ServoAxis@1' | 'Gripper@1' | 'Vacuum@1' | 'MotorStartStop@1';

export interface FieldIoPoint {
  id: string;
  name: string;
  address: string;
  type: FieldIoType;
}

interface CmPhysicalPort {
  id: string;
  label: string;
  direction: FieldIoDirection;
  type: FieldIoType;
  optional?: boolean;
}

interface CmProfileSpec {
  driver: SpatialInstanceNode['driverClass'];
  ports: readonly CmPhysicalPort[];
  homeState: string;
  actions: readonly RadialMethodOption[];
  feedback: readonly SpatialPort[];
  communicationPending?: boolean;
}

const di = (id: string, label: string, optional = false): CmPhysicalPort => ({ id, label, optional, direction: 'INPUT', type: 'BOOL' });
const dout = (id: string, label: string, optional = false): CmPhysicalPort => ({ id, label, optional, direction: 'OUTPUT', type: 'BOOL' });
const feedback = (id: string, label: string): SpatialPort => ({ id, label: `● ${label}`, type: 'SEQ' });
const action = (
  methodId: string, targetPortId: string, label: string, waitDescription: string,
  targetDiscreteState: string, feedbackMember: string, sclCommand: string,
): RadialMethodOption => ({ methodId, targetPortId, label, waitDescription, targetDiscreteState, feedbackMember, sclCommand });

export const cmProfiles: Record<CmDeviceProfile, CmProfileSpec> = {
  'Cylinder2Pos@1': {
    driver: 'FB_AF_Actuator2Pos',
    ports: [di('diHome', '缩回到位磁开'), di('diWork', '伸出到位磁开'), dout('doWork', '伸出阀输出'), dout('doHome', '缩回阀输出', true)],
    homeState: 'AtHome',
    actions: [
      action('ExtendWork', 'IN_EXTEND', '伸出', '伸出到位', 'AtWork', 'o_bAtWork', 'ExtendWork()'),
      action('RetractHome', 'IN_RETRACT', '缩回', '缩回到位', 'AtHome', 'o_bAtHome', 'RetractHome()'),
    ],
    feedback: [feedback('OUT_EXTENDED', '伸出到位'), feedback('OUT_RETRACTED', '缩回到位'),
      { id: 'OUT_AT_HOME', label: '🛡️ 原位安全状态', type: 'GUARD' }],
  },
  'DigitalInput@1': {
    driver: 'FB_AF_DigitalInput',
    ports: [di('diSignal', '传感器输入')],
    homeState: 'Off', actions: [],
    feedback: [feedback('OUT_ON', '检测到位'), feedback('OUT_OFF', '未检测到位')],
  },
  'ServoAxis@1': {
    driver: 'FB_AF_AxisMotion', communicationPending: true,
    ports: [di('diHomeLim', '原点限位', true), di('diPosLim', '正限位', true), di('diNegLim', '负限位', true)],
    homeState: 'AtHome',
    actions: [
      action('MoveHome', 'IN_HOME', '回原点', '回零完成', 'AtHome', 'o_bAtHome', 'MoveHome()'),
      action('MoveAbs', 'IN_POSITION', '绝对定位', '定位到位', 'AtTarget', 'o_bInPosition', 'MoveAbs(#TargetPosition)'),
      action('StopMotion', 'IN_STOP', '停止', '停止确认', 'Stopped', 'o_bStopped', 'Stop()'),
    ],
    feedback: [feedback('OUT_HOME', '回零完成'), feedback('OUT_POSITION', '定位到位'), feedback('OUT_STOPPED', '停止确认')],
  },
  'Gripper@1': {
    driver: 'FB_AF_Gripper',
    ports: [di('diClosed', '夹紧到位输入'), di('diOpened', '松开到位输入'),
      di('diPartPresent', '工件在位输入', true), dout('doClose', '夹紧阀输出'), dout('doOpen', '松开阀输出', true)],
    homeState: 'Opened',
    actions: [
      action('GripClose', 'IN_CLAMP', '夹紧', '夹紧到位', 'Closed', 'o_bClosed', 'CloseGrip()'),
      action('GripOpen', 'IN_RELEASE', '松开', '松开到位', 'Opened', 'o_bOpened', 'OpenGrip()'),
    ],
    feedback: [feedback('OUT_CLAMPED', '夹紧到位'), feedback('OUT_RELEASED', '松开到位'), feedback('OUT_PART_PRESENT', '工件在位（选配）')],
  },
  'Vacuum@1': {
    driver: 'FB_AF_Vacuum',
    ports: [di('diVacuumOk', '真空到位输入'), dout('doVacuum', '真空阀输出'), dout('doBlowOff', '破真空阀输出', true)],
    homeState: 'Released',
    actions: [
      action('VacuumOn', 'IN_VACUUM', '吸附', '真空到位', 'Holding', 'o_bVacuumOk', 'VacuumOn()'),
      action('VacuumRelease', 'IN_RELEASE', '释放', '真空解除确认', 'Released', 'o_bReleased', 'VacuumRelease()'),
    ],
    feedback: [feedback('OUT_VACUUM_OK', '真空到位'), feedback('OUT_RELEASED', '真空解除确认')],
  },
  'MotorStartStop@1': {
    driver: 'FB_AF_MotorStartStop',
    ports: [di('diRunning', '运行反馈输入'), di('diFault', '故障输入', true), dout('doRun', '启动输出')],
    homeState: 'Stopped',
    actions: [
      action('StartMotor', 'IN_START', '启动', '运行反馈', 'Running', 'o_bRunning', 'Start()'),
      action('StopMotor', 'IN_STOP', '停止', '停机反馈', 'Stopped', 'o_bStopped', 'Stop()'),
    ],
    feedback: [feedback('OUT_RUNNING', '运行反馈'), feedback('OUT_STOPPED', '停机反馈'), feedback('OUT_FAULT', '故障反馈')],
  },
  'Robot6Axis@1': {
    driver: 'FB_AF_Robot6Axis', communicationPending: true, ports: [], homeState: 'Idle',
    actions: [
      action('StartJob', 'IN_JOB_START', '启动作业请求', '作业完成应答', 'JobDone', 'o_bJobDone', 'StartJob(#JobId)'),
      action('StopJob', 'IN_JOB_STOP', '停止作业请求', '停止确认', 'Stopped', 'o_bStopped', 'StopJob()'),
    ],
    feedback: [feedback('OUT_READY', '机器人就绪'), feedback('OUT_BUSY', '作业运行中'),
      feedback('OUT_JOB_DONE', '作业完成应答'), feedback('OUT_STOPPED', '停止确认'), feedback('OUT_FAULT', '机器人故障')],
  },
};

export function defaultCmControl(profile: CmDeviceProfile) {
  const spec = cmProfiles[profile];
  const inPorts: SpatialPort[] = spec.actions.map(({ targetPortId, label }) => ({ id: targetPortId!, label: `▶ ${label}`, type: 'SEQ' }));
  if (inPorts.length) inPorts.push({ id: 'IN_GUARD', label: '🛡️ 动作许可', type: 'GUARD' });
  return {
    inPorts,
    outPorts: spec.feedback.map((port) => ({ ...port })),
    initialHomeState: spec.homeState,
    discreteStates: [...new Set([spec.homeState, ...spec.actions.map(({ targetDiscreteState }) => targetDiscreteState),
      ...(profile === 'DigitalInput@1' ? ['On'] : [])])],
  };
}

export function cmPresetWait(node: SpatialInstanceNode, preset?: RadialMethodOption): string {
  return `#${node.id}.${preset?.feedbackMember ?? 'o_bDone'}`;
}

const typeSize: Record<FieldIoType, number> = {
  BOOL: 1, BYTE: 8, WORD: 16, DWORD: 32, INT: 16, UINT: 16, DINT: 32, UDINT: 32, REAL: 32,
};

export function parseFieldAddress(value: string, type: FieldIoType) {
  const match = /^%?([IQ])([XBWD]?)(\d+)(?:\.([0-7]))?$/.exec(value.trim().toUpperCase());
  if (!match) return;
  const [, area, width, byteText, bitText] = match;
  const byte = Number(byteText);
  if (!Number.isSafeInteger(byte) || byte > Math.floor((Number.MAX_SAFE_INTEGER - 32) / 8)) return;
  const count = typeSize[type];
  const expectedWidth = count === 8 ? 'B' : count === 16 ? 'W' : 'D';
  if (type === 'BOOL' ? (width !== '' && width !== 'X') || bitText === undefined : width !== expectedWidth || bitText !== undefined) return;
  const start = byte * 8 + Number(bitText ?? 0);
  return {
    address: `%${area}${type === 'BOOL' ? `${byte}.${bitText}` : `${width}${byte}`}`,
    direction: (area === 'I' ? 'INPUT' : 'OUTPUT') as FieldIoDirection,
    start,
    end: start + count,
  };
}

export function fieldIoOwners(workspace: AfStudioWorkspaceData, pointId: string) {
  return Object.values(workspace.stationGraphs).flatMap((station) =>
    station.spatialNodes.flatMap((node) => Object.entries(node.fieldBindings ?? {})
      .filter(([, boundId]) => boundId === pointId)
      .map(([portId]) => ({ stationId: station.stationId, nodeId: node.id, portId, label: `${station.stationName} / ${node.title}` }))));
}

export function pointError(workspace: AfStudioWorkspaceData, draft: FieldIoPoint): string | undefined {
  if (!draft.name.trim()) return '请输入点位名称';
  const address = parseFieldAddress(draft.address, draft.type);
  if (!address) return '地址与数据类型不匹配。BOOL 示例 %I0.0，WORD 示例 %IW2';
  const previous = workspace.fieldIoPoints?.find((point) => point.id === draft.id);
  if (previous && fieldIoOwners(workspace, draft.id).length &&
    (previous.address !== address.address || previous.type !== draft.type)) return '请先解除设备绑定，再修改点位地址或类型';
  if (workspace.fieldIoPoints?.some((point) => {
    if (point.id === draft.id) return false;
    const other = parseFieldAddress(point.address, point.type);
    return other && address.direction === other.direction && address.start < other.end && address.end > other.start;
  })) return '该 PLC 地址与点表内已有地址重叠';
}

export function bindingError(
  workspace: AfStudioWorkspaceData, stationId: string, node: SpatialInstanceNode, portId: string, pointId: string,
): string | undefined {
  const port = node.cmProfile && cmProfiles[node.cmProfile].ports.find((candidate) => candidate.id === portId);
  if (!port) return '该设备端口不存在';
  if (!pointId) return;
  const point = workspace.fieldIoPoints?.find((candidate) => candidate.id === pointId);
  if (!point || point.type !== port.type || parseFieldAddress(point.address, point.type)?.direction !== port.direction) {
    return '点位的输入输出方向或数据类型与 CM 端口不匹配';
  }
  if (port.direction === 'OUTPUT' && fieldIoOwners(workspace, pointId).some((owner) =>
    owner.stationId !== stationId || owner.nodeId !== node.id || owner.portId !== portId,
  )) return '该输出点已被另一 CM 端口占用';
}

export function cmBindingStatus(station: StationHyperGraph): string | undefined {
  const managed = station.spatialNodes.filter((node) => node.cmProfile);
  const communicationPending = managed.find(({ cmProfile }) => cmProfiles[cmProfile!].communicationPending);
  if (communicationPending) return communicationPending.cmProfile === 'Robot6Axis@1' ? 'KUKA 通讯接口待定义' : '伺服驱动报文待定义';
  if (managed.some((node) => cmProfiles[node.cmProfile!].ports.some((port) => !port.optional && !node.fieldBindings?.[port.id]))) return '待绑定现场 I/O';
  if (managed.length) return 'CM 点表已配置，待 PLC 运行接线';
}
