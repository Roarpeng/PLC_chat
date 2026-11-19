import { describe, expect, it } from 'vitest';
import type { AfStudioWorkspaceData, SpatialInstanceNode } from './afHyperGraph.types';
import { bindingError, cmBindingStatus, cmProfiles, cmPresetWait, defaultCmControl, parseFieldAddress, pointError, type CmDeviceProfile } from './fieldIo';
import { getRadialMethodsForClass } from './motherClassRegistry';
import { cloneStationGraph } from './stationWorkspace';

const node = (id: string, station: string, fieldBindings = {}): SpatialInstanceNode => ({
  id, instanceDb: `DB_${station}_${id}`, title: id, cmProfile: 'Cylinder2Pos@1',
  driverClass: 'FB_AF_Actuator2Pos', role: 'ACTUATOR', fieldBindings, cohesiveIoMap: {},
  initialHomeState: 'AtHome', discreteStates: ['AtHome', 'AtWork'],
  position: { x: 0, y: 0 }, isPinned: false, inPorts: [], outPorts: [],
});
const workspace: AfStudioWorkspaceData = {
  projectName: 'test', projectGraph: { stations: [], edges: [] },
  fieldIoPoints: [
    { id: 'valve', name: '动作阀', address: '%Q0.1', type: 'BOOL' },
    { id: 'home', name: '原位', address: '%I3.2', type: 'BOOL' },
    { id: 'pressure', name: '压力', address: '%IW4', type: 'INT' },
  ],
  stationGraphs: {
    A: { stationId: 'A', stationName: 'A', spatialNodes: [node('first', 'A', { doWork: 'valve' })], temporalSteps: [], guardEdges: [] },
    B: { stationId: 'B', stationName: 'B', spatialNodes: [node('second', 'B')], temporalSteps: [], guardEdges: [] },
  },
};

describe('typed AF field I/O', () => {
  it('exposes independent cylinder commands and directional completion conditions', () => {
    const cylinder = { ...node('cylinder', 'A'), ...defaultCmControl('Cylinder2Pos@1') };
    const actions = getRadialMethodsForClass(cylinder.driverClass, cylinder).filter((method) => !method.isGuard);
    expect(actions.map((method) => [method.label, method.targetPortId, cmPresetWait(cylinder, method)]))
      .toEqual([['伸出', 'IN_EXTEND', '#cylinder.o_bAtWork'], ['缩回', 'IN_RETRACT', '#cylinder.o_bAtHome']]);
    expect(cylinder.outPorts.map(({ id }) => id)).toContain('OUT_EXTENDED');
    expect(cylinder.outPorts.map(({ id }) => id)).toContain('OUT_RETRACTED');
  });

  it('supplies operational ports for each CM profile and keeps digital sensing passive', () => {
    for (const profile of Object.keys(cmProfiles) as CmDeviceProfile[]) {
      const spec = cmProfiles[profile];
      const control = defaultCmControl(profile);
      expect(control.outPorts.length).toBeGreaterThan(0);
      expect(control.inPorts.filter(({ type }) => type === 'SEQ').map(({ id }) => id))
        .toEqual(spec.actions.map(({ targetPortId }) => targetPortId));
      expect(spec.actions.every(({ feedbackMember }) => Boolean(feedbackMember))).toBe(true);
    }
    expect(defaultCmControl('DigitalInput@1').inPorts).toEqual([]);
    expect(cmProfiles['Vacuum@1'].driver).not.toBe(cmProfiles['Gripper@1'].driver);
  });
  it('normalizes Siemens bit aliases and rejects overlapping bit/byte or word ranges', () => {
    expect(parseFieldAddress(' qx00.1 ', 'BOOL')?.address).toBe('%Q0.1');
    expect(parseFieldAddress('%I0.8', 'BOOL')).toBeUndefined();
    expect(pointError(workspace, { id: 'dup', name: 'dup', address: '%QB0', type: 'BYTE' })).toContain('重叠');
    expect(pointError(workspace, { id: 'dup', name: 'dup', address: '%I5.7', type: 'BOOL' })).toContain('重叠');
  });

  it('rejects incompatible direction, type and duplicate output use across stations', () => {
    const first = workspace.stationGraphs.A.spatialNodes[0];
    const second = workspace.stationGraphs.B.spatialNodes[0];
    expect(bindingError(workspace, 'B', second, 'diHome', 'valve')).toContain('不匹配');
    expect(bindingError(workspace, 'B', second, 'diHome', 'pressure')).toContain('不匹配');
    expect(bindingError(workspace, 'B', second, 'doWork', 'valve')).toContain('占用');
    expect(bindingError(workspace, 'A', first, 'doWork', 'valve')).toBeUndefined();
    expect(bindingError(workspace, 'B', second, 'diHome', 'home')).toBeUndefined();
  });

  it('copies the CM driver reference with a new instance and empty bindings', () => {
    const source = workspace.stationGraphs.A;
    const clone = cloneStationGraph(source, 'C', 'C');
    expect(clone.spatialNodes[0]).toMatchObject({
      driverClass: 'FB_AF_Actuator2Pos', cmProfile: 'Cylinder2Pos@1', fieldBindings: {},
    });
    expect(clone.spatialNodes[0].instanceDb).not.toBe(source.spatialNodes[0].instanceDb);
    expect(cmBindingStatus(clone)).toBe('待绑定现场 I/O');
  });
});
