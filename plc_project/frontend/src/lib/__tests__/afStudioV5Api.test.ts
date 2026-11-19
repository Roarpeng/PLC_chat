import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  compileStationScl,
  fetchMerkleManifest,
  syncMerkleBlocks,
  synthesizeCopilotIntent,
  synthesizeStationHoming,
  traceStationCutSet,
  verifyStationSymbolic,
} from '../afStudioV5Api';
import { createDefaultAfStudioWorkspace } from '../../core/ir/seedHyperGraphs';
import type { SafetyGuardEdge, StationHyperGraph } from '../../core/ir/afHyperGraph.types';

describe('afStudioV5Api - 7 Endpoints & Offline Fallback', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    // 默认模拟网络断开，强制触发离线降级分支
    globalThis.fetch = vi.fn().mockRejectedValue(new Error('Network connection refused (offline test)'));
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  const getSt20 = (): StationHyperGraph => {
    const ws = createDefaultAfStudioWorkspace();
    return JSON.parse(JSON.stringify(ws.stationGraphs['ST20']));
  };

  it('1. fetchMerkleManifest: falls back to local AST hasher when offline', async () => {
    const st20 = getSt20();
    const res = await fetchMerkleManifest({ station: st20 });

    expect(res.ok).toBe(true);
    expect(res.code).toBe(0);
    expect(res.evidence_level).toBe('offline');
    expect(res.evidenceLevel).toBe('offline');
    expect(res.data.stationId).toBe('ST20');
    expect(res.data.dirtyCount).toBe(4);
    expect(res.data.unchangedCount).toBe(0);
    expect(res.data.entries).toHaveLength(4);

    const blockNames = res.data.entries.map((e) => e.blockName);
    expect(blockNames).toContain('FB_ST20_AutoSeq');
    expect(blockNames).toContain('FB_ST20_HomeSeq');
    expect(blockNames).toContain('FC_ST20_GuardDiag');
    expect(blockNames).toContain('DB_ST20_Instances');
  });

  it('2. syncMerkleBlocks: computes block-level diffs and aligns with backend fields', async () => {
    const st20 = getSt20();
    const res = await syncMerkleBlocks({
      station: st20,
      projectId: 'AssyLine_01',
    });

    expect(res.ok).toBe(true);
    expect(res.evidence_level).toBe('offline');
    expect(res.data.projectId).toBe('AssyLine_01');
    expect(res.data.stationId).toBe('ST20');
    expect(res.data.totalBlocks).toBe(4);
    expect(res.data.dirtyCount).toBe(4);
    expect(res.data.unchangedCount).toBe(0);
    expect(res.data.tiaSynced).toBe(false);
    expect(res.data.compileOk).toBe(true);
    expect(res.data.dirtyBlocks).toHaveLength(4);

    // 第二次同步（传入之前的哈希）：dirtyCount 降为 0
    const prevHashes = res.data.blockHashes;
    const res2 = await syncMerkleBlocks({
      station: st20,
      projectId: 'AssyLine_01',
      previousHashes: prevHashes,
    });
    expect(res2.data.dirtyCount).toBe(0);
    expect(res2.data.unchangedCount).toBe(4);
    expect(res2.data.dirtyBlocks).toEqual([]);
  });

  it('3. compileStationScl: deterministically generates 4 SCL blocks and hashes', async () => {
    const st20 = getSt20();
    const res = await compileStationScl({ station: st20 });

    expect(res.ok).toBe(true);
    expect(res.evidence_level).toBe('offline');
    expect(res.data.stationId).toBe('ST20');
    expect(res.data.blocks).toHaveLength(4);

    const blockMap = Object.fromEntries(res.data.blocks.map((b) => [b.name, b]));
    expect(blockMap['FB_ST20_AutoSeq']).toBeDefined();
    expect(blockMap['FB_ST20_HomeSeq']).toBeDefined();
    expect(blockMap['FC_ST20_GuardDiag']).toBeDefined();
    expect(blockMap['DB_ST20_Instances']).toBeDefined();

    for (const blk of res.data.blocks) {
      expect(blk.merkleHash).toHaveLength(8);
      expect(blk.sclCode.trim().length).toBeGreaterThan(0);
    }
  });

  it('4. verifyStationSymbolic: passes valid ST20 and intercepts missing guardrails', async () => {
    const st20 = getSt20();
    // 正常 ST20 校验通过
    const resPass = await verifyStationSymbolic({ station: st20 });
    expect(resPass.ok).toBe(true);
    expect(resPass.data.passed).toBe(true);
    expect(resPass.data.violations).toEqual([]);
    expect(resPass.data.homingResult).toBeDefined();
    expect(resPass.data.homingResult?.hasCycleDeadlock).toBe(false);

    // 移除 Z 轴护栏 -> 触发违例并给出修复建议
    const st20Broken = JSON.parse(JSON.stringify(st20)) as StationHyperGraph;
    st20Broken.guardEdges = st20Broken.guardEdges.filter((g) => g.id !== 'G_ST20_Z_TO_X');

    const resFail = await verifyStationSymbolic({ station: st20Broken });
    expect(resFail.data.passed).toBe(false);
    expect(resFail.data.violations.length).toBeGreaterThan(0);
    expect(resFail.data.suggestedPatches?.length).toBeGreaterThan(0);

    const patch = resFail.data.suggestedPatches![0] as SafetyGuardEdge;
    expect(patch.fromNode).toBe('INST_ST20_Z');
    expect(patch.toNode).toBe('INST_ST20_X');

    // 补全护栏后再次验证 -> 通过
    st20Broken.guardEdges.push(patch);
    const resFixed = await verifyStationSymbolic({ station: st20Broken });
    expect(resFixed.data.passed).toBe(true);
  });

  it('5. synthesizeStationHoming: synthesizes 2-layer concurrent homing and detects deadlocks', async () => {
    const st20 = getSt20();
    const res = await synthesizeStationHoming({ station: st20 });

    expect(res.ok).toBe(true);
    expect(res.evidence_level).toBe('offline');
    expect(res.data.hasCycleDeadlock).toBe(false);
    expect(res.data.concurrentLayers).toHaveLength(2);

    const layer0NodeIds = res.data.concurrentLayers[0].map((n) => n.id);
    const layer1NodeIds = res.data.concurrentLayers[1].map((n) => n.id);
    expect(layer0NodeIds).toContain('INST_ST20_Z');
    expect(layer0NodeIds).toContain('INST_ST20_GRIP');
    expect(layer1NodeIds).toContain('INST_ST20_X');
    expect(res.data.generatedHomeScl).toContain('FB_ST20_HomeSeq');

    // 引入死锁环
    const st20Cycle = JSON.parse(JSON.stringify(st20)) as StationHyperGraph;
    st20Cycle.guardEdges.push({
      id: 'G_CYCLE_X_TO_Z',
      fromNode: 'INST_ST20_X',
      fromPort: 'OUT_DONE',
      toNode: 'INST_ST20_Z',
      toPort: 'IN_EXEC',
      requiredSourceState: 'Pos_Home_0',
      diagCodeHex: '16#0299',
      humanDescription: '测试死锁反向互锁',
    });

    const resDeadlock = await synthesizeStationHoming({ station: st20Cycle });
    expect(resDeadlock.data.hasCycleDeadlock).toBe(true);
    expect(resDeadlock.data.cycleNodeIds).toContain('INST_ST20_X');
    expect(resDeadlock.data.cycleNodeIds).toContain('INST_ST20_Z');
  });

  it('6. synthesizeCopilotIntent: synthesizes ghost diff transaction from NL intent', async () => {
    const st20 = getSt20();
    const res = await synthesizeCopilotIntent({
      station: st20,
      prompt: '增加视觉 NG 去抛料位虚影分支',
    });

    expect(res.ok).toBe(true);
    expect(res.evidence_level).toBe('offline');
    expect(res.data.stationId).toBe('ST20');
    expect(res.data.verificationPassed).toBe(true);
    expect(res.data.addedTemporalSteps.length).toBeGreaterThan(0);

    const step = res.data.addedTemporalSteps[0];
    expect(step.stepNo).toBe(35);
  });

  it('7. traceStationCutSet: prunes healthy guardrails and traces upstream root cause with 3-stage camera flight', async () => {
    const ws = createDefaultAfStudioWorkspace();
    const res = await traceStationCutSet({
      projectGraph: ws.projectGraph,
      stationGraphs: ws.stationGraphs,
      faultStationId: 'ST20',
      faultStepNo: 30,
    });

    expect(res.ok).toBe(true);
    expect(res.evidence_level).toBe('offline');
    expect(res.data.blockedStationId).toBe('ST20');
    expect(res.data.blockedStepNo).toBe(30);
    expect(res.data.prunedHealthyEdgeIds).toContain('G_ST20_Z_TO_X');
    expect(res.data.falsifiedEdgeIds).toContain('G_ST20_ST10_TO_X');
    expect(res.data.rootCauseStationId).toBe('ST10');
    expect(res.data.rootCauseNodeId).toBe('INST_ST10_TRANS');
    expect(res.data.rootPhysicalTerminal).toBe('%I0.4');
    expect(res.data.rootCabinetWireTag).toBe('X12:04');

    expect(res.data.flyToStages).toHaveLength(3);
    expect(res.data.flyToStages[0].layer).toBe('STATION');
    expect(res.data.flyToStages[0].stationId).toBe('ST20');
    expect(res.data.flyToStages[1].layer).toBe('PROJECT');
    expect(res.data.flyToStages[2].layer).toBe('STATION');
    expect(res.data.flyToStages[2].stationId).toBe('ST10');
  });

  it('handles remote server 200 response when gateway is available', async () => {
    const mockRemoteData = {
      stationId: 'ST20',
      blocks: [
        {
          name: 'FB_ST20_AutoSeq',
          type: 'FB',
          sclCode: 'REMOTE_SCL',
          merkleHash: 'A1B2C3D4',
          interfaceHash: 'E5F6G7H8',
        },
      ],
      blockHashes: { FB_ST20_AutoSeq: 'A1B2C3D4' },
      artifacts: [],
      totalLines: 10,
    };

    globalThis.fetch = vi.fn().mockResolvedValue({
      status: 200,
      json: async () => ({
        ok: true,
        code: 0,
        data: mockRemoteData,
        message: 'ok',
        evidence_level: 'V19_real',
        request_id: 'req_remote_123',
      }),
    });

    const st20 = getSt20();
    const res = await compileStationScl({ station: st20 });
    expect(res.ok).toBe(true);
    expect(res.evidence_level).toBe('V19_real');
    expect(res.evidenceLevel).toBe('V19_real');
    expect(res.data.blocks[0].sclCode).toBe('REMOTE_SCL');
  });
});
