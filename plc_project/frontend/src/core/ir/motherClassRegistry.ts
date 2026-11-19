import type {
  DriverMotherClass,
  RadialMethodOption,
  SpatialInstanceNode,
  SpatialNodeTheme,
  SpatialPort,
} from './afHyperGraph.types';
import { stationBoundaryLabels } from './stationBoundaryLabels';
import { cmProfiles, defaultCmControl } from './fieldIo';

export interface MotherClassSpec {
  driverClass: DriverMotherClass;
  displayName: string;
  role: 'BOUNDARY_IN' | 'BOUNDARY_OUT' | 'ACTUATOR';
  theme: SpatialNodeTheme;
  description: string;
  supportsPartPresentSensor: boolean;
  isSensorOnly: boolean;
  defaultDiscreteStates: string[];
  initialHomeState: string;
  defaultCohesiveIoKeys: string[];
  defaultIoSummaryText: string;
  defaultInPorts: SpatialPort[];
  defaultOutPorts: SpatialPort[];
  radialMethods: RadialMethodOption[];
}

export interface MotherClassPaletteItem {
  id: 'SERVO' | 'CYLINDER' | 'GRIPPER' | 'VISION';
  driverClass: DriverMotherClass;
  title: string;
  subtitle: string;
  badgeText: string;
  theme: SpatialNodeTheme;
  defaultTitlePrefix: string;
  defaultDbPrefix: string;
  defaultIoSummaryText: string;
}

export interface MotherClassRegistry extends Record<DriverMotherClass, MotherClassSpec> {
  [customClass: string]: MotherClassSpec;
}

const VALID_THEMES = new Set<SpatialNodeTheme>(['klein', 'emerald', 'amber', 'vermilion', 'ink']);

export const MOTHER_CLASS_REGISTRY: MotherClassRegistry = {
  FB_AF_AxisMotion: {
    driverClass: 'FB_AF_AxisMotion',
    displayName: '伺服轴母版',
    role: 'ACTUATOR',
    theme: 'klein',
    description: '多位置绝对/相对定位伺服驱动母版，内聚限位与报文映射，支持配方离散目标位点。',
    supportsPartPresentSensor: false,
    isSensorOnly: false,
    defaultDiscreteStates: ['Pos_Home_0', 'Pos_Pick_120', 'Pos_Press_245', 'Pos_Reject_410'],
    initialHomeState: 'Pos_Home_0',
    defaultCohesiveIoKeys: ['drvTelegram', 'diHomeLim', 'diPosLim', 'diNegLim'],
    defaultIoSummaryText: '配方: 待机0 / 取料120 / 压装245 / 抛料410mm',
    defaultInPorts: [
      { id: 'IN_EXEC', label: '▶ 多位置伺服触发槽', type: 'SEQ' },
      { id: 'IN_GUARD', label: '🛡️ 防撞护栏 (i_bInterlockOK)', type: 'GUARD' },
    ],
    defaultOutPorts: [{ id: 'OUT_DONE', label: '● 伺服定位完成 →', type: 'SEQ' }],
    radialMethods: [
      {
        methodId: 'MovePick',
        label: '🎯 移至取料位 (120mm)',
        waitDescription: '到达取料位',
        sclCommand: 'MoveAbs(120.0)',
        targetDiscreteState: 'Pos_Pick_120',
      },
      {
        methodId: 'MovePress',
        label: '🎯 移至压装位 (245mm)',
        waitDescription: '到达压装位',
        sclCommand: 'MoveAbs(245.0)',
        targetDiscreteState: 'Pos_Press_245',
      },
      {
        methodId: 'MoveReject',
        label: '🗑️ 移至NG抛料位 (410mm)',
        waitDescription: '到达NG抛料位',
        sclCommand: 'MoveAbs(410.0)',
        targetDiscreteState: 'Pos_Reject_410',
      },
      {
        methodId: 'MoveHome',
        label: '🏠 回待机原位 (0mm)',
        waitDescription: '到达0mm待机位',
        sclCommand: 'MoveAbs(0.0)',
        targetDiscreteState: 'Pos_Home_0',
      },
      {
        methodId: 'GUARD',
        label: '🛡️ 设为永久防撞护栏',
        waitDescription: '安全原位互锁满足',
        sclCommand: 'i_bInterlockOK',
        targetDiscreteState: 'Pos_Home_0',
        isGuard: true,
      },
    ],
  },

  FB_AF_Actuator2Pos: {
    driverClass: 'FB_AF_Actuator2Pos',
    displayName: '双位气缸母版',
    role: 'ACTUATOR',
    theme: 'emerald',
    description: '标准双位执行器母版，内聚原位/动位双磁开与电磁阀输出，暴露安全原位护栏端口。',
    supportsPartPresentSensor: false,
    isSensorOnly: false,
    defaultDiscreteStates: ['AtHome', 'AtWork'],
    initialHomeState: 'AtHome',
    defaultCohesiveIoKeys: ['diHome', 'diWork', 'doWork'],
    defaultIoSummaryText: '原/动位双磁开内聚',
    defaultInPorts: [
      { id: 'IN_EXEC', label: '▶ 伸出/缩回触发槽', type: 'SEQ' },
      { id: 'IN_GUARD', label: '🛡️ 防撞护栏 (i_bInterlockOK)', type: 'GUARD' },
    ],
    defaultOutPorts: [
      { id: 'OUT_DONE', label: '● 气缸动作到位 →', type: 'SEQ' },
      { id: 'OUT_AT_HOME', label: '🛡️ 原位安全状态 (AtHome)', type: 'GUARD' },
    ],
    radialMethods: [
      {
        methodId: 'ExtendWork',
        label: '⬇ 伸出下压并保压1.5s',
        waitDescription: '动位磁开导通',
        sclCommand: 'ExtendWork()',
        targetDiscreteState: 'AtWork',
      },
      {
        methodId: 'RetractHome',
        label: '⬆ 缩回顶升安全原位',
        waitDescription: '原位磁开导通',
        sclCommand: 'RetractHome()',
        targetDiscreteState: 'AtHome',
      },
      {
        methodId: 'GUARD',
        label: '🛡️ 设为永久防撞护栏',
        waitDescription: '原位安全互锁满足',
        sclCommand: 'i_bInterlockOK',
        targetDiscreteState: 'AtHome',
        isGuard: true,
      },
    ],
  },

  FB_AF_Gripper: {
    driverClass: 'FB_AF_Gripper',
    displayName: '平行夹爪母版',
    role: 'ACTUATOR',
    theme: 'emerald',
    description: '气动/电动夹爪母版，内聚带料检测光电 (bPartPresent) 保护算子，支持 Auto-Homing 防掉料分支。',
    supportsPartPresentSensor: true,
    isSensorOnly: false,
    defaultDiscreteStates: ['Opened', 'Closed'],
    initialHomeState: 'Opened',
    defaultCohesiveIoKeys: ['diClosed', 'diOpened', 'diPartPresent', 'doClose', 'doOpen'],
    defaultIoSummaryText: '带料光电保护内聚',
    defaultInPorts: [
      { id: 'IN_EXEC', label: '▶ 工艺动作触发槽', type: 'SEQ' },
      { id: 'IN_GUARD', label: '🛡️ 防撞护栏 (i_bInterlockOK)', type: 'GUARD' },
    ],
    defaultOutPorts: [{ id: 'OUT_DONE', label: '● 动作到位反馈 →', type: 'SEQ' }],
    radialMethods: [
      {
        methodId: 'GripClose',
        label: '✊ 闭合夹紧电芯',
        waitDescription: '夹紧磁开导通',
        sclCommand: 'CloseGrip()',
        targetDiscreteState: 'Closed',
      },
      {
        methodId: 'GripOpen',
        label: '🖐️ 张开释放电芯',
        waitDescription: '张开磁开导通',
        sclCommand: 'OpenGrip()',
        targetDiscreteState: 'Opened',
      },
      {
        methodId: 'GUARD',
        label: '🛡️ 设为永久防撞护栏',
        waitDescription: '原位安全互锁满足',
        sclCommand: 'i_bInterlockOK',
        targetDiscreteState: 'Opened',
        isGuard: true,
      },
    ],
  },

  FB_AF_Vacuum: {
    driverClass: 'FB_AF_Vacuum', displayName: '真空吸盘 CM', role: 'ACTUATOR', theme: 'amber',
    description: '吸附、释放与真空反馈。',
    supportsPartPresentSensor: false, isSensorOnly: false,
    defaultDiscreteStates: defaultCmControl('Vacuum@1').discreteStates, initialHomeState: 'Released',
    defaultCohesiveIoKeys: [], defaultIoSummaryText: '',
    defaultInPorts: defaultCmControl('Vacuum@1').inPorts,
    defaultOutPorts: defaultCmControl('Vacuum@1').outPorts,
    radialMethods: [...cmProfiles['Vacuum@1'].actions],
  },

  FB_AF_MotorStartStop: {
    driverClass: 'FB_AF_MotorStartStop', displayName: '启停电机 CM', role: 'ACTUATOR', theme: 'klein',
    description: '点位启停控制，适用于同类输送电机。',
    supportsPartPresentSensor: false, isSensorOnly: false,
    defaultDiscreteStates: defaultCmControl('MotorStartStop@1').discreteStates, initialHomeState: 'Stopped',
    defaultCohesiveIoKeys: [], defaultIoSummaryText: '',
    defaultInPorts: defaultCmControl('MotorStartStop@1').inPorts,
    defaultOutPorts: defaultCmControl('MotorStartStop@1').outPorts,
    radialMethods: [...cmProfiles['MotorStartStop@1'].actions],
  },

  FB_AF_VisionSensor: {
    driverClass: 'FB_AF_VisionSensor',
    displayName: '视觉/测高仪母版',
    role: 'ACTUATOR',
    theme: 'amber',
    description: '工艺检测传感器母版（2D视觉相机、激光测高仪、读码器），输出 OK/NG 分支结果。',
    supportsPartPresentSensor: false,
    isSensorOnly: true,
    defaultDiscreteStates: ['Idle', 'Pass_OK', 'Fail_NG'],
    initialHomeState: 'Idle',
    defaultCohesiveIoKeys: ['profinetTrig', 'profinetResultOk', 'profinetResultNg'],
    defaultIoSummaryText: 'Profinet 结果数据块',
    defaultInPorts: [{ id: 'IN_EXEC', label: '▶ 触发拍照检测', type: 'SEQ' }],
    defaultOutPorts: [
      { id: 'OUT_OK', label: '● 判定 OK →', type: 'SEQ' },
      { id: 'OUT_NG', label: '● 判定 NG →', type: 'SEQ' },
    ],
    radialMethods: [
      {
        methodId: 'TrigInspect',
        label: '📸 触发拍照极性检测',
        waitDescription: '视觉判定完成',
        sclCommand: 'TriggerCam()',
        targetDiscreteState: 'Pass_OK',
      },
    ],
  },

  FB_AF_DigitalInput: {
    driverClass: 'FB_AF_DigitalInput', displayName: '数字输入 CM', role: 'ACTUATOR', theme: 'ink',
    description: '读取现场数字输入并提供在位状态。',
    supportsPartPresentSensor: false, isSensorOnly: true,
    defaultDiscreteStates: ['Off', 'On'], initialHomeState: 'Off',
    defaultCohesiveIoKeys: [], defaultIoSummaryText: '',
    defaultInPorts: [], defaultOutPorts: [{ id: 'OUT_DONE', label: '● 在位状态', type: 'SEQ' }],
    radialMethods: [],
  },

  FB_AF_Robot6Axis: {
    driverClass: 'FB_AF_Robot6Axis', displayName: '六轴机器人 CM', role: 'ACTUATOR', theme: 'klein',
    description: '机器人通信与握手接口待定义。',
    supportsPartPresentSensor: false, isSensorOnly: false,
    defaultDiscreteStates: ['AtHome', 'AtWork'], initialHomeState: 'AtHome',
    defaultCohesiveIoKeys: [], defaultIoSummaryText: '',
    defaultInPorts: [{ id: 'IN_EXEC', label: '▶ 作业请求', type: 'SEQ' }, { id: 'IN_GUARD', label: '🛡️ 防撞护栏', type: 'GUARD' }],
    defaultOutPorts: [{ id: 'OUT_DONE', label: '● 作业应答', type: 'SEQ' }],
    radialMethods: [],
  },

  STATION_INPUT_PORT: {
    driverClass: 'STATION_INPUT_PORT',
    displayName: '工站输入边界',
    role: 'BOUNDARY_IN',
    theme: 'ink',
    description: '将 L1 的工位请求和外部安全许可传给站内逻辑。',
    supportsPartPresentSensor: false,
    isSensorOnly: false,
    defaultDiscreteStates: ['WaitingPart', 'PartArrived'],
    initialHomeState: 'WaitingPart',
    defaultCohesiveIoKeys: ['i_bPartArrived', 'i_bUpstreamSafe'],
    defaultIoSummaryText: '映射自 L1 产线接口',
    defaultInPorts: [],
    defaultOutPorts: [{ id: 'OUT_PART_ARRIVED', label: stationBoundaryLabels.request, type: 'SEQ' }],
    radialMethods: [],
  },

  STATION_OUTPUT_PORT: {
    driverClass: 'STATION_OUTPUT_PORT',
    displayName: '工站输出边界',
    role: 'BOUNDARY_OUT',
    theme: 'ink',
    description: '向 L1 回报工位完成结果和安全状态。',
    supportsPartPresentSensor: false,
    isSensorOnly: false,
    defaultDiscreteStates: ['Idle', 'CycleDone'],
    initialHomeState: 'Idle',
    defaultCohesiveIoKeys: ['o_bCycleDone', 'o_bSafeAtHome'],
    defaultIoSummaryText: '反馈至 L1 工位接口',
    defaultInPorts: [{ id: 'IN_CYCLE_END', label: stationBoundaryLabels.done, type: 'SEQ' }],
    defaultOutPorts: [],
    radialMethods: [
      {
        methodId: 'ReleaseNext',
        label: '报告工位完成',
        waitDescription: '工位完成应答',
        sclCommand: 'o_bCycleDone := TRUE',
        targetDiscreteState: 'CycleDone',
      },
    ],
  },
};

export const MOTHER_CLASS_PALETTE: MotherClassPaletteItem[] = [
  {
    id: 'SERVO',
    driverClass: 'FB_AF_AxisMotion',
    title: '伺服轴母版',
    subtitle: 'FB_AF_AxisMotion · 含离散配方点',
    badgeText: '+ 实例',
    theme: 'klein',
    defaultTitlePrefix: '辅助伺服轴',
    defaultDbPrefix: 'Axis',
    defaultIoSummaryText: '离散配方点定位',
  },
  {
    id: 'CYLINDER',
    driverClass: 'FB_AF_Actuator2Pos',
    title: '双位气缸母版',
    subtitle: 'FB_AF_Actuator2Pos · 内聚双磁开',
    badgeText: '+ 实例',
    theme: 'emerald',
    defaultTitlePrefix: '辅助气缸',
    defaultDbPrefix: 'Cyl',
    defaultIoSummaryText: '原/动位双磁开内聚',
  },
  {
    id: 'GRIPPER',
    driverClass: 'FB_AF_Gripper',
    title: '平行夹爪母版',
    subtitle: 'FB_AF_Gripper · 含带料保护算子',
    badgeText: '+ 实例',
    theme: 'emerald',
    defaultTitlePrefix: '气动夹爪',
    defaultDbPrefix: 'Grip',
    defaultIoSummaryText: '带料光电保护内聚',
  },
  {
    id: 'VISION',
    driverClass: 'FB_AF_VisionSensor',
    title: '视觉/测高仪母版',
    subtitle: 'FB_AF_VisionSensor · 工艺传感器',
    badgeText: '+ 实例',
    theme: 'amber',
    defaultTitlePrefix: '工艺传感器',
    defaultDbPrefix: 'Cam',
    defaultIoSummaryText: 'Profinet 结果数据块',
  },
];

function cloneRadialOption(opt: RadialMethodOption): RadialMethodOption {
  return { ...opt };
}

function clonePort(port: SpatialPort): SpatialPort {
  return { ...port };
}

function cloneSpec(spec: MotherClassSpec): MotherClassSpec {
  return {
    ...spec,
    defaultDiscreteStates: [...spec.defaultDiscreteStates],
    defaultCohesiveIoKeys: [...spec.defaultCohesiveIoKeys],
    defaultInPorts: spec.defaultInPorts.map(clonePort),
    defaultOutPorts: spec.defaultOutPorts.map(clonePort),
    radialMethods: spec.radialMethods.map(cloneRadialOption),
  };
}

function synthesizeAxisMethodForState(stateName: string, homeState: string): RadialMethodOption {
  const numMatch = stateName.match(/(-?\d+(?:\.\d+)?)$/);
  const posValue = numMatch ? `${numMatch[1]}.0`.replace('.0.0', '.0') : '0.0';
  if (stateName === homeState || /home/i.test(stateName)) {
    return {
      methodId: 'MoveHome',
      label: `🏠 回待机原位 (${numMatch ? numMatch[1] : '0'}mm)`,
      waitDescription: `到达${stateName}待机位`,
      sclCommand: `MoveAbs(${posValue})`,
      targetDiscreteState: stateName,
    };
  }
  const cleanName = stateName.replace(/^Pos_/, '');
  return {
    methodId: `Move_${cleanName}`,
    label: `🎯 移至 ${cleanName}${numMatch ? ` (${numMatch[1]}mm)` : ''}`,
    waitDescription: `到达${cleanName}`,
    sclCommand: `MoveAbs(${posValue})`,
    targetDiscreteState: stateName,
  };
}

/**
 * 动态读取驱动母版在径向菜单中的工艺动作选项；
 * 当传入具体节点实例时，若实例定制了额外离散位置点，会自动补全对应定位动作。
 */
export function getRadialMethodsForClass(
  driverClass: DriverMotherClass,
  node?: SpatialInstanceNode
): RadialMethodOption[] {
  const spec = MOTHER_CLASS_REGISTRY[driverClass];
  if (!spec) return [];

  if (node?.cmProfile) {
    return [...cmProfiles[node.cmProfile].actions, ...spec.radialMethods.filter((method) => method.isGuard)]
      .map(cloneRadialOption);
  }

  const baseMethods = spec.radialMethods.map(cloneRadialOption);
  if (!node) return baseMethods;

  if (driverClass === 'FB_AF_AxisMotion' && node.discreteStates.length > 0) {
    const knownByState = new Map<string, RadialMethodOption>();
    let guardMethod: RadialMethodOption | undefined;
    for (const m of baseMethods) {
      if (m.isGuard) {
        guardMethod = m;
      } else {
        knownByState.set(m.targetDiscreteState, m);
      }
    }

    const adapted: RadialMethodOption[] = [];
    for (const state of node.discreteStates) {
      const existing = knownByState.get(state);
      if (existing) {
        adapted.push(cloneRadialOption(existing));
      } else {
        adapted.push(synthesizeAxisMethodForState(state, node.initialHomeState));
      }
    }
    if (guardMethod) {
      adapted.push({
        ...cloneRadialOption(guardMethod),
        targetDiscreteState: node.initialHomeState || guardMethod.targetDiscreteState,
      });
    }
    return adapted;
  }

  if (driverClass === 'STATION_OUTPUT_PORT') {
    const hasGuardPort = node.inPorts.some((p) => p.type === 'GUARD');
    if (hasGuardPort && !baseMethods.some((m) => m.isGuard)) {
      baseMethods.push({
        methodId: 'GUARD',
        label: '🛡️ 设为永久防撞护栏',
        waitDescription: '暴露安全状态至下游护栏',
        sclCommand: 'o_bSafeAtHome',
        targetDiscreteState: node.initialHomeState || 'Idle',
        isGuard: true,
      });
    }
  }

  return baseMethods;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function normalizePort(raw: unknown): SpatialPort | null {
  if (!isRecord(raw) || typeof raw.id !== 'string' || !raw.id) return null;
  const type = raw.type === 'GUARD' ? 'GUARD' : 'SEQ';
  return {
    id: raw.id,
    label: typeof raw.label === 'string' && raw.label ? raw.label : raw.id,
    type,
    ...(raw.isFaultLeaf === true ? { isFaultLeaf: true } : {}),
  };
}

function normalizeRadialMethod(raw: unknown): RadialMethodOption | null {
  if (!isRecord(raw)) return null;
  const methodId =
    typeof raw.methodId === 'string'
      ? raw.methodId
      : typeof raw.id === 'string'
        ? raw.id
        : '';
  if (!methodId) return null;
  const isGuard = raw.isGuard === true || methodId === 'GUARD';
  const label = typeof raw.label === 'string' && raw.label ? raw.label : methodId;
  const waitDescription =
    typeof raw.waitDescription === 'string'
      ? raw.waitDescription
      : typeof raw.waitDesc === 'string'
        ? raw.waitDesc
        : isGuard
          ? '安全原位互锁满足'
          : `${label} 到位`;
  const sclCommand =
    typeof raw.sclCommand === 'string'
      ? raw.sclCommand
      : typeof raw.sclCmd === 'string'
        ? raw.sclCmd
        : typeof raw.sclStatement === 'string'
          ? raw.sclStatement
          : isGuard
            ? 'i_bInterlockOK'
            : `${methodId}()`;
  const targetDiscreteState =
    typeof raw.targetDiscreteState === 'string'
      ? raw.targetDiscreteState
      : typeof raw.targetState === 'string'
        ? raw.targetState
        : isGuard
          ? 'AtHome'
          : methodId;

  return {
    methodId,
    label,
    waitDescription,
    sclCommand,
    targetDiscreteState,
    ...(isGuard ? { isGuard: true } : {}),
  };
}

function stringList(raw: unknown): string[] | undefined {
  if (!Array.isArray(raw)) return undefined;
  const cleaned = raw.filter((item): item is string => typeof item === 'string' && item.trim().length > 0);
  return cleaned.length > 0 ? cleaned : undefined;
}

function extractReflectedEntries(parsed: unknown): Array<{ classKey: string; body: Record<string, unknown> }> {
  const entries: Array<{ classKey: string; body: Record<string, unknown> }> = [];

  const pushEntry = (fallbackKey: string, obj: unknown) => {
    if (!isRecord(obj)) return;
    const keyCandidate =
      (typeof obj.driverClass === 'string' && obj.driverClass) ||
      (typeof obj.className === 'string' && obj.className) ||
      (typeof obj.fbName === 'string' && obj.fbName) ||
      (typeof obj.name === 'string' && obj.name) ||
      fallbackKey;
    if (keyCandidate) {
      entries.push({ classKey: keyCandidate, body: obj });
    }
  };

  if (Array.isArray(parsed)) {
    parsed.forEach((item, idx) => pushEntry(`CUSTOM_${idx}`, item));
    return entries;
  }

  if (!isRecord(parsed)) {
    throw new Error('Reflected motherClassRegistry JSON must be an object or array.');
  }

  const listField = parsed.classes ?? parsed.motherClasses ?? parsed.blocks ?? parsed.items;
  if (Array.isArray(listField)) {
    listField.forEach((item, idx) => pushEntry(`CUSTOM_${idx}`, item));
    return entries;
  }

  const mapField = isRecord(parsed.registry) ? parsed.registry : parsed;
  for (const [key, val] of Object.entries(mapField)) {
    if (key === 'version' || key === 'tiaVersion' || key === 'exportedAt' || key === 'libraryName') {
      continue;
    }
    pushEntry(key, val);
  }
  return entries;
}

/**
 * 解析由 C# `AfLibraryReflector` 扫描博途全局库导出的 `motherClassRegistry.json`，
 * 并与内置的 6 类标准母版元数据安全合并。
 */
export function parseReflectedRegistryJson(
  rawJson: string | Record<string, unknown>
): MotherClassRegistry {
  let parsed: unknown;
  if (typeof rawJson === 'string') {
    try {
      parsed = JSON.parse(rawJson);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      throw new Error(`Invalid reflected motherClassRegistry JSON: ${msg}`);
    }
  } else {
    parsed = rawJson;
  }

  const merged: Record<string, MotherClassSpec> = {};
  for (const key of Object.keys(MOTHER_CLASS_REGISTRY) as DriverMotherClass[]) {
    merged[key] = cloneSpec(MOTHER_CLASS_REGISTRY[key]);
  }

  const entries = extractReflectedEntries(parsed);
  for (const { classKey, body } of entries) {
    const base = merged[classKey];

    const displayName =
      (typeof body.displayName === 'string' && body.displayName) ||
      (typeof body.title === 'string' && body.title) ||
      (typeof body.label === 'string' && body.label) ||
      base?.displayName ||
      classKey;

    const themeCandidate = typeof body.theme === 'string' ? (body.theme as SpatialNodeTheme) : undefined;
    const theme: SpatialNodeTheme =
      themeCandidate && VALID_THEMES.has(themeCandidate) ? themeCandidate : base?.theme ?? 'klein';

    const roleCandidate = body.role;
    const role: MotherClassSpec['role'] =
      roleCandidate === 'BOUNDARY_IN' || roleCandidate === 'BOUNDARY_OUT' || roleCandidate === 'ACTUATOR'
        ? roleCandidate
        : base?.role ?? 'ACTUATOR';

    const states =
      stringList(body.defaultDiscreteStates) ??
      stringList(body.discreteStates) ??
      stringList(body.states) ??
      base?.defaultDiscreteStates ??
      ['AtHome', 'AtWork'];

    const initialHomeState =
      (typeof body.initialHomeState === 'string' && body.initialHomeState) ||
      (typeof body.homeState === 'string' && body.homeState) ||
      base?.initialHomeState ||
      states[0] ||
      'AtHome';

    const ioKeys =
      stringList(body.defaultCohesiveIoKeys) ??
      stringList(body.cohesiveIoKeys) ??
      (Array.isArray(body.pins)
        ? body.pins
            .map((p) => (isRecord(p) && typeof p.name === 'string' ? p.name : ''))
            .filter(Boolean)
        : undefined) ??
      base?.defaultCohesiveIoKeys ??
      [];

    const inPortsRaw = Array.isArray(body.defaultInPorts)
      ? body.defaultInPorts
      : Array.isArray(body.inPorts)
        ? body.inPorts
        : null;
    const defaultInPorts = inPortsRaw
      ? inPortsRaw.map(normalizePort).filter((p): p is SpatialPort => p !== null)
      : base?.defaultInPorts ?? [{ id: 'IN_EXEC', label: '▶ 工艺动作触发槽', type: 'SEQ' }];

    const outPortsRaw = Array.isArray(body.defaultOutPorts)
      ? body.defaultOutPorts
      : Array.isArray(body.outPorts)
        ? body.outPorts
        : null;
    const defaultOutPorts = outPortsRaw
      ? outPortsRaw.map(normalizePort).filter((p): p is SpatialPort => p !== null)
      : base?.defaultOutPorts ?? [{ id: 'OUT_DONE', label: '● 动作完成反馈 →', type: 'SEQ' }];

    const rawMethods = Array.isArray(body.radialMethods)
      ? body.radialMethods
      : Array.isArray(body.methods)
        ? body.methods
        : Array.isArray(body.actions)
          ? body.actions
          : null;

    const mergedMethods: RadialMethodOption[] = base ? base.radialMethods.map(cloneRadialOption) : [];
    if (rawMethods) {
      const normalized = rawMethods
        .map(normalizeRadialMethod)
        .filter((m): m is RadialMethodOption => m !== null);
      for (const incoming of normalized) {
        const existingIdx = mergedMethods.findIndex((m) => m.methodId === incoming.methodId);
        if (existingIdx >= 0) {
          mergedMethods[existingIdx] = incoming;
        } else {
          const guardIdx = mergedMethods.findIndex((m) => m.isGuard);
          if (guardIdx >= 0 && !incoming.isGuard) {
            mergedMethods.splice(guardIdx, 0, incoming);
          } else {
            mergedMethods.push(incoming);
          }
        }
      }
    }

    const supportsPartPresentSensor =
      typeof body.supportsPartPresentSensor === 'boolean'
        ? body.supportsPartPresentSensor
        : typeof body.hasPartPresentSensor === 'boolean'
          ? body.hasPartPresentSensor
          : base?.supportsPartPresentSensor ?? false;

    const isSensorOnly =
      typeof body.isSensorOnly === 'boolean' ? body.isSensorOnly : base?.isSensorOnly ?? false;

    merged[classKey] = {
      driverClass: (base?.driverClass ?? classKey) as DriverMotherClass,
      displayName,
      role,
      theme,
      description:
        (typeof body.description === 'string' && body.description) ||
        (typeof body.comment === 'string' && body.comment) ||
        base?.description ||
        displayName,
      supportsPartPresentSensor,
      isSensorOnly,
      defaultDiscreteStates: [...new Set(states)],
      initialHomeState,
      defaultCohesiveIoKeys: [...new Set(ioKeys)],
      defaultIoSummaryText:
        (typeof body.defaultIoSummaryText === 'string' && body.defaultIoSummaryText) ||
        (typeof body.ioSummaryText === 'string' && body.ioSummaryText) ||
        base?.defaultIoSummaryText ||
        '',
      defaultInPorts,
      defaultOutPorts,
      radialMethods: mergedMethods,
    };
  }

  return merged as MotherClassRegistry;
}
