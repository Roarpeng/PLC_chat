import { describe, expect, it } from 'vitest';
import {
  emptyFlow,
  newNode,
  type StationDesign,
} from '../../../workbench/stationDesign';
import type {
  AfStudioWorkspaceData,
  DriverMotherClass,
  SpatialInstanceNode,
} from '../afHyperGraph.types';
import {
  MOTHER_CLASS_PALETTE,
  MOTHER_CLASS_REGISTRY,
  getRadialMethodsForClass,
  parseReflectedRegistryJson,
} from '../motherClassRegistry';
import { createDefaultAfStudioWorkspace } from '../seedHyperGraphs';
import {
  hyperGraphStationToStationDesign,
  mapDriverToMotherClass,
  stationDesignToHyperGraphWorkspace,
} from '../stationDesignBridge';

const ALL_MOTHER_CLASSES: DriverMotherClass[] = [
  'FB_AF_AxisMotion',
  'FB_AF_Actuator2Pos',
  'FB_AF_Gripper',
  'FB_AF_VisionSensor',
  'STATION_INPUT_PORT',
  'STATION_OUTPUT_PORT',
];

describe('motherClassRegistry', () => {
  it('registers all 6 DriverMotherClass entries with valid defaults', () => {
    for (const cls of ALL_MOTHER_CLASSES) {
      const spec = MOTHER_CLASS_REGISTRY[cls];
      expect(spec).toBeDefined();
      expect(spec.driverClass).toBe(cls);
      expect(spec.defaultDiscreteStates.length).toBeGreaterThan(0);
      expect(spec.defaultDiscreteStates).toContain(spec.initialHomeState);
      expect(['klein', 'emerald', 'amber', 'vermilion', 'ink']).toContain(spec.theme);
    }
    expect(MOTHER_CLASS_REGISTRY.FB_AF_Gripper.supportsPartPresentSensor).toBe(true);
    expect(MOTHER_CLASS_REGISTRY.FB_AF_VisionSensor.isSensorOnly).toBe(true);
  });

  it('provides 4 palette items for the left-sidebar instantiator', () => {
    expect(MOTHER_CLASS_PALETTE).toHaveLength(4);
    expect(MOTHER_CLASS_PALETTE.map((item) => item.driverClass)).toEqual([
      'FB_AF_AxisMotion',
      'FB_AF_Actuator2Pos',
      'FB_AF_Gripper',
      'FB_AF_VisionSensor',
    ]);
  });

  it('returns radial craft methods aligned with v5 spec and adapts to node discrete states', () => {
    const axisMethods = getRadialMethodsForClass('FB_AF_AxisMotion');
    expect(axisMethods.map((m) => m.methodId)).toEqual([
      'MovePick',
      'MovePress',
      'MoveReject',
      'MoveHome',
      'GUARD',
    ]);
    expect(axisMethods.find((m) => m.isGuard)?.methodId).toBe('GUARD');

    const cylMethods = getRadialMethodsForClass('FB_AF_Actuator2Pos');
    expect(cylMethods.map((m) => m.methodId)).toEqual(['ExtendWork', 'RetractHome', 'GUARD']);

    const gripMethods = getRadialMethodsForClass('FB_AF_Gripper');
    expect(gripMethods.map((m) => m.methodId)).toEqual(['GripClose', 'GripOpen', 'GUARD']);

    const visionMethods = getRadialMethodsForClass('FB_AF_VisionSensor');
    expect(visionMethods.map((m) => m.methodId)).toEqual(['TrigInspect']);

    const outMethods = getRadialMethodsForClass('STATION_OUTPUT_PORT');
    expect(outMethods.map((m) => m.methodId)).toEqual(['ReleaseNext']);

    expect(getRadialMethodsForClass('STATION_INPUT_PORT')).toEqual([]);

    const customAxis: SpatialInstanceNode = {
      id: 'INST_CUSTOM_AXIS',
      role: 'ACTUATOR',
      title: '自定义伺服轴',
      driverClass: 'FB_AF_AxisMotion',
      instanceDb: 'DB_CustomAxis',
      position: { x: 100, y: 100 },
      isPinned: true,
      discreteStates: ['Pos_Home_0', 'Pos_Press_245', 'Pos_Weld_330'],
      initialHomeState: 'Pos_Home_0',
      cohesiveIoMap: {},
      inPorts: [{ id: 'IN_EXEC', label: '▶ 触发', type: 'SEQ' }],
      outPorts: [{ id: 'OUT_DONE', label: '● 完成', type: 'SEQ' }],
    };
    const customMethods = getRadialMethodsForClass('FB_AF_AxisMotion', customAxis);
    expect(customMethods.map((m) => m.targetDiscreteState)).toEqual([
      'Pos_Home_0',
      'Pos_Press_245',
      'Pos_Weld_330',
      'Pos_Home_0',
    ]);
    expect(customMethods[2].sclCommand).toBe('MoveAbs(330.0)');
    expect(customMethods[3].isGuard).toBe(true);
  });

  it('parses and merges reflected motherClassRegistry.json from C# AfLibraryReflector', () => {
    const reflectedPayload = JSON.stringify({
      tiaVersion: 'V17',
      libraryName: 'AF_GlobalLib_v5',
      classes: [
        {
          driverClass: 'FB_AF_AxisMotion',
          displayName: 'AF 伺服绝对定位母版 (TIA V17)',
          discreteStates: ['Pos_Home_0', 'Pos_Pick_120', 'Pos_Inspect_190', 'Pos_Press_245', 'Pos_Reject_410'],
          radialMethods: [
            {
              methodId: 'MoveInspect',
              label: '🔍 移至复检位 (190mm)',
              waitDesc: '到达190mm复检位',
              sclCmd: 'MoveAbs(190.0)',
              targetState: 'Pos_Inspect_190',
            },
          ],
        },
        {
          driverClass: 'FB_AF_RotaryTable',
          displayName: '伺服分度转台母版',
          theme: 'klein',
          states: ['Station_0', 'Station_90', 'Station_180', 'Station_270'],
          homeState: 'Station_0',
        },
      ],
    });

    const merged = parseReflectedRegistryJson(reflectedPayload);
    expect(merged.FB_AF_AxisMotion.displayName).toBe('AF 伺服绝对定位母版 (TIA V17)');
    expect(merged.FB_AF_AxisMotion.defaultDiscreteStates).toContain('Pos_Inspect_190');
    const axisMethodIds = merged.FB_AF_AxisMotion.radialMethods.map((m) => m.methodId);
    expect(axisMethodIds).toContain('MoveInspect');
    expect(axisMethodIds[axisMethodIds.length - 1]).toBe('GUARD');
    // Built-in classes remain intact
    expect(merged.FB_AF_Actuator2Pos.initialHomeState).toBe('AtHome');
    expect(merged.FB_AF_RotaryTable.displayName).toBe('伺服分度转台母版');

    // Original registry is not mutated
    expect(MOTHER_CLASS_REGISTRY.FB_AF_AxisMotion.radialMethods.some((m) => m.methodId === 'MoveInspect')).toBe(false);

    expect(() => parseReflectedRegistryJson('{bad-json')).toThrow(/Invalid reflected/);
  });
});

describe('seedHyperGraphs (AssyLine_01)', () => {
  it('creates complete L1 and L2 hypergraphs for ST10, ST20, and ST30', () => {
    const ws = createDefaultAfStudioWorkspace();
    expect(ws.projectName).toBe('AssyLine_01');
    expect(ws.projectGraph.stations.map((s) => s.stationId)).toEqual(['ST10', 'ST20', 'ST30']);
    expect(ws.projectGraph.edges.map((e) => e.id)).toEqual(['E_L1_1', 'E_L1_2', 'E_L1_3']);

    // ST10 assertions
    const st10 = ws.stationGraphs.ST10;
    expect(st10.spatialNodes.map((n) => n.id)).toEqual([
      'INST_ST10_STOP',
      'INST_ST10_TRANS',
      'BOUND_OUT_ST10',
    ]);
    const st10Trans = st10.spatialNodes.find((n) => n.id === 'INST_ST10_TRANS')!;
    expect(st10Trans.isPhysicalRootCause).toBe(true);
    expect(st10Trans.cohesiveIoMap).toEqual({
      diHome: '%I0.4',
      diWork: '%I0.5',
      cabinetTerminal: 'X12:04',
    });
    expect(st10.guardEdges[0].id).toBe('G_ST10_OUT');
    expect(st10.temporalSteps.map((s) => s.stepNo)).toEqual([10, 20]);

    // ST20 assertions
    const st20 = ws.stationGraphs.ST20;
    expect(st20.spatialNodes.map((n) => n.id)).toEqual([
      'BOUND_IN_ST20',
      'INST_ST20_GRIP',
      'INST_ST20_CAM',
      'INST_ST20_X',
      'INST_ST20_Z',
      'BOUND_OUT_ST20',
    ]);
    const grip = st20.spatialNodes.find((n) => n.id === 'INST_ST20_GRIP')!;
    expect(grip.hasPartPresentSensor).toBe(true);
    const axisX = st20.spatialNodes.find((n) => n.id === 'INST_ST20_X')!;
    expect(axisX.driverClass).toBe('FB_AF_AxisMotion');
    expect(axisX.discreteStates).toEqual([
      'Pos_Home_0',
      'Pos_Pick_120',
      'Pos_Press_245',
      'Pos_Reject_410',
    ]);
    const cylZ = st20.spatialNodes.find((n) => n.id === 'INST_ST20_Z')!;
    expect(cylZ.driverClass).toBe('FB_AF_Actuator2Pos');
    expect(cylZ.discreteStates).toEqual(['AtHome', 'AtWork']);

    expect(st20.guardEdges.map((g) => g.diagCodeHex)).toEqual(['16#0201', '16#0203']);
    const crossGuard = st20.guardEdges.find((g) => g.id === 'G_ST20_ST10_TO_X')!;
    expect(crossGuard.crossStationRef).toEqual({
      upstreamStationId: 'ST10',
      upstreamInstanceId: 'INST_ST10_TRANS',
      upstreamPortId: 'OUT_HOME_DI',
      physicalTerminal: '%I0.4',
      cabinetWireTag: 'X12:04',
      l1EdgeId: 'E_L1_2',
    });

    expect(st20.temporalSteps.map((s) => s.stepNo)).toEqual([10, 20, 30, 40, 50]);
    const step30 = st20.temporalSteps.find((s) => s.stepNo === 30)!;
    expect(step30.requiresGuardNodeIds).toEqual(['INST_ST20_Z']);
    const step50 = st20.temporalSteps.find((s) => s.stepNo === 50)!;
    expect(step50.invocations.map((i) => [i.targetNodeId, i.methodId])).toEqual([
      ['INST_ST20_Z', 'RetractHome'],
      ['BOUND_OUT_ST20', 'ReleaseNext'],
    ]);

    // ST30 assertions
    const st30 = ws.stationGraphs.ST30;
    expect(st30.spatialNodes.map((n) => n.id)).toEqual([
      'BOUND_IN_ST30',
      'INST_ST30_LASER',
      'BOUND_OUT_ST30',
    ]);
    expect(st30.temporalSteps.map((s) => s.stepNo)).toEqual([10, 20]);
  });

  it('returns an isolated deep clone on each call', () => {
    const a = createDefaultAfStudioWorkspace();
    const b = createDefaultAfStudioWorkspace();
    a.projectName = 'Mutated';
    a.stationGraphs.ST20.spatialNodes[1].title = 'Changed';
    a.stationGraphs.ST20.guardEdges.pop();

    expect(b.projectName).toBe('AssyLine_01');
    expect(b.stationGraphs.ST20.spatialNodes[1].title).toBe('1号平行夹爪');
    expect(b.stationGraphs.ST20.guardEdges).toHaveLength(2);
  });
});

describe('stationDesignBridge', () => {
  function sampleStationDesign(): StationDesign {
    const devSourceNode = { ...newNode('device'), id: 'src_node', device_id: 'cyl_trans', name: '移载缸' };
    const ifaceNode = { ...newNode('interface'), id: 'if_st10' };
    const act10 = {
      ...newNode('action'),
      id: 'act_st10_1',
      name: '移载缸伸出',
      actions: [{ device_id: 'cyl_trans', action_id: 'extend' }],
      completion: [{ device_id: 'cyl_trans', port: 'extended', value: true }],
    };
    const act10Retract = {
      ...newNode('action'),
      id: 'act_st10_2',
      name: '移载缸缩回',
      actions: [{ device_id: 'cyl_trans', action_id: 'retract' }],
      completion: [{ device_id: 'cyl_trans', port: 'retracted', value: true }],
    };

    const st10 = {
      id: 'ST10',
      name: 'ST10 来料站',
      devices: [
        {
          id: 'cyl_trans',
          name: '来料移载气缸',
          driver: 'cylinder',
          bindings: { retracted: 'sig_i04', extended: 'sig_i05' },
          timeout_ms: 2000,
        },
      ],
      public_ports: [{ id: 'home_ok', name: '移载原位', direction: 'output' as const, type: 'BOOL' as const }],
      flow: {
        start: 'act_st10_1',
        nodes: [act10, act10Retract, devSourceNode, ifaceNode],
        edges: [{ id: 'e10_1', from_id: 'act_st10_1', to_id: 'act_st10_2', outcome: 'next' as const }],
        wires: [{ id: 'w_st10_iface', from_id: 'src_node', from_port: 'fb_retracted', to_id: 'if_st10', to_port: 'home_ok' }],
      },
    };

    const act20Pick = {
      ...newNode('action'),
      id: 'act_st20_1',
      name: '压装缸下压',
      actions: [{ device_id: 'cyl_z', action_id: 'extend' }],
      position: { x: 400, y: 260 },
    };
    const act20Move = {
      ...newNode('action'),
      id: 'act_st20_2',
      name: 'X轴移至压装位',
      actions: [{ device_id: 'axis_x', action_id: 'work' }],
      position: { x: 400, y: 90 },
    };
    const act20Retract = {
      ...newNode('action'),
      id: 'act_st20_3',
      name: '压装缸缩回原位',
      actions: [{ device_id: 'cyl_z', action_id: 'retract' }],
    };

    const st20 = {
      id: 'ST20',
      name: 'ST20 压装站',
      devices: [
        { id: 'axis_x', name: 'X轴伺服', driver: 'servo', bindings: { in_position: 'sig_i11' }, timeout_ms: 5000 },
        { id: 'cyl_z', name: 'Z轴压装缸', driver: 'cylinder', bindings: { retracted: 'sig_i10' }, timeout_ms: 2000 },
      ],
      public_ports: [{ id: 'permit_x', name: 'ST10原位许可', direction: 'input' as const, type: 'BOOL' as const }],
      interlocks: [
        {
          id: 'g_local_z',
          name: 'Z轴顶升原位保护',
          device_id: 'cyl_z',
          port: 'retracted',
          value: true,
          human_text: 'Z轴必须处于顶升原位才允许X轴横移',
          block_code: '#0201',
          active: true,
        },
        {
          id: 'g_cross_st10',
          name: '上游移载缸原位保护',
          device_id: null,
          port: null,
          value: true,
          human_text: '上游 ST10 移载气缸必须回到原位',
          block_code: '#0203',
          active: true,
          public_port: 'permit_x',
          source_station_id: 'ST10',
          cross_station: true,
        },
      ],
      flow: {
        start: 'act_st20_1',
        nodes: [act20Pick, act20Move, act20Retract],
        edges: [
          { id: 'e20_1', from_id: 'act_st20_1', to_id: 'act_st20_2', outcome: 'next' as const },
          { id: 'e20_2', from_id: 'act_st20_2', to_id: 'act_st20_3', outcome: 'next' as const },
        ],
      },
    };

    return {
      version: 1,
      name: 'BridgeTestLine',
      hardware: {
        cpu: 'CPU 1515-2 PN',
        network: 'PROFINET',
        modules: [{ id: 'X12', name: 'DI16', slot: 1, kind: 'DI' }],
        signals: [
          { id: 'sig_i04', name: 'ST10原位', module_id: 'X12', direction: 'input', address: '%I0.4' },
          { id: 'sig_i05', name: 'ST10动位', module_id: 'X12', direction: 'input', address: '%I0.5' },
          { id: 'sig_i10', name: 'ST20_Z原位', module_id: 'X12', direction: 'input', address: '%I10.0' },
          { id: 'sig_i11', name: 'ST20_X到位', module_id: 'X12', direction: 'input', address: '%I11.1' },
        ],
      },
      stations: [st10, st20],
      flow: {
        start: 'n_st10',
        nodes: [
          { ...newNode('station'), id: 'n_st10', name: st10.name, station_ids: ['ST10'], position: { x: 80, y: 120 } },
          { ...newNode('station'), id: 'n_st20', name: st20.name, station_ids: ['ST20'], position: { x: 460, y: 120 } },
        ],
        edges: [{ id: 'e_l1_seq', from_id: 'n_st10', to_id: 'n_st20', outcome: 'done' }],
        wires: [{ id: 'w_l1_guard', from_id: 'n_st10', from_port: 'home_ok', to_id: 'n_st20', to_port: 'permit_x' }],
      },
    };
  }

  it('maps driver names to DriverMotherClass', () => {
    expect(mapDriverToMotherClass('servo')).toBe('FB_AF_AxisMotion');
    expect(mapDriverToMotherClass('cylinder')).toBe('FB_AF_Actuator2Pos');
    expect(mapDriverToMotherClass('pneumatic_gripper')).toBe('FB_AF_Gripper');
    expect(mapDriverToMotherClass('vision')).toBe('FB_AF_VisionSensor');
    expect(mapDriverToMotherClass('photoelectric')).toBe('FB_AF_VisionSensor');
  });

  it('converts StationDesign into orthogonal hypergraph without duplicating reused actuators', () => {
    const design = sampleStationDesign();
    const ws = stationDesignToHyperGraphWorkspace(design);

    expect(ws.projectName).toBe('BridgeTestLine');
    expect(ws.projectGraph.stations).toHaveLength(2);
    expect(ws.projectGraph.edges.some((e) => e.kind === 'GUARD' && e.diagCodeHex === '16#0203')).toBe(true);

    // ST10: cyl_trans is invoked twice (extend & retract) but remains 1 unique spatial node
    const st10 = ws.stationGraphs.ST10;
    const st10Actuators = st10.spatialNodes.filter((n) => n.role === 'ACTUATOR');
    expect(st10Actuators).toHaveLength(1);
    expect(st10Actuators[0].cohesiveIoMap.retracted).toBe('%I0.4');
    expect(st10.temporalSteps).toHaveLength(2);
    expect(st10.guardEdges.some((g) => g.toNode === 'BOUND_OUT_ST10')).toBe(true);

    // ST20: cyl_z invoked twice -> 1 spatial node, cross-station guard traced to %I0.4
    const st20 = ws.stationGraphs.ST20;
    const st20Actuators = st20.spatialNodes.filter((n) => n.role === 'ACTUATOR');
    expect(st20Actuators).toHaveLength(2);
    expect(st20.temporalSteps).toHaveLength(3);

    const localGuard = st20.guardEdges.find((g) => g.id === 'g_local_z')!;
    expect(localGuard.fromNode).toBe('cyl_z');
    expect(localGuard.toNode).toBe('axis_x');
    expect(localGuard.diagCodeHex).toBe('16#0201');

    const crossGuard = st20.guardEdges.find((g) => g.id === 'g_cross_st10')!;
    expect(crossGuard.crossStationRef).toEqual({
      upstreamStationId: 'ST10',
      upstreamInstanceId: 'cyl_trans',
      upstreamPortId: 'OUT_retracted',
      physicalTerminal: '%I0.4',
      cabinetWireTag: 'X12:%I0.4',
      l1EdgeId: 'w_l1_guard',
    });
  });

  it('round-trips AfStudioWorkspaceData to StationDesign and back cleanly', () => {
    const seedWs: AfStudioWorkspaceData = createDefaultAfStudioWorkspace();
    const design = hyperGraphStationToStationDesign(seedWs);

    expect(design.version).toBe(1);
    expect(design.name).toBe('AssyLine_01');
    expect(design.stations.map((s) => s.id)).toEqual(['ST10', 'ST20', 'ST30']);
    expect(design.hardware.signals.some((s) => s.address === '%I0.4')).toBe(true);
    expect(design.stations[1].interlocks?.map((i) => i.block_code)).toEqual(['#0201', '#0203']);

    const reconverted = stationDesignToHyperGraphWorkspace(design);
    expect(Object.keys(reconverted.stationGraphs)).toEqual(['ST10', 'ST20', 'ST30']);
    const st20Cross = reconverted.stationGraphs.ST20.guardEdges.find((g) => g.crossStationRef);
    expect(st20Cross?.crossStationRef?.upstreamStationId).toBe('ST10');
    expect(st20Cross?.crossStationRef?.physicalTerminal).toBe('%I0.4');
    expect(st20Cross?.diagCodeHex).toBe('16#0203');

    // Verify custom StationDesign round-trip preserves devices and steps
    const sample = sampleStationDesign();
    const ws1 = stationDesignToHyperGraphWorkspace(sample);
    const design2 = hyperGraphStationToStationDesign(ws1, sample);
    const ws2 = stationDesignToHyperGraphWorkspace(design2);
    expect(ws2.stationGraphs.ST20.spatialNodes.filter((n) => n.role === 'ACTUATOR').map((n) => n.id)).toEqual([
      'axis_x',
      'cyl_z',
    ]);
    expect(ws2.stationGraphs.ST20.temporalSteps).toHaveLength(3);
  });
});
