import { describe, expect, it } from 'vitest';
import type { HomingSynthesisResult, StationHyperGraph } from '../../ir/afHyperGraph.types';
import { createDefaultAfStudioWorkspace } from '../../ir/seedHyperGraphs';
import {
  computeBlockHashes,
  computeMerkleSyncManifest,
  extractInterfaceSignature,
  normalizeSclAst,
  sha256Hex,
} from '../merkleAstHasher';
import { compileStationHyperGraph } from '../multiTargetSclGen';

describe('merkleAstHasher', () => {
  it('computes NIST FIPS 180-4 SHA-256 test vectors synchronously without node:crypto', () => {
    expect(sha256Hex('abc')).toBe(
      'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'
    );
    expect(sha256Hex('')).toBe(
      'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
    );
    expect(
      sha256Hex('abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq')
    ).toBe('248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1');

    // Verify manual UTF-8 fallback produces identical hashes for multi-byte CJK & emoji
    const unicodeSample = 'ST20 · 视觉引导压装站 🛡️ %I0.4';
    const withTextEncoder = sha256Hex(unicodeSample);
    const originalTextEncoder = globalThis.TextEncoder;
    const g = globalThis as unknown as { TextEncoder?: typeof TextEncoder };
    try {
      g.TextEncoder = undefined;
      expect(sha256Hex(unicodeSample)).toBe(withTextEncoder);
    } finally {
      g.TextEncoder = originalTextEncoder;
    }
  });

  it('normalizes SCL AST while preserving logic comments and stripping decorative timestamps', () => {
    const sclA = [
      '// Timestamp: 2026-11-18T12:00:00Z   ',
      '(* Generated at: 2026-11-18 12:00 *)',
      '//   ',
      '(*   *)',
      'FUNCTION_BLOCK "FB_Demo"   ',
      'VAR_INPUT',
      '   i_bStart : Bool; // 启动触发',
      'END_VAR',
      '',
      '',
      'BEGIN',
      '   // 实际工艺逻辑注释',
      '   #q_bDone := #i_bStart;   ',
      'END_FUNCTION_BLOCK',
      '',
    ].join('\r\n');

    const sclB = [
      '(* 更新时间戳 导出时间: 2099-01-01 00:00 *)',
      'FUNCTION_BLOCK "FB_Demo"',
      'VAR_INPUT',
      '   i_bStart : Bool; // 启动触发',
      'END_VAR',
      '',
      'BEGIN',
      '   // 实际工艺逻辑注释',
      '   #q_bDone := #i_bStart;',
      'END_FUNCTION_BLOCK',
    ].join('\n');

    expect(normalizeSclAst(sclA)).toBe(normalizeSclAst(sclB));
    expect(normalizeSclAst(sclA)).toContain('// 实际工艺逻辑注释');
    expect(normalizeSclAst(sclA)).not.toContain('Timestamp');
    expect(computeBlockHashes(sclA)).toEqual(computeBlockHashes(sclB));
  });

  it('extracts canonical VAR_INPUT/VAR_OUTPUT/VAR_IN_OUT/VAR interface signature', () => {
    const scl = `
      FUNCTION_BLOCK "FB_Test"
      VAR_INPUT
         i_bRun : Bool;
      END_VAR
      VAR_OUTPUT
         q_bOk : Bool;
      END_VAR
      VAR_IN_OUT
         io_Axis : Int;
      END_VAR
      VAR_TEMP
         tmpIdx : Int;
      END_VAR
      VAR
         statStep : Int;
      END_VAR
      BEGIN
         #statStep := 10;
      END_FUNCTION_BLOCK
    `;

    const sig = extractInterfaceSignature(scl);
    expect(sig).toContain('VAR_INPUT');
    expect(sig).toContain('i_bRun : Bool;');
    expect(sig).toContain('VAR_OUTPUT');
    expect(sig).toContain('VAR_IN_OUT');
    expect(sig).toContain('VAR');
    expect(sig).toContain('statStep : Int;');
    expect(sig).not.toContain('VAR_TEMP');
    expect(sig).not.toContain('tmpIdx');
    expect(sig).not.toContain('#statStep := 10;');

    const hashes = computeBlockHashes(scl);
    expect(hashes.merkleHash).toMatch(/^[0-9a-f]{8}$/);
    expect(hashes.fullSha256).toMatch(/^[0-9a-f]{64}$/);
    expect(hashes.fullSha256.startsWith(hashes.merkleHash)).toBe(true);
    expect(hashes.interfaceHash).toMatch(/^[0-9a-f]{16}$/);
  });
});

describe('multiTargetSclGen & incremental Merkle diff', () => {
  function getSt20(): StationHyperGraph {
    return createDefaultAfStudioWorkspace().stationGraphs.ST20;
  }

  it('compiles all 4 SCL blocks with full syntax integrity including S50 dual concurrent invocations', () => {
    const st20 = getSt20();
    const artifacts = compileStationHyperGraph(st20);

    expect(artifacts.map((a) => [a.blockName, a.blockType])).toEqual([
      ['DB_ST20_Instances', 'DB'],
      ['FB_ST20_AutoSeq', 'FB'],
      ['FB_ST20_HomeSeq', 'FB'],
      ['FC_ST20_GuardDiag', 'FC'],
    ]);

    const [dbBlock, autoBlock, homeBlock, diagBlock] = artifacts;

    // 1) DB_ST20_Instances
    expect(dbBlock.sclCode).toContain('DATA_BLOCK "DB_ST20_Instances"');
    expect(dbBlock.sclCode).toContain('DB_ST20_Gripper1 : "FB_AF_Gripper";');
    expect(dbBlock.sclCode).toContain('DB_ST20_VisionCam : "FB_AF_VisionSensor";');
    expect(dbBlock.sclCode).toContain('DB_ST20_AxisX : "FB_AF_AxisMotion";');
    expect(dbBlock.sclCode).toContain('DB_ST20_CylZ : "FB_AF_Actuator2Pos";');
    expect(dbBlock.sclCode).toContain('%Q10.2');
    expect(dbBlock.sclCode).toContain('%I10.0');
    expect(dbBlock.sclCode).toContain('END_DATA_BLOCK');

    // 2) FB_ST20_AutoSeq (including ascending CASE steps, guard pins, and S50 dual concurrent invocations)
    expect(autoBlock.instanceDbName).toBe('DB_ST20_Instances');
    expect(autoBlock.sclCode).toContain('FUNCTION_BLOCK "FB_ST20_AutoSeq"');
    expect(autoBlock.sclCode).toContain('i_bGuard_G_ST20_Z_TO_X : Bool');
    expect(autoBlock.sclCode).toContain('i_bGuard_G_ST20_ST10_TO_X : Bool');
    expect(autoBlock.sclCode).toContain('CASE #statStep OF');
    expect(autoBlock.sclCode).toContain('10: // [来料夹紧电芯');
    expect(autoBlock.sclCode).toContain('30: // [X轴横移至压装位');
    expect(autoBlock.sclCode).toContain('16#0201');
    expect(autoBlock.sclCode).toContain('16#0203');
    expect(autoBlock.sclCode).toContain('50: // [Z轴回升并放行下游');
    expect(autoBlock.sclCode).toContain('#DB_ST20_CylZ.RetractHome();');
    expect(autoBlock.sclCode).toContain('o_bCycleDone := TRUE;');
    expect(autoBlock.sclCode).toContain(
      '("DB_ST20_CylZ".o_bAtHome) AND ("DB_ST20_CylZ".o_bAtHome AND i_bDownstreamAck)'
    );
    expect(autoBlock.sclCode).toContain('END_FUNCTION_BLOCK');

    // 3) FB_ST20_HomeSeq (Kahn topological layers + gripper part-present protection)
    expect(homeBlock.instanceDbName).toBe('DB_ST20_Instances');
    expect(homeBlock.sclCode).toContain('FUNCTION_BLOCK "FB_ST20_HomeSeq"');
    expect(homeBlock.sclCode).toContain('CASE #statHomeStep OF');
    expect(homeBlock.sclCode).toContain('10: // [Kahn 拓扑归航层 Layer 1]');
    expect(homeBlock.sclCode).toContain('"DB_ST20_Gripper1".i_bPartPresent');
    expect(homeBlock.sclCode).toContain('"DB_ST20_Gripper1".i_bCmdMaintainGrip := TRUE;');
    expect(homeBlock.sclCode).toContain('"DB_ST20_CylZ".i_bCmdHome := TRUE;');
    expect(homeBlock.sclCode).toContain('20: // [Kahn 拓扑归航层 Layer 2]');
    expect(homeBlock.sclCode).toContain('"DB_ST20_AxisX".i_bCmdHome := TRUE;');
    expect(homeBlock.sclCode).toContain('END_FUNCTION_BLOCK');

    // 4) FC_ST20_GuardDiag (REGION + diag codes + crossStationRef provenance)
    expect(diagBlock.sclCode).toContain('FUNCTION "FC_ST20_GuardDiag" : Word');
    expect(diagBlock.sclCode).toContain('REGION Safety_Invariants_And_Diagnostic_Bitmask');
    expect(diagBlock.sclCode).toContain('16#0201');
    expect(diagBlock.sclCode).toContain('16#0203');
    expect(diagBlock.sclCode).toContain('"DB_ST20_AxisX".i_bInterlockOK := FALSE;');
    expect(diagBlock.sclCode).toContain('"DB_ST20_AxisX".o_wBlockDiagCode := 16#0203;');
    expect(diagBlock.sclCode).toContain('ST10');
    expect(diagBlock.sclCode).toContain('INST_ST10_TRANS');
    expect(diagBlock.sclCode).toContain('%I0.4');
    expect(diagBlock.sclCode).toContain('X12:04');
    expect(diagBlock.sclCode).toContain('END_REGION');

    for (const block of artifacts) {
      expect(block.merkleHash).toMatch(/^[0-9a-f]{8}$/);
      expect(block.fullSha256).toMatch(/^[0-9a-f]{64}$/);
      expect(block.interfaceHash).toMatch(/^[0-9a-f]{16}$/);
    }
  });

  it('guarantees 100% identical block hashes when spatial node UI coordinates move', () => {
    const original = getSt20();
    const moved = getSt20();
    moved.spatialNodes.forEach((node, idx) => {
      node.position = {
        x: node.position.x + 175 + idx * 13,
        y: node.position.y - 42 + idx * 7,
      };
      node.isPinned = !node.isPinned;
    });

    const artifactsA = compileStationHyperGraph(original);
    const artifactsB = compileStationHyperGraph(moved);

    expect(artifactsB.map((a) => a.merkleHash)).toEqual(artifactsA.map((a) => a.merkleHash));
    expect(artifactsB.map((a) => a.fullSha256)).toEqual(artifactsA.map((a) => a.fullSha256));
    expect(artifactsB.map((a) => a.interfaceHash)).toEqual(
      artifactsA.map((a) => a.interfaceHash)
    );
    expect(artifactsB.map((a) => a.sclCode)).toEqual(artifactsA.map((a) => a.sclCode));

    const prevMap = Object.fromEntries(
      artifactsA.map((a) => [
        `${original.stationId}::${a.blockName}`,
        { merkleHash: a.merkleHash, interfaceHash: a.interfaceHash },
      ])
    );
    const manifest = computeMerkleSyncManifest(moved.stationId, artifactsB, prevMap);
    expect(manifest.dirtyCount).toBe(0);
    expect(manifest.unchangedCount).toBe(4);
    expect(manifest.estimatedSyncSeconds).toBe(0);
    expect(manifest.entries.every((e) => e.status === 'UNCHANGED')).toBe(true);
  });

  it('marks only FB_ST20_AutoSeq as DIRTY when a single step action changes', () => {
    const baseline = getSt20();
    const baselineArtifacts = compileStationHyperGraph(baseline);
    const prevHashes = Object.fromEntries(
      baselineArtifacts.map((a) => [
        a.blockName,
        { merkleHash: a.merkleHash, interfaceHash: a.interfaceHash },
      ])
    );

    const edited = getSt20();
    const step30 = edited.temporalSteps.find((s) => s.stepNo === 30)!;
    step30.invocations[0].sclStatement = '#DB_ST20_AxisX.MoveAbs(248.5);';
    step30.invocations[0].waitPredicateScl =
      '"DB_ST20_AxisX".o_bInPos AND (ABS("DB_ST20_AxisX".o_rActPos - 248.5) < 0.05)';

    const editedArtifacts = compileStationHyperGraph(edited);
    const manifest = computeMerkleSyncManifest(edited.stationId, editedArtifacts, prevHashes);

    expect(manifest.dirtyCount).toBe(1);
    expect(manifest.unchangedCount).toBe(3);
    expect(manifest.estimatedSyncSeconds).toBe(1.18);

    const statusByName = Object.fromEntries(
      manifest.entries.map((e) => [e.blockName, e.status])
    );
    expect(statusByName).toEqual({
      DB_ST20_Instances: 'UNCHANGED',
      FB_ST20_AutoSeq: 'DIRTY',
      FB_ST20_HomeSeq: 'UNCHANGED',
      FC_ST20_GuardDiag: 'UNCHANGED',
    });
  });

  it('cascades DB block to DIRTY with timestamp refresh reason when FB VAR_INPUT changes', () => {
    const baseline = getSt20();
    const baselineArtifacts = compileStationHyperGraph(baseline);
    const prevHashes = Object.fromEntries(
      baselineArtifacts.map((a) => [
        `${baseline.stationId}::${a.blockName}`,
        { merkleHash: a.merkleHash, interfaceHash: a.interfaceHash },
      ])
    );

    // Edit FB_ST20_AutoSeq VAR_INPUT while keeping DB_ST20_Instances SCL untouched
    const mutatedArtifacts = baselineArtifacts.map((artifact) => {
      if (artifact.blockName !== 'FB_ST20_AutoSeq') return artifact;
      const modifiedScl = artifact.sclCode.replace(
        'i_bInterlockOK : Bool := TRUE;',
        'i_bInterlockOK : Bool := TRUE;\n   i_bSafetyDoorClosed : Bool := TRUE;'
      );
      return {
        ...artifact,
        sclCode: modifiedScl,
        ...computeBlockHashes(modifiedScl),
      };
    });

    const manifest = computeMerkleSyncManifest('ST20', mutatedArtifacts, prevHashes);

    expect(manifest.dirtyCount).toBe(2);
    expect(manifest.unchangedCount).toBe(2);
    expect(manifest.estimatedSyncSeconds).toBe(2.36);

    const statusByName = Object.fromEntries(
      manifest.entries.map((e) => [e.blockName, e.status])
    );
    expect(statusByName).toEqual({
      DB_ST20_Instances: 'DIRTY',
      FB_ST20_AutoSeq: 'DIRTY',
      FB_ST20_HomeSeq: 'UNCHANGED',
      FC_ST20_GuardDiag: 'UNCHANGED',
    });

    const dbEntry = manifest.entries.find((e) => e.blockName === 'DB_ST20_Instances')!;
    expect(dbEntry.reason).toContain('接口时间戳刷新：需连带重建背景 DB');

    // Also verify explicit custom artifact.instanceDbName cascade
    const customIdbScl = 'DATA_BLOCK "IDB_Custom" "FB_Custom"\nBEGIN\nEND_DATA_BLOCK';
    const fbV1Scl = 'FUNCTION_BLOCK "FB_Custom"\nVAR_INPUT\n   i_a : Bool;\nEND_VAR\nBEGIN\nEND_FUNCTION_BLOCK';
    const fbV2Scl = 'FUNCTION_BLOCK "FB_Custom"\nVAR_INPUT\n   i_a : Bool;\n   i_b : Bool;\nEND_VAR\nBEGIN\nEND_FUNCTION_BLOCK';
    const customV1 = [
      {
        blockName: 'FB_Custom',
        blockType: 'FB' as const,
        stationId: 'ST99',
        sclCode: fbV1Scl,
        instanceDbName: 'IDB_Custom',
        ...computeBlockHashes(fbV1Scl),
      },
      {
        blockName: 'IDB_Custom',
        blockType: 'DB' as const,
        stationId: 'ST99',
        sclCode: customIdbScl,
        ...computeBlockHashes(customIdbScl),
      },
    ];
    const customPrev = Object.fromEntries(
      customV1.map((b) => [b.blockName, { merkleHash: b.merkleHash, interfaceHash: b.interfaceHash }])
    );
    const customV2 = [
      {
        ...customV1[0],
        sclCode: fbV2Scl,
        ...computeBlockHashes(fbV2Scl),
      },
      customV1[1],
    ];
    const customManifest = computeMerkleSyncManifest('ST99', customV2, customPrev);
    expect(customManifest.dirtyCount).toBe(2);
    expect(customManifest.entries.find((e) => e.blockName === 'IDB_Custom')?.status).toBe('DIRTY');
    expect(customManifest.entries.find((e) => e.blockName === 'IDB_Custom')?.reason).toContain(
      '接口时间戳刷新：需连带重建背景 DB'
    );
  });

  it('handles OK/NG branches, homingOverride, and Tarjan cycle deadlock safety fault block', () => {
    const st20 = getSt20();

    // Add an NG branch step from VisionCam
    st20.temporalSteps.push({
      id: 'T_S35_NG',
      stepNo: 35,
      title: '视觉NG移至抛料位',
      fromNode: 'INST_ST20_CAM',
      fromPort: 'OUT_NG',
      branchPredicate: 'NG',
      invocations: [
        {
          targetNodeId: 'INST_ST20_X',
          targetPortId: 'IN_EXEC',
          methodId: 'MoveReject',
          actionLabel: '移至NG抛料位 (410mm)',
          targetDiscreteState: 'Pos_Reject_410',
          sclStatement: '#DB_ST20_AxisX.MoveAbs(410.0);',
          waitPredicateScl: '"DB_ST20_AxisX".o_bInPos',
        },
      ],
    });

    const branched = compileStationHyperGraph(st20);
    const autoSeq = branched.find((b) => b.blockName === 'FB_ST20_AutoSeq')!;
    expect(autoSeq.sclCode).toContain('"DB_ST20_VisionCam".o_bPassOk');
    expect(autoSeq.sclCode).toContain('#statStep := 30;');
    expect(autoSeq.sclCode).toContain('"DB_ST20_VisionCam".o_bFailNg');
    expect(autoSeq.sclCode).toContain('#statStep := 35;');

    // Consuming homingOverride directly when no deadlock
    const customOverride: HomingSynthesisResult = {
      hasCycleDeadlock: false,
      cycleNodeIds: [],
      cycleEdgeIds: [],
      concurrentLayers: [],
      layerActions: [],
      generatedHomeScl:
        'FUNCTION_BLOCK "FB_ST20_HomeSeq"\nVAR_INPUT\n   i_bHomeReq : Bool;\nEND_VAR\nBEGIN\n   ; // Custom Override\nEND_FUNCTION_BLOCK',
    };
    const withOverride = compileStationHyperGraph(st20, customOverride);
    expect(withOverride[2].sclCode).toContain('// Custom Override');

    // Consuming homingOverride with cycle deadlock emits safe fault-stop block
    const deadlockOverride: HomingSynthesisResult = {
      hasCycleDeadlock: true,
      cycleNodeIds: ['INST_ST20_Z', 'INST_ST20_X'],
      cycleEdgeIds: ['G_ST20_Z_TO_X', 'G_ST20_X_TO_Z'],
      concurrentLayers: [],
      layerActions: [],
      generatedHomeScl: '',
    };
    const withDeadlockOverride = compileStationHyperGraph(st20, deadlockOverride);
    expect(withDeadlockOverride[2].sclCode).toContain('#q_bHomeFault := TRUE;');
    expect(withDeadlockOverride[2].sclCode).toContain('16#DEAD');
    expect(withDeadlockOverride[2].sclCode).toContain('G_ST20_X_TO_Z');

    // Internal Tarjan cycle deadlock detection without homingOverride
    st20.guardEdges.push({
      id: 'G_CYCLE_X_TO_Z',
      fromNode: 'INST_ST20_X',
      fromPort: 'OUT_DONE',
      toNode: 'INST_ST20_Z',
      toPort: 'IN_GUARD',
      requiredSourceState: 'Pos_Home_0',
      diagCodeHex: '16#0299',
      humanDescription: '人为构造死锁环 X -> Z',
    });
    const cyclicArtifacts = compileStationHyperGraph(st20);
    expect(cyclicArtifacts[2].sclCode).toContain('#q_bHomeFault := TRUE;');
    expect(cyclicArtifacts[2].sclCode).toContain('G_CYCLE_X_TO_Z');
  });

  it('compiles ST10 and ST30 cleanly without boundary DB errors', () => {
    const ws = createDefaultAfStudioWorkspace();
    const st10Artifacts = compileStationHyperGraph(ws.stationGraphs.ST10);
    const st30Artifacts = compileStationHyperGraph(ws.stationGraphs.ST30);

    expect(st10Artifacts).toHaveLength(4);
    expect(st10Artifacts[3].sclCode).toContain('#q_bInterlock_BOUND_OUT_ST10 := FALSE;');
    expect(st10Artifacts[3].sclCode).not.toContain('"输出至下游 ST20"');

    expect(st30Artifacts).toHaveLength(4);
    expect(st30Artifacts[2].sclCode).toContain('FUNCTION_BLOCK "FB_ST30_HomeSeq"');
    expect(st30Artifacts[3].sclCode).toContain('当前工站无额外空间安全护栏边');
  });
});
