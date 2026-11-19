import {
  emptyFlow,
  primarySteps,
  type Device,
  type Driver,
  type Edge,
  type Flow,
  type Hardware,
  type Interlock,
  type Node,
  type PortDefinition,
  type Signal,
  type SignalWire,
  type Station,
  type StationDesign,
} from '../../workbench/stationDesign';
import type {
  AfStudioWorkspaceData,
  CrossStationGuardRef,
  DriverMotherClass,
  ProjectCompoundEdge,
  ProjectCompoundStation,
  SafetyGuardEdge,
  SpatialInstanceNode,
  SpatialPort,
  StationHyperGraph,
  TemporalStepHyperEdge,
  TemporalStepInvocation,
} from './afHyperGraph.types';
import { MOTHER_CLASS_REGISTRY } from './motherClassRegistry';

const DRIVER_TO_MOTHER_CLASS: Record<string, DriverMotherClass> = {
  servo: 'FB_AF_AxisMotion',
  servo_to: 'FB_AF_AxisMotion',
  vfd: 'FB_AF_AxisMotion',
  stepper: 'FB_AF_AxisMotion',
  FB_AF_AxisMotion: 'FB_AF_AxisMotion',

  cylinder: 'FB_AF_Actuator2Pos',
  single_cylinder: 'FB_AF_Actuator2Pos',
  rotary_cylinder: 'FB_AF_Actuator2Pos',
  electric_cylinder: 'FB_AF_Actuator2Pos',
  solenoid: 'FB_AF_Actuator2Pos',
  motor: 'FB_AF_Actuator2Pos',
  conveyor: 'FB_AF_Actuator2Pos',
  roller_conveyor: 'FB_AF_Actuator2Pos',
  index_table: 'FB_AF_Actuator2Pos',
  FB_AF_Actuator2Pos: 'FB_AF_Actuator2Pos',

  pneumatic_gripper: 'FB_AF_Gripper',
  electric_gripper: 'FB_AF_Gripper',
  vacuum: 'FB_AF_Gripper',
  FB_AF_Gripper: 'FB_AF_Gripper',
  FB_AF_Vacuum: 'FB_AF_Vacuum',
  FB_AF_MotorStartStop: 'FB_AF_MotorStartStop',

  vision: 'FB_AF_VisionSensor',
  scanner: 'FB_AF_VisionSensor',
  rfid: 'FB_AF_VisionSensor',
  sensor: 'FB_AF_VisionSensor',
  photoelectric: 'FB_AF_VisionSensor',
  proximity: 'FB_AF_VisionSensor',
  reed: 'FB_AF_VisionSensor',
  limit: 'FB_AF_VisionSensor',
  pressure_switch: 'FB_AF_VisionSensor',
  vacuum_switch: 'FB_AF_VisionSensor',
  analog_sensor: 'FB_AF_VisionSensor',
  encoder: 'FB_AF_VisionSensor',
  FB_AF_VisionSensor: 'FB_AF_VisionSensor',
  digital_input: 'FB_AF_DigitalInput',
  FB_AF_DigitalInput: 'FB_AF_DigitalInput',
  robot: 'FB_AF_Robot6Axis',
  FB_AF_Robot6Axis: 'FB_AF_Robot6Axis',
};

const MOTHER_CLASS_TO_DRIVER: Record<DriverMotherClass, Driver> = {
  FB_AF_AxisMotion: 'servo',
  FB_AF_Actuator2Pos: 'cylinder',
  FB_AF_Gripper: 'pneumatic_gripper',
  FB_AF_Vacuum: 'vacuum',
  FB_AF_MotorStartStop: 'motor',
  FB_AF_VisionSensor: 'vision',
  FB_AF_DigitalInput: 'digital_input',
  FB_AF_Robot6Axis: 'robot',
  STATION_INPUT_PORT: 'interface',
  STATION_OUTPUT_PORT: 'interface',
};

const ACTION_MAP: Record<string, { methodId: string; label: string; targetState: string; scl: string }> = {
  extend: { methodId: 'ExtendWork', label: '伸出下压', targetState: 'AtWork', scl: 'ExtendWork()' },
  retract: { methodId: 'RetractHome', label: '缩回原位', targetState: 'AtHome', scl: 'RetractHome()' },
  clamp: { methodId: 'GripClose', label: '闭合夹紧', targetState: 'Closed', scl: 'CloseGrip()' },
  release: { methodId: 'GripOpen', label: '张开释放', targetState: 'Opened', scl: 'OpenGrip()' },
  work: { methodId: 'MoveWork', label: '移动至工作位', targetState: 'Pos_Press_245', scl: 'MoveAbs(245.0)' },
  home: { methodId: 'MoveHome', label: '回待机原位', targetState: 'Pos_Home_0', scl: 'MoveAbs(0.0)' },
  stop: { methodId: 'StopMotion', label: '撤销运动请求', targetState: 'Pos_Home_0', scl: 'Stop()' },
  grip: { methodId: 'GripClose', label: '吸附夹持', targetState: 'Closed', scl: 'CloseGrip()' },
  start: { methodId: 'ExtendWork', label: '启动运行', targetState: 'AtWork', scl: 'Start()' },
  open: { methodId: 'ExtendWork', label: '通电开启', targetState: 'AtWork', scl: 'ExtendWork()' },
  close: { methodId: 'RetractHome', label: '断电关闭', targetState: 'AtHome', scl: 'RetractHome()' },
};

function sanitizeIdent(raw: string): string {
  const cleaned = raw.replace(/[^A-Za-z0-9_]/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '');
  return cleaned || 'Inst';
}

function normalizeDiagHex(raw?: string | null, fallbackIdx = 1): string {
  if (raw && raw.trim()) {
    const trimmed = raw.trim();
    if (/^16#[0-9A-Fa-f]+$/.test(trimmed)) return trimmed.toUpperCase().replace('16#', '16#');
    if (/^#[0-9A-Fa-f]+$/.test(trimmed)) return `16#${trimmed.slice(1).toUpperCase()}`;
    return trimmed;
  }
  return `16#${(0x0200 + fallbackIdx).toString(16).padStart(4, '0').toUpperCase()}`;
}

function toBlockCode(diagCodeHex: string): string {
  if (diagCodeHex.startsWith('16#')) return `#${diagCodeHex.slice(3)}`;
  if (diagCodeHex.startsWith('#')) return diagCodeHex;
  return `#${diagCodeHex}`;
}

export function mapDriverToMotherClass(driver: Driver): DriverMotherClass {
  return DRIVER_TO_MOTHER_CLASS[driver] ?? 'FB_AF_Actuator2Pos';
}

export function mapMotherClassToDriver(driverClass: DriverMotherClass): Driver {
  return MOTHER_CLASS_TO_DRIVER[driverClass] ?? 'cylinder';
}

function buildCohesiveIoMap(device: Device, signalsById: Map<string, Signal>): Record<string, string> {
  const ioMap: Record<string, string> = {};
  for (const [portKey, signalId] of Object.entries(device.bindings ?? {})) {
    const sig = signalsById.get(signalId);
    ioMap[portKey] = sig?.address || signalId;
  }
  return ioMap;
}

function resolveCrossStationSource(
  design: StationDesign,
  targetStation: Station,
  interlock: Interlock,
  signalsById: Map<string, Signal>
): CrossStationGuardRef | null {
  const stationsById = new Map(design.stations.map((s) => [s.id, s]));

  if (interlock.device_id && interlock.port && interlock.source_station_id && interlock.source_station_id !== targetStation.id) {
    const owner = stationsById.get(interlock.source_station_id);
    const dev = owner?.devices.find((d) => d.id === interlock.device_id);
    const sig = dev ? signalsById.get(dev.bindings[interlock.port] ?? '') : undefined;
    return {
      upstreamStationId: interlock.source_station_id,
      upstreamInstanceId: dev?.id ?? interlock.device_id,
      upstreamPortId: `OUT_${interlock.port}`,
      physicalTerminal: sig?.address ?? '',
      cabinetWireTag: sig?.module_id ? `${sig.module_id}:${sig.address}` : '',
    };
  }

  if (!interlock.public_port) return null;

  const targetL1Node = design.flow.nodes.find(
    (n) => (n.kind === 'station' || n.kind === 'handoff') && n.station_ids[0] === targetStation.id
  );
  let l1Wire = targetL1Node
    ? design.flow.wires?.find((w) => w.to_id === targetL1Node.id && w.to_port === interlock.public_port)
    : undefined;
  if (!l1Wire && targetL1Node && interlock.source_station_id) {
    const sourceL1Candidates = new Set(
      design.flow.nodes
        .filter((n) => (n.kind === 'station' || n.kind === 'handoff') && n.station_ids[0] === interlock.source_station_id)
        .map((n) => n.id)
    );
    l1Wire = design.flow.wires?.find(
      (w) => w.to_id === targetL1Node.id && sourceL1Candidates.has(w.from_id)
    );
  }
  const sourceL1Node = l1Wire ? design.flow.nodes.find((n) => n.id === l1Wire.from_id) : undefined;
  const upstreamStationId = sourceL1Node?.station_ids[0] ?? interlock.source_station_id ?? '';
  const owner = upstreamStationId ? stationsById.get(upstreamStationId) : undefined;

  if (!owner) {
    return upstreamStationId
      ? {
          upstreamStationId,
          upstreamInstanceId: `BOUND_OUT_${upstreamStationId}`,
          physicalTerminal: '',
          cabinetWireTag: '',
          l1EdgeId: l1Wire?.id,
        }
      : null;
  }

  const iface = owner.flow.nodes.find((n) => n.kind === 'interface');
  const feedWire =
    iface && l1Wire
      ? owner.flow.wires?.find((w) => w.to_id === iface.id && w.to_port === l1Wire.from_port)
      : undefined;

  if (feedWire) {
    const feederNode = owner.flow.nodes.find((n) => n.id === feedWire.from_id);
    let deviceId = feederNode?.device_id ?? null;
    if (!deviceId && feederNode?.kind === 'action' && feederNode.actions?.length === 1) {
      deviceId = feederNode.actions[0].device_id;
    }
    const dev = owner.devices.find((d) => d.id === deviceId);
    const rawPort = feedWire.from_port.startsWith('fb_') ? feedWire.from_port.slice(3) : feedWire.from_port;
    const sig = dev ? signalsById.get(dev.bindings[rawPort] ?? '') : undefined;
    if (dev) {
      return {
        upstreamStationId: owner.id,
        upstreamInstanceId: dev.id,
        upstreamPortId: `OUT_${rawPort}`,
        physicalTerminal: sig?.address ?? '',
        cabinetWireTag: sig?.module_id ? `${sig.module_id}:${sig.address}` : '',
        l1EdgeId: l1Wire?.id,
      };
    }
  }

  return {
    upstreamStationId: owner.id,
    upstreamInstanceId: owner.devices[0]?.id ?? `BOUND_OUT_${owner.id}`,
    upstreamPortId: l1Wire ? `OUT_${l1Wire.from_port}` : undefined,
    physicalTerminal: '',
    cabinetWireTag: '',
    l1EdgeId: l1Wire?.id,
  };
}

function mapActionToInvocation(
  action: { device_id: string; action_id: string },
  node: Node,
  spatialById: Map<string, SpatialInstanceNode>
): TemporalStepInvocation {
  const targetNode = spatialById.get(action.device_id);
  const preset = ACTION_MAP[action.action_id];
  const dbName = targetNode?.instanceDb ?? action.device_id;
  const methodId = preset?.methodId ?? sanitizeIdent(action.action_id);
  const actionLabel = preset?.label ?? (node.name || action.action_id);
  const sclCmd = preset?.scl ?? `${methodId}()`;
  const targetDiscreteState =
    preset?.targetState ??
    targetNode?.discreteStates.find((s) => s.toLowerCase().includes(action.action_id.toLowerCase())) ??
    targetNode?.discreteStates[targetNode.discreteStates.length - 1] ??
    'AtWork';

  const waitDesc = node.completion?.length
    ? node.completion.map((c) => `${c.port}=${String(c.value)}`).join(' & ')
    : `${actionLabel} 到位`;

  const waitScl = node.completion?.length
    ? node.completion
        .map((c) => `${c.value ? '' : 'NOT '}"${dbName}".fb_${sanitizeIdent(c.port)}`)
        .join(' AND ')
    : `"${dbName}".o_bDone`;

  return {
    targetNodeId: action.device_id,
    targetPortId: 'IN_EXEC',
    methodId,
    actionLabel,
    targetDiscreteState,
    sclStatement: `#${dbName}.${sclCmd};`,
    waitPredicateScl: waitScl,
    waitDescription: waitDesc,
  };
}

function convertStationToHyperGraph(
  design: StationDesign,
  station: Station,
  signalsById: Map<string, Signal>
): StationHyperGraph {
  const boundInId = `BOUND_IN_${station.id}`;
  const boundOutId = `BOUND_OUT_${station.id}`;

  const inputPublicPorts = (station.public_ports ?? []).filter((p) => p.direction === 'input');
  const outputPublicPorts = (station.public_ports ?? []).filter((p) => p.direction === 'output');

  const boundInOutPorts: SpatialPort[] = [
    { id: 'OUT_PART_ARRIVED', label: '● 工位触发启动', type: 'SEQ' },
    ...inputPublicPorts.map((p) => ({
      id: `OUT_${p.id}`,
      label: `🛡️ ${p.name}`,
      type: 'GUARD' as const,
      isFaultLeaf: p.type === 'BOOL',
    })),
  ];

  const boundInNode: SpatialInstanceNode = {
    id: boundInId,
    role: 'BOUNDARY_IN',
    title: `${station.name} · 左输入边界`,
    driverClass: 'STATION_INPUT_PORT',
    instanceDb: `映射自 L1 (${station.id})`,
    position: { x: 40, y: 140 },
    isPinned: true,
    discreteStates: ['WaitingPart', 'PartArrived'],
    initialHomeState: 'WaitingPart',
    cohesiveIoMap: {},
    theme: 'ink',
    inPorts: [],
    outPorts: boundInOutPorts,
  };

  const deviceNodes: SpatialInstanceNode[] = station.devices.map((dev, idx) => {
    const driverClass = mapDriverToMotherClass(dev.driver);
    const spec = MOTHER_CLASS_REGISTRY[driverClass];
    const flowHintNode =
      station.flow.nodes.find((n) => n.device_id === dev.id && n.position) ??
      station.flow.nodes.find((n) => n.actions?.some((a) => a.device_id === dev.id) && n.position);
    const position = flowHintNode?.position
      ? { x: flowHintNode.position.x, y: flowHintNode.position.y }
      : { x: 285 + (idx % 2) * 305, y: 75 + Math.floor(idx / 2) * 205 };

    const cohesiveIoMap = buildCohesiveIoMap(dev, signalsById);
    const ioSummaryText =
      Object.entries(cohesiveIoMap)
        .map(([k, v]) => `${k}: ${v}`)
        .join(' · ') || spec.defaultIoSummaryText;

    return {
      id: dev.id,
      role: 'ACTUATOR',
      title: dev.name,
      driverClass,
      instanceDb: `DB_${sanitizeIdent(station.id)}_${sanitizeIdent(dev.id)}`,
      position,
      isPinned: Boolean(flowHintNode?.position),
      hasPartPresentSensor:
        spec.supportsPartPresentSensor ||
        Boolean(cohesiveIoMap.part_present || cohesiveIoMap.diPartPresent),
      discreteStates: [...spec.defaultDiscreteStates],
      initialHomeState: spec.initialHomeState,
      cohesiveIoMap,
      ioSummaryText,
      theme: spec.theme,
      inPorts: spec.defaultInPorts.map((p) => ({ ...p })),
      outPorts: spec.defaultOutPorts.map((p) => ({ ...p })),
    };
  });

  const boundOutInPorts: SpatialPort[] = [
    { id: 'IN_CYCLE_END', label: '▶ 工位完成放行', type: 'SEQ' },
    ...outputPublicPorts.map((p) => ({
      id: `IN_SAFE_${p.id}`,
      label: `🛡️ ${p.name}`,
      type: 'GUARD' as const,
    })),
  ];

  const maxX = deviceNodes.reduce((m, n) => Math.max(m, n.position.x), 300);
  const boundOutNode: SpatialInstanceNode = {
    id: boundOutId,
    role: 'BOUNDARY_OUT',
    title: `${station.name} · 右输出边界`,
    driverClass: 'STATION_OUTPUT_PORT',
    instanceDb: `输出至 L1 (${station.id})`,
    position: { x: maxX + 320, y: 150 },
    isPinned: true,
    discreteStates: ['Idle', 'CycleDone'],
    initialHomeState: 'Idle',
    cohesiveIoMap: {},
    theme: 'ink',
    inPorts: boundOutInPorts,
    outPorts: [],
  };

  const spatialNodes: SpatialInstanceNode[] = [boundInNode, ...deviceNodes, boundOutNode];
  const spatialById = new Map(spatialNodes.map((n) => [n.id, n]));

  const guardEdges: SafetyGuardEdge[] = [];
  const defaultProtectedActuator =
    deviceNodes.find((n) => n.driverClass === 'FB_AF_AxisMotion') ?? deviceNodes[0];

  // 1) Station interlocks -> SafetyGuardEdges
  (station.interlocks ?? []).forEach((interlock, idx) => {
    const crossRef = resolveCrossStationSource(design, station, interlock, signalsById);
    const diagCodeHex = normalizeDiagHex(interlock.block_code, idx + 1);
    const humanDescription = interlock.human_text?.trim() || interlock.name;
    const isHealthy = interlock.active !== false;

    if (crossRef || interlock.cross_station || interlock.public_port) {
      const fromPortId = interlock.public_port
        ? `OUT_${interlock.public_port}`
        : boundInNode.outPorts.find((p) => p.type === 'GUARD')?.id ?? 'OUT_PART_ARRIVED';
      if (!boundInNode.outPorts.some((p) => p.id === fromPortId)) {
        boundInNode.outPorts.push({
          id: fromPortId,
          label: `🛡️ ${interlock.name}`,
          type: 'GUARD',
          isFaultLeaf: true,
        });
      }

      const targetNode =
        (defaultProtectedActuator && defaultProtectedActuator.id !== crossRef?.upstreamInstanceId
          ? defaultProtectedActuator
          : undefined) ??
        deviceNodes.find((n) => n.id !== crossRef?.upstreamInstanceId) ??
        boundOutNode;

      if (!targetNode.inPorts.some((p) => p.id === 'IN_GUARD')) {
        targetNode.inPorts.push({ id: 'IN_GUARD', label: '🛡️ 防撞护栏', type: 'GUARD' });
      }

      guardEdges.push({
        id: interlock.id,
        fromNode: boundInNode.id,
        fromPort: fromPortId,
        toNode: targetNode.id,
        toPort: 'IN_GUARD',
        requiredSourceState: interlock.value ? 'AtHome' : 'AtWork',
        diagCodeHex,
        humanDescription,
        isHealthy,
        ...(crossRef ? { crossStationRef: crossRef } : {}),
      });
      return;
    }

    if (interlock.device_id) {
      const srcNode = spatialById.get(interlock.device_id);
      if (!srcNode) return;
      const srcGuardPortId =
        srcNode.outPorts.find((p) => p.type === 'GUARD')?.id ?? `OUT_${interlock.port ?? 'GUARD'}`;
      if (!srcNode.outPorts.some((p) => p.id === srcGuardPortId)) {
        srcNode.outPorts.push({
          id: srcGuardPortId,
          label: `🛡️ ${interlock.port ?? '安全位'}`,
          type: 'GUARD',
        });
      }

      const targetNode =
        deviceNodes.find((n) => n.id !== srcNode.id && n.driverClass === 'FB_AF_AxisMotion') ??
        deviceNodes.find((n) => n.id !== srcNode.id) ??
        boundOutNode;
      const targetGuardPort =
        targetNode.inPorts.find((p) => p.type === 'GUARD')?.id ?? 'IN_GUARD';
      if (!targetNode.inPorts.some((p) => p.id === targetGuardPort)) {
        targetNode.inPorts.push({ id: targetGuardPort, label: '🛡️ 防撞护栏', type: 'GUARD' });
      }

      guardEdges.push({
        id: interlock.id,
        fromNode: srcNode.id,
        fromPort: srcGuardPortId,
        toNode: targetNode.id,
        toPort: targetGuardPort,
        requiredSourceState: interlock.value ? srcNode.initialHomeState : srcNode.discreteStates[1] ?? 'AtWork',
        diagCodeHex,
        humanDescription,
        isHealthy,
      });
    }
  });

  // 2) Internal interface feed wires -> Boundary guard exposure edges (e.g. G_ST10_OUT)
  const ifaceNode = station.flow.nodes.find((n) => n.kind === 'interface');
  if (ifaceNode) {
    (station.flow.wires ?? [])
      .filter((w) => w.to_id === ifaceNode.id)
      .forEach((wire, idx) => {
        const feeder = station.flow.nodes.find((n) => n.id === wire.from_id);
        let devId = feeder?.device_id ?? null;
        if (!devId && feeder?.kind === 'action' && feeder.actions?.length === 1) {
          devId = feeder.actions[0].device_id;
        }
        const srcNode = devId ? spatialById.get(devId) : undefined;
        if (!srcNode) return;
        const fromPortId =
          srcNode.outPorts.find((p) => p.type === 'GUARD')?.id ?? `OUT_${wire.from_port}`;
        if (!srcNode.outPorts.some((p) => p.id === fromPortId)) {
          srcNode.outPorts.push({
            id: fromPortId,
            label: `🛡️ ${wire.from_port}`,
            type: 'GUARD',
            isFaultLeaf: true,
          });
        }
        const toPortId = `IN_SAFE_${wire.to_port}`;
        if (!boundOutNode.inPorts.some((p) => p.id === toPortId)) {
          boundOutNode.inPorts.push({
            id: toPortId,
            label: `🛡️ ${wire.to_port}`,
            type: 'GUARD',
          });
        }
        guardEdges.push({
          id: `G_EXP_${wire.id}`,
          fromNode: srcNode.id,
          fromPort: fromPortId,
          toNode: boundOutNode.id,
          toPort: toPortId,
          requiredSourceState: srcNode.initialHomeState,
          diagCodeHex: normalizeDiagHex(null, guardEdges.length + idx + 1),
          humanDescription: `暴露 ${srcNode.title} (${wire.from_port}) 至工站边界 ${wire.to_port}`,
          isHealthy: true,
        });
      });
  }

  // 3) Flow steps -> TemporalStepHyperEdges
  const temporalSteps: TemporalStepHyperEdge[] = [];
  const orderedNodes = primarySteps(station.flow);
  const incomingEdgeByNode = new Map<string, Edge>();
  station.flow.edges.forEach((e) => {
    if (!incomingEdgeByNode.has(e.to_id)) {
      incomingEdgeByNode.set(e.to_id, e);
    }
  });
  const nodeById = new Map(station.flow.nodes.map((n) => [n.id, n]));
  const stepSourceByFlowNodeId = new Map<string, { nodeId: string; portId: string }>();

  let prevNodeId = boundInNode.id;
  let prevPortId = 'OUT_PART_ARRIVED';
  let stepCounter = 10;

  for (const flowNode of orderedNodes) {
    if (flowNode.kind === 'action' && flowNode.actions && flowNode.actions.length > 0) {
      const invocations = flowNode.actions.map((act) =>
        mapActionToInvocation(act, flowNode, spatialById)
      );

      // Node-level permissions -> SafetyGuardEdges if not already present
      for (const perm of flowNode.permissions ?? []) {
        const alreadyHas = guardEdges.some(
          (g) => g.fromNode === perm.device_id && invocations.some((inv) => inv.targetNodeId === g.toNode)
        );
        const srcNode = spatialById.get(perm.device_id);
        const targetActNode = spatialById.get(invocations[0].targetNodeId);
        if (!alreadyHas && srcNode && targetActNode && srcNode.id !== targetActNode.id) {
          const fromPort =
            srcNode.outPorts.find((p) => p.type === 'GUARD')?.id ?? `OUT_${perm.port}`;
          if (!srcNode.outPorts.some((p) => p.id === fromPort)) {
            srcNode.outPorts.push({ id: fromPort, label: `🛡️ ${perm.port}`, type: 'GUARD' });
          }
          if (!targetActNode.inPorts.some((p) => p.id === 'IN_GUARD')) {
            targetActNode.inPorts.push({ id: 'IN_GUARD', label: '🛡️ 防撞护栏', type: 'GUARD' });
          }
          guardEdges.push({
            id: `G_PERM_${perm.id}`,
            fromNode: srcNode.id,
            fromPort,
            toNode: targetActNode.id,
            toPort: 'IN_GUARD',
            requiredSourceState: perm.value ? srcNode.initialHomeState : 'AtWork',
            diagCodeHex: normalizeDiagHex(null, guardEdges.length + 1),
            humanDescription: `${srcNode.title}.${perm.port}=${String(perm.value)} 保护 ${targetActNode.title}`,
            isHealthy: true,
          });
        }
      }

      const incoming = incomingEdgeByNode.get(flowNode.id);
      const branchPredicate: TemporalStepHyperEdge['branchPredicate'] =
        incoming?.outcome === 'true'
          ? 'OK'
          : incoming?.outcome === 'false'
            ? 'NG'
            : 'ALWAYS';

      let resolvedFromNode = prevNodeId;
      let resolvedFromPort = prevPortId;
      if (incoming) {
        let ancestorId: string | undefined = incoming.from_id;
        while (ancestorId && nodeById.get(ancestorId)?.kind === 'decision') {
          ancestorId = incomingEdgeByNode.get(ancestorId)?.from_id;
        }
        const ancestorOutput = ancestorId ? stepSourceByFlowNodeId.get(ancestorId) : undefined;
        if (ancestorOutput) {
          resolvedFromNode = ancestorOutput.nodeId;
          resolvedFromPort =
            branchPredicate === 'NG' &&
            spatialById.get(ancestorOutput.nodeId)?.outPorts.some((p) => p.id === 'OUT_NG')
              ? 'OUT_NG'
              : branchPredicate === 'OK' &&
                  spatialById.get(ancestorOutput.nodeId)?.outPorts.some((p) => p.id === 'OUT_OK')
                ? 'OUT_OK'
                : ancestorOutput.portId;
        }
      }

      const targetIds = new Set(invocations.map((i) => i.targetNodeId));
      const requiresGuardNodeIds = guardEdges
        .filter((g) => targetIds.has(g.toNode) && g.fromNode !== boundInNode.id)
        .map((g) => g.fromNode);

      temporalSteps.push({
        id: `T_${flowNode.id}`,
        stepNo: stepCounter,
        title: flowNode.name,
        fromNode: resolvedFromNode,
        fromPort: resolvedFromPort,
        invocations,
        branchPredicate,
        ...(requiresGuardNodeIds.length > 0 ? { requiresGuardNodeIds } : {}),
      });

      const primaryTarget = spatialById.get(invocations[0].targetNodeId);
      const outPortId =
        primaryTarget?.outPorts.find((p) => p.type === 'SEQ')?.id ?? 'OUT_DONE';
      prevNodeId = primaryTarget?.id ?? prevNodeId;
      prevPortId = outPortId;
      stepSourceByFlowNodeId.set(flowNode.id, { nodeId: prevNodeId, portId: prevPortId });
      stepCounter += 10;
    } else if (flowNode.kind === 'done' && temporalSteps.length > 0) {
      temporalSteps.push({
        id: `T_${flowNode.id}`,
        stepNo: stepCounter,
        title: flowNode.name || '放行下游工站',
        fromNode: prevNodeId,
        fromPort: prevPortId,
        invocations: [
          {
            targetNodeId: boundOutNode.id,
            targetPortId: 'IN_CYCLE_END',
            methodId: 'ReleaseNext',
            actionLabel: flowNode.name || '放行成品至下游',
            targetDiscreteState: 'CycleDone',
            sclStatement: 'o_bCycleDone := TRUE;',
            waitPredicateScl: 'i_bDownstreamAck',
            waitDescription: '下游接收握手',
          },
        ],
        branchPredicate: 'ALWAYS',
      });
      stepCounter += 10;
    }
  }

  return {
    stationId: station.id,
    stationName: station.name,
    spatialNodes,
    guardEdges,
    temporalSteps,
  };
}

/** 将 V2 StationDesign 工程设计模型无损转换为正交超图工作区 */
export function stationDesignToHyperGraphWorkspace(design: StationDesign): AfStudioWorkspaceData {
  const signalsById = new Map(design.hardware.signals.map((s) => [s.id, s]));
  const stationGraphs: Record<string, StationHyperGraph> = {};

  for (const station of design.stations) {
    stationGraphs[station.id] = convertStationToHyperGraph(design, station, signalsById);
  }

  const l1Stations: ProjectCompoundStation[] = design.stations.map((station, idx) => {
    const l1Node = design.flow.nodes.find(
      (n) => (n.kind === 'station' || n.kind === 'handoff') && n.station_ids.includes(station.id)
    );
    const inPublicPorts = (station.public_ports ?? []).filter((p) => p.direction === 'input');
    const outPublicPorts = (station.public_ports ?? []).filter((p) => p.direction === 'output');

    return {
      id: l1Node?.id ?? `NODE_${station.id}`,
      stationId: station.id,
      title: station.name,
      position: l1Node?.position ? { ...l1Node.position } : { x: 80 + idx * 370, y: 120 },
      isPinned: Boolean(l1Node?.position),
      instanceSummaries: station.devices.map(
        (d) => `DB_${sanitizeIdent(station.id)}_${sanitizeIdent(d.id)} (${d.name})`
      ),
      inPorts: [
        { id: 'P_IN_HANDOVER', label: '📦 上游来料握手', type: 'SEQ' },
        ...inPublicPorts.map((p) => ({
          id: p.id,
          label: `🛡️ ${p.name}`,
          type: 'GUARD' as const,
        })),
      ],
      outPorts: [
        { id: 'P_OUT_HANDOVER', label: '📦 成品放行下游 →', type: 'SEQ' },
        ...outPublicPorts.map((p) => ({
          id: p.id,
          label: `🛡️ ${p.name}`,
          type: 'GUARD' as const,
          isFaultLeaf: p.type === 'BOOL',
        })),
      ],
    };
  });

  const l1NodeIdByStationId = new Map(l1Stations.map((s) => [s.stationId, s.id]));
  const l1StationByNodeId = new Map(l1Stations.map((s) => [s.id, s]));
  const l1Edges: ProjectCompoundEdge[] = [];

  for (const edge of design.flow.edges) {
    const fromSt = l1StationByNodeId.get(edge.from_id);
    const toSt = l1StationByNodeId.get(edge.to_id);
    if (!fromSt || !toSt) continue;
    l1Edges.push({
      id: edge.id,
      fromNode: fromSt.id,
      fromPort: 'P_OUT_HANDOVER',
      toNode: toSt.id,
      toPort: 'P_IN_HANDOVER',
      kind: 'SEQ',
      label: edge.outcome === 'done' ? '物流交接握手' : edge.outcome,
    });
  }

  for (const wire of design.flow.wires ?? []) {
    const fromSt = l1StationByNodeId.get(wire.from_id);
    const toSt = l1StationByNodeId.get(wire.to_id);
    if (!fromSt || !toSt) continue;
    const targetStation = design.stations.find((s) => s.id === toSt.stationId);
    const interlock = targetStation?.interlocks?.find((i) => i.public_port === wire.to_port);

    l1Edges.push({
      id: wire.id,
      fromNode: fromSt.id,
      fromPort: wire.from_port,
      toNode: toSt.id,
      toPort: wire.to_port,
      kind: interlock ? 'GUARD' : 'SEQ',
      label: interlock
        ? `跨站护栏 ${interlock.block_code ?? ''}`.trim()
        : `${wire.from_port} → ${wire.to_port}`,
      ...(interlock?.block_code ? { diagCodeHex: normalizeDiagHex(interlock.block_code) } : {}),
    });
  }

  // Ensure cross-station interlocks without L1 wires still surface on L1 when source_station_id exists
  for (const station of design.stations) {
    for (const interlock of station.interlocks ?? []) {
      if (!interlock.source_station_id || interlock.source_station_id === station.id) continue;
      const fromL1Id = l1NodeIdByStationId.get(interlock.source_station_id);
      const toL1Id = l1NodeIdByStationId.get(station.id);
      if (!fromL1Id || !toL1Id) continue;
      const exists = l1Edges.some(
        (e) => e.fromNode === fromL1Id && e.toNode === toL1Id && e.kind === 'GUARD'
      );
      if (!exists) {
        l1Edges.push({
          id: `E_L1_GUARD_${interlock.id}`,
          fromNode: fromL1Id,
          fromPort: 'P_OUT_HANDOVER',
          toNode: toL1Id,
          toPort: interlock.public_port ?? 'P_IN_HANDOVER',
          kind: 'GUARD',
          label: `跨站护栏 ${interlock.block_code ?? interlock.name}`.trim(),
          ...(interlock.block_code ? { diagCodeHex: normalizeDiagHex(interlock.block_code) } : {}),
        });
      }
    }
  }

  return {
    projectName: design.name,
    projectGraph: {
      stations: l1Stations,
      edges: l1Edges,
    },
    stationGraphs,
  };
}

function inferActionId(invocation: TemporalStepInvocation): string {
  switch (invocation.methodId) {
    case 'ExtendWork':
    case 'PushAndRetract':
      return 'extend';
    case 'RetractHome':
      return 'retract';
    case 'GripClose':
      return 'clamp';
    case 'GripOpen':
      return 'release';
    case 'MovePick':
    case 'MovePress':
    case 'MoveReject':
    case 'MoveWork':
      return 'work';
    case 'MoveHome':
      return 'home';
    default:
      return sanitizeIdent(invocation.methodId).toLowerCase();
  }
}

function ensureHardwareSignal(
  signals: Signal[],
  addressOrId: string,
  nameHint: string,
  portKey: string,
  defaultModuleId: string
): string {
  const existingById = signals.find((s) => s.id === addressOrId);
  if (existingById) return existingById.id;

  const existingByAddr = signals.find((s) => s.address === addressOrId);
  if (existingByAddr) return existingByAddr.id;

  const isOutput = /^%Q/i.test(addressOrId) || /^(do|o_)/i.test(portKey);
  const newId = `sig_${sanitizeIdent(addressOrId)}_${signals.length + 1}`;
  signals.push({
    id: newId,
    name: nameHint,
    module_id: defaultModuleId,
    direction: isOutput ? 'output' : 'input',
    address: addressOrId,
  });
  return newId;
}

/** 将正交超图工作区写回 V2 StationDesign，供现有仿真/编译/审计管线消费 */
export function hyperGraphStationToStationDesign(
  workspace: AfStudioWorkspaceData,
  baseDesign?: StationDesign
): StationDesign {
  const hardware: Hardware = baseDesign
    ? {
        cpu: baseDesign.hardware.cpu,
        network: baseDesign.hardware.network,
        modules: baseDesign.hardware.modules.map((m) => ({ ...m })),
        signals: baseDesign.hardware.signals.map((s) => ({ ...s })),
      }
    : {
        cpu: 'CPU 1515-2 PN',
        network: 'PROFINET',
        modules: [
          { id: 'mod_di_1', name: 'DI 16x24VDC', slot: 1, kind: 'DI' },
          { id: 'mod_do_1', name: 'DQ 16x24VDC', slot: 2, kind: 'DO' },
        ],
        signals: [],
      };

  const defaultDiModule =
    hardware.modules.find((m) => m.kind === 'DI' || m.kind === 'DI_DO')?.id ?? 'mod_di_1';
  const defaultDoModule =
    hardware.modules.find((m) => m.kind === 'DO' || m.kind === 'DI_DO')?.id ?? defaultDiModule;

  const baseStationsById = new Map((baseDesign?.stations ?? []).map((s) => [s.id, s]));
  const stations: Station[] = [];

  for (const hg of Object.values(workspace.stationGraphs)) {
    const baseStation = baseStationsById.get(hg.stationId);
    const baseDevicesById = new Map((baseStation?.devices ?? []).map((d) => [d.id, d]));

    const actuatorNodes = hg.spatialNodes.filter((n) => n.role === 'ACTUATOR');
    const devices: Device[] = actuatorNodes.map((node) => {
      const baseDev = baseDevicesById.get(node.id);
      const bindings: Record<string, string> = {};
      for (const [portKey, val] of Object.entries(node.cohesiveIoMap)) {
        if (!val || portKey === 'cabinetTerminal') continue;
        if (/^%[IQM]/i.test(val)) {
          const sigId = ensureHardwareSignal(
            hardware.signals,
            val,
            `${node.title}_${portKey}`,
            portKey,
            /^%Q/i.test(val) ? defaultDoModule : defaultDiModule
          );
          bindings[portKey] = sigId;
        } else if (baseDev?.bindings[portKey]) {
          bindings[portKey] = baseDev.bindings[portKey];
        } else {
          bindings[portKey] = val;
        }
      }
      return {
        id: node.id,
        name: node.title,
        driver:
          baseDev && mapDriverToMotherClass(baseDev.driver) === node.driverClass
            ? baseDev.driver
            : mapMotherClassToDriver(node.driverClass),
        bindings,
        timeout_ms: baseDev?.timeout_ms ?? 3000,
        ...(baseDev?.extend_timeout_ms !== undefined ? { extend_timeout_ms: baseDev.extend_timeout_ms } : {}),
        ...(baseDev?.retract_timeout_ms !== undefined ? { retract_timeout_ms: baseDev.retract_timeout_ms } : {}),
        ...(baseDev?.homing_priority !== undefined ? { homing_priority: baseDev.homing_priority } : {}),
      };
    });

    const boundIn = hg.spatialNodes.find((n) => n.role === 'BOUNDARY_IN');
    const boundOut = hg.spatialNodes.find((n) => n.role === 'BOUNDARY_OUT');

    const publicPorts: PortDefinition[] = [
      ...(boundIn?.outPorts ?? [])
        .filter((p) => p.type === 'GUARD')
        .map((p) => ({
          id: p.id.startsWith('OUT_') ? p.id.slice(4) : p.id,
          name: p.label.replace(/^🛡️\s*/, ''),
          direction: 'input' as const,
          type: 'BOOL' as const,
        })),
      ...(boundOut?.inPorts ?? [])
        .filter((p) => p.type === 'GUARD')
        .map((p) => ({
          id: p.id.startsWith('IN_SAFE_') ? p.id.slice(8) : p.id,
          name: p.label.replace(/^🛡️\s*/, ''),
          direction: 'output' as const,
          type: 'BOOL' as const,
        })),
    ];

    const stationFlow: Flow = emptyFlow();
    const deviceFlowNodes = new Map<string, Node>();
    for (const node of actuatorNodes) {
      const devNode: Node = {
        id: `devnode_${node.id}`,
        name: node.title,
        kind: 'device',
        device_id: node.id,
        port: null,
        value: true,
        duration_ms: 0,
        timeout_ms: 0,
        station_ids: [],
        position: { ...node.position },
      };
      deviceFlowNodes.set(node.id, devNode);
    }

    const sortedSteps = [...hg.temporalSteps].sort((a, b) => a.stepNo - b.stepNo);
    const stepPairs: Array<{ step: TemporalStepHyperEdge; node: Node }> = [];
    const stepEdges: Edge[] = [];
    const internalWires: SignalWire[] = [];

    for (const step of sortedSteps) {
      const actuatorInvocations = step.invocations.filter((inv) =>
        actuatorNodes.some((a) => a.id === inv.targetNodeId)
      );
      if (actuatorInvocations.length === 0) continue;

      const primaryTarget = actuatorNodes.find(
        (a) => a.id === actuatorInvocations[0].targetNodeId
      );
      const actNode: Node = {
        id: step.id,
        name: step.title,
        kind: 'action',
        device_id: null,
        port: null,
        value: true,
        duration_ms: 0,
        timeout_ms: 3000,
        station_ids: [],
        actions: actuatorInvocations.map((inv) => ({
          device_id: inv.targetNodeId,
          action_id: inferActionId(inv),
        })),
        position: primaryTarget ? { ...primaryTarget.position } : undefined,
      };
      stepPairs.push({ step, node: actNode });
    }

    for (let i = 0; i < stepPairs.length - 1; i++) {
      const nextStep = stepPairs[i + 1].step;
      const outcome: Edge['outcome'] =
        nextStep.branchPredicate === 'OK'
          ? 'true'
          : nextStep.branchPredicate === 'NG'
            ? 'false'
            : 'next';
      stepEdges.push({
        id: `edge_${stepPairs[i].node.id}_${stepPairs[i + 1].node.id}`,
        from_id: stepPairs[i].node.id,
        to_id: stepPairs[i + 1].node.id,
        outcome,
      });
    }

    if (stepPairs.length > 0) {
      const stepNodes = stepPairs.map((p) => p.node);
      const hasBoundOutStep = sortedSteps.some((step) =>
        step.invocations.some((inv) => boundOut && inv.targetNodeId === boundOut.id)
      );
      const baseHasDone = Boolean(baseStation?.flow.nodes.some((n) => n.kind === 'done'));
      if (hasBoundOutStep || baseHasDone) {
        const doneNode: Node = {
          id: `done_${hg.stationId}`,
          name: '工位完成',
          kind: 'done',
          device_id: null,
          port: null,
          value: true,
          duration_ms: 0,
          timeout_ms: 0,
          station_ids: [],
        };
        stepEdges.push({
          id: `edge_${stepNodes[stepNodes.length - 1].id}_${doneNode.id}`,
          from_id: stepNodes[stepNodes.length - 1].id,
          to_id: doneNode.id,
          outcome: 'next',
        });
        stationFlow.nodes = [...stepNodes, doneNode];
      } else {
        stationFlow.nodes = [...stepNodes];
      }
      stationFlow.start = stepNodes[0].id;
      stationFlow.edges = stepEdges;
    }

    const interlocks: Interlock[] = [];
    const ifaceNode: Node = {
      id: `iface_${hg.stationId}`,
      name: '工位接口',
      kind: 'interface',
      device_id: null,
      port: null,
      value: true,
      duration_ms: 0,
      timeout_ms: 0,
      station_ids: [],
    };
    let hasIfaceWire = false;

    for (const guard of hg.guardEdges) {
      if (boundOut && guard.toNode === boundOut.id && !guard.crossStationRef) {
        const srcActuator = actuatorNodes.find((a) => a.id === guard.fromNode);
        const srcFlowNode = srcActuator ? deviceFlowNodes.get(srcActuator.id) : undefined;
        if (srcFlowNode) {
          hasIfaceWire = true;
          if (!stationFlow.nodes.some((n) => n.id === srcFlowNode.id)) {
            stationFlow.nodes.push(srcFlowNode);
          }
          const bindingKeys = srcActuator ? Object.keys(srcActuator.cohesiveIoMap) : [];
          const homeKey =
            bindingKeys.find((k) => /home|retract/i.test(k)) ?? bindingKeys[0] ?? 'diHome';
          const outPublicPort = guard.toPort.startsWith('IN_SAFE_')
            ? guard.toPort.slice(8)
            : guard.toPort;
          internalWires.push({
            id: `wire_${guard.id}`,
            from_id: srcFlowNode.id,
            from_port: `fb_${homeKey}`,
            to_id: ifaceNode.id,
            to_port: outPublicPort,
          });
        }
        continue;
      }

      if (guard.crossStationRef) {
        const pubPort = guard.fromPort.startsWith('OUT_')
          ? guard.fromPort.slice(4)
          : guard.fromPort;
        interlocks.push({
          id: guard.id,
          name: guard.humanDescription,
          device_id: null,
          port: null,
          value: true,
          human_text: guard.humanDescription,
          block_code: toBlockCode(guard.diagCodeHex),
          active: guard.isHealthy !== false,
          public_port: pubPort,
          source_station_id: guard.crossStationRef.upstreamStationId,
          cross_station: true,
        });
      } else {
        const srcActuator = actuatorNodes.find((a) => a.id === guard.fromNode);
        const bindingKeys = srcActuator ? Object.keys(srcActuator.cohesiveIoMap) : [];
        const portKey =
          bindingKeys.find((k) => /home|retract/i.test(k)) ?? bindingKeys[0] ?? 'diHome';
        interlocks.push({
          id: guard.id,
          name: guard.humanDescription,
          device_id: srcActuator ? srcActuator.id : null,
          port: srcActuator ? portKey : null,
          value: true,
          human_text: guard.humanDescription,
          block_code: toBlockCode(guard.diagCodeHex),
          active: guard.isHealthy !== false,
        });
      }
    }

    if (hasIfaceWire) {
      stationFlow.nodes.push(ifaceNode);
      stationFlow.wires = internalWires;
    }

    stations.push({
      id: hg.stationId,
      name: hg.stationName,
      devices,
      flow: stationFlow,
      ...(interlocks.length > 0 ? { interlocks } : {}),
      ...(publicPorts.length > 0 ? { public_ports: publicPorts } : {}),
    });
  }

  const l1Nodes: Node[] = workspace.projectGraph.stations.map((st) => ({
    id: st.id,
    name: st.title,
    kind: 'station',
    device_id: null,
    port: null,
    value: true,
    duration_ms: 0,
    timeout_ms: 0,
    station_ids: [st.stationId],
    position: { ...st.position },
  }));

  const l1Edges: Edge[] = workspace.projectGraph.edges
    .filter((e) => e.kind === 'SEQ')
    .map((e) => ({
      id: e.id,
      from_id: e.fromNode,
      to_id: e.toNode,
      outcome: 'done',
    }));

  const l1Wires: SignalWire[] = workspace.projectGraph.edges
    .filter((e) => e.kind === 'GUARD')
    .map((e) => {
      const fromStationId = workspace.projectGraph.stations.find((s) => s.id === e.fromNode)?.stationId;
      const toStationId = workspace.projectGraph.stations.find((s) => s.id === e.toNode)?.stationId;
      const targetStation = stations.find((s) => s.id === toStationId);
      const sourceStation = stations.find((s) => s.id === fromStationId);
      const matchingInterlock = targetStation?.interlocks?.find(
        (il) => il.cross_station && (!fromStationId || il.source_station_id === fromStationId)
      );
      const outPort = sourceStation?.public_ports?.find((p) => p.direction === 'output')?.id;
      return {
        id: e.id,
        from_id: e.fromNode,
        from_port: outPort ?? e.fromPort,
        to_id: e.toNode,
        to_port: matchingInterlock?.public_port ?? e.toPort,
      };
    });

  return {
    version: 1,
    name: workspace.projectName || baseDesign?.name || 'AssyLine_01',
    hardware,
    stations,
    flow: {
      start: l1Nodes[0]?.id ?? null,
      nodes: l1Nodes,
      edges: l1Edges,
      ...(l1Wires.length > 0 ? { wires: l1Wires } : {}),
    },
  };
}
