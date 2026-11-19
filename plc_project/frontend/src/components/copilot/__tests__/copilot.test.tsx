import React, { type ReactElement, type ReactNode } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import type {
  GhostGraphTransaction,
  StationHyperGraph,
  VerificationReport,
} from '../../../core/ir/afHyperGraph.types';
import { createDefaultAfStudioWorkspace } from '../../../core/ir/seedHyperGraphs';
import {
  createDemoExcelColdStartPayload,
  parseColdStartTables,
} from '../../../core/copilot/excelColdStartParser';
import { synthesizeGhostFromPrompt } from '../../../core/copilot/nlGhostSynthesizer';
import {
  GhostDiffBanner,
  handleGhostBannerKeydown,
} from '../GhostDiffBanner';
import { ExcelColdStartDrop } from '../ExcelColdStartDrop';

type Element = ReactElement<Record<string, unknown>>;

function findElement(
  tree: ReactNode,
  predicate: (element: Element) => boolean
): Element | undefined {
  for (const child of React.Children.toArray(tree)) {
    if (!React.isValidElement<Record<string, unknown>>(child)) continue;
    if (predicate(child)) return child;
    const found = findElement(child.props.children as ReactNode, predicate);
    if (found) return found;
  }
  return undefined;
}

function textContent(node: ReactNode): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(textContent).join('');
  if (React.isValidElement<Record<string, unknown>>(node)) {
    return textContent(node.props.children as ReactNode);
  }
  return '';
}

function expand(element: ReactElement): ReactNode {
  let tree: ReactNode;
  function Render() {
    tree = (element.type as (props: Record<string, unknown>) => ReactNode)(
      element.props as Record<string, unknown>
    );
    return tree;
  }
  renderToStaticMarkup(<Render />);
  return tree;
}

function html(tree: ReactNode): string {
  return renderToStaticMarkup(<>{tree}</>);
}

describe('excelColdStartParser', () => {
  it('deduplicates repeated cylinder actions in TSV timing + IO tables into 1 SpatialInstanceNode and 3 TemporalStepHyperEdges', () => {
    const timingTsv = [
      '步号\t工步名称\t机构\t母版\t动作\t目标状态\t完成条件\t前序机构',
      '10\t定位气缸伸出\t定位气缸\t双位气缸\t伸出\tAtWork\t动位磁开 %I0.3 导通\t',
      '20\t定位气缸保压\t定位气缸\t双位气缸\t保压1.5s\tAtWork\t保压定时器完成\t定位气缸',
      '30\t定位气缸缩回\t定位气缸\t双位气缸\t缩回\tAtHome\t原位磁开 %I0.2 导通\t定位气缸',
    ].join('\n');

    const ioTsv = [
      '机构\t位号\t原位输入\t动位输入\t输出点\t电柜端子',
      '定位气缸\tDB_ST10_CylLoc\t%I0.2\t%I0.3\t%Q0.2\tX10:02',
    ].join('\n');

    const tx = parseColdStartTables(timingTsv, ioTsv, { stationId: 'ST10' });

    expect(tx.stationId).toBe('ST10');
    expect(tx.addedNodes).toHaveLength(1);
    const cylNode = tx.addedNodes[0];
    expect(cylNode.title).toBe('定位气缸');
    expect(cylNode.driverClass).toBe('FB_AF_Actuator2Pos');
    expect(cylNode.instanceDb).toBe('DB_ST10_CylLoc');
    expect(cylNode.isPinned).toBe(false);
    expect(cylNode.cohesiveIoMap).toEqual({
      diHome: '%I0.2',
      diWork: '%I0.3',
      doWork: '%Q0.2',
      cabinetTerminal: 'X10:02',
    });

    expect(tx.addedTemporalSteps).toHaveLength(3);
    expect(tx.addedTemporalSteps.map((s) => s.stepNo)).toEqual([10, 20, 30]);
    expect(
      tx.addedTemporalSteps.every(
        (s) => s.invocations[0]?.targetNodeId === cylNode.id
      )
    ).toBe(true);
    expect(tx.addedTemporalSteps.map((s) => s.invocations[0]?.methodId)).toEqual([
      'ExtendWork',
      'DwellHold',
      'RetractHome',
    ]);
    expect(
      tx.addedTemporalSteps.map((s) => s.invocations[0]?.targetDiscreteState)
    ).toEqual(['AtWork', 'AtWork', 'AtHome']);
    expect(tx.addedTemporalSteps[1].fromNode).toBe(cylNode.id);
    expect(tx.addedTemporalSteps[2].fromNode).toBe(cylNode.id);
  });

  it('parses quoted CSV, Markdown tables, and JSON row arrays with English headers', () => {
    const csvTiming = [
      'Step,Title,Actuator,Driver,Action,TargetState,WaitDesc',
      '10,"Clamp, Part",1号抓手,FB_AF_Gripper,GripClose,Closed,"Sensor %I3.2, %I3.4"',
      '20,Release Part,1号抓手,FB_AF_Gripper,GripOpen,Opened,Opened switch on',
    ].join('\n');
    const csvIo = [
      'Device,DB,DI_Home,DI_Work,DO_Work,DI_PartPresent,Terminal',
      '1号抓手,DB_ST15_Grip,%I3.0,%I3.1,%Q3.0,%I3.2,X15:01',
    ].join('\n');

    const csvTx = parseColdStartTables(csvTiming, csvIo, { stationId: 'ST15' });
    expect(csvTx.addedNodes).toHaveLength(1);
    expect(csvTx.addedNodes[0].driverClass).toBe('FB_AF_Gripper');
    expect(csvTx.addedNodes[0].hasPartPresentSensor).toBe(true);
    expect(csvTx.addedNodes[0].cohesiveIoMap.diPartPresent).toBe('%I3.2');
    expect(csvTx.addedNodes[0].isPinned).toBe(false);
    expect(csvTx.addedTemporalSteps).toHaveLength(2);
    expect(csvTx.addedTemporalSteps[0].invocations[0].waitDescription).toBe(
      'Sensor %I3.2, %I3.4'
    );

    const mdTiming = [
      '| 步号 | 工步名称 | 机构 | 动作 | 完成条件 |',
      '| --- | --- | --- | --- | --- |',
      '| 10 | 压装伸出 | 辅助压缸 | 伸出 | 到位信号 |',
      '| 20 | 压装退回 | 辅助压缸 | 缩回 | 原位信号 |',
    ].join('\n');
    const mdTx = parseColdStartTables(mdTiming, undefined, { stationId: 'ST16' });
    expect(mdTx.addedNodes).toHaveLength(1);
    expect(mdTx.addedTemporalSteps).toHaveLength(2);

    const jsonTiming = JSON.stringify([
      {
        stepNo: 10,
        title: '视觉检测',
        actuator: '视觉复检相机',
        driverClass: 'FB_AF_VisionSensor',
        action: 'TrigInspect',
        targetState: 'Pass_OK',
        waitDesc: '判定完成',
      },
    ]);
    const jsonTx = parseColdStartTables(jsonTiming, undefined, { stationId: 'ST17' });
    expect(jsonTx.addedNodes).toHaveLength(1);
    expect(jsonTx.addedNodes[0].driverClass).toBe('FB_AF_VisionSensor');
    expect(jsonTx.addedTemporalSteps).toHaveLength(1);
  });

  it('reuses existingNodes by name or instanceDb without creating duplicate nodes', () => {
    const ws = createDefaultAfStudioWorkspace();
    const st20 = ws.stationGraphs.ST20;

    const timingTsv = [
      '步号\t工步名称\t机构\t动作\t完成条件\t前序机构',
      '60\tZ轴二次下压\tZ轴主压装气缸\t伸出\t下压动位导通\tINST_ST20_X',
      '70\tZ轴二次退回\tDB_ST20_CylZ\t缩回\t回原位 %I10.0\tZ轴主压装气缸',
    ].join('\n');

    const tx = parseColdStartTables(timingTsv, undefined, {
      stationId: 'ST20',
      existingNodes: st20.spatialNodes,
    });

    expect(tx.addedNodes).toHaveLength(0);
    expect(tx.addedTemporalSteps).toHaveLength(2);
    expect(tx.addedTemporalSteps[0].invocations[0].targetNodeId).toBe('INST_ST20_Z');
    expect(tx.addedTemporalSteps[1].invocations[0].targetNodeId).toBe('INST_ST20_Z');
  });

  it('createDemoExcelColdStartPayload("ST30") produces DB_ST30_CylReject and S25 ghost wire', () => {
    const payload = createDemoExcelColdStartPayload('ST30');
    expect(payload.timingTableText).toContain('NG剔除吹气气缸');
    expect(payload.ioTableText).toContain('DB_ST30_CylReject');

    const { transaction } = payload;
    expect(transaction.stationId).toBe('ST30');
    expect(transaction.addedNodes).toHaveLength(1);
    const rejectNode = transaction.addedNodes[0];
    expect(rejectNode.title).toBe('NG剔除吹气气缸');
    expect(rejectNode.instanceDb).toBe('DB_ST30_CylReject');
    expect(rejectNode.isPinned).toBe(false);
    expect(rejectNode.cohesiveIoMap.diHome).toBe('%I20.2');
    expect(rejectNode.cohesiveIoMap.doWork).toBe('%Q20.1');

    expect(transaction.addedTemporalSteps).toHaveLength(1);
    const s25 = transaction.addedTemporalSteps[0];
    expect(s25.stepNo).toBe(25);
    expect(s25.fromNode).toBe('INST_ST30_LASER');
    expect(s25.fromPort).toBe('OUT_OK');
    expect(s25.invocations[0].targetNodeId).toBe(rejectNode.id);
    expect(s25.branchPredicate).toBe('NG');
  });
});

describe('nlGhostSynthesizer', () => {
  it('synthesizes S35 (OUT_NG -> INST_ST20_X) and S36 (INST_ST20_X -> INST_ST20_GRIP) on ST20 for NG reject prompt', () => {
    const ws = createDefaultAfStudioWorkspace();
    const st20 = ws.stationGraphs.ST20;

    const tx = synthesizeGhostFromPrompt('增加视觉 NG 去抛料位分支', st20);

    expect(tx.stationId).toBe('ST20');
    expect(tx.addedNodes).toHaveLength(0);
    expect(tx.addedTemporalSteps).toHaveLength(2);
    expect(tx.verificationPassed).toBe(true);

    const [s35, s36] = tx.addedTemporalSteps;
    expect(s35.stepNo).toBe(35);
    expect(s35.title).toContain('410mm');
    expect(s35.fromNode).toBe('INST_ST20_CAM');
    expect(s35.fromPort).toBe('OUT_NG');
    expect(s35.branchPredicate).toBe('NG');
    expect(s35.invocations[0].targetNodeId).toBe('INST_ST20_X');
    expect(s35.invocations[0].targetDiscreteState).toBe('Pos_Reject_410');

    expect(s36.stepNo).toBe(36);
    expect(s36.fromNode).toBe('INST_ST20_X');
    expect(s36.branchPredicate).toBe('NG');
    expect(s36.invocations[0].targetNodeId).toBe('INST_ST20_GRIP');
    expect(s36.invocations[0].methodId).toBe('GripOpen');
  });

  it('attaches an unpinned NG reject cylinder node when station lacks one (ST30)', () => {
    const ws = createDefaultAfStudioWorkspace();
    const st30 = ws.stationGraphs.ST30;

    const tx = synthesizeGhostFromPrompt('增加 NG 剔除分支', st30);

    expect(tx.addedNodes).toHaveLength(1);
    expect(tx.addedNodes[0].instanceDb).toBe('DB_ST30_CylReject');
    expect(tx.addedNodes[0].isPinned).toBe(false);
    expect(tx.addedTemporalSteps).toHaveLength(1);
    expect(tx.addedTemporalSteps[0].stepNo).toBe(25);
    expect(tx.addedTemporalSteps[0].invocations[0].targetNodeId).toBe(tx.addedNodes[0].id);
  });

  it('synthesizes safety guardrail edges for防撞/护栏 prompts without cycles', () => {
    const ws = createDefaultAfStudioWorkspace();
    const st20MissingGuard: StationHyperGraph = {
      ...ws.stationGraphs.ST20,
      guardEdges: ws.stationGraphs.ST20.guardEdges.filter(
        (g) => g.id !== 'G_ST20_Z_TO_X'
      ),
    };

    const tx = synthesizeGhostFromPrompt('添加 Z轴与 X轴防撞互锁护栏', st20MissingGuard);
    expect(tx.addedGuardEdges).toHaveLength(1);
    expect(tx.addedGuardEdges[0].fromNode).toBe('INST_ST20_Z');
    expect(tx.addedGuardEdges[0].toNode).toBe('INST_ST20_X');
    expect(tx.addedGuardEdges[0].requiredSourceState).toBe('AtHome');
  });

  it('synthesizes new unpinned actuator node and next stepNo for 新增/复检 prompts', () => {
    const ws = createDefaultAfStudioWorkspace();
    const st20 = ws.stationGraphs.ST20;

    const tx = synthesizeGhostFromPrompt('新增复检气缸动作', st20);
    expect(tx.addedNodes).toHaveLength(1);
    expect(tx.addedNodes[0].isPinned).toBe(false);
    expect(tx.addedNodes[0].driverClass).toBe('FB_AF_Actuator2Pos');
    expect(tx.addedTemporalSteps).toHaveLength(1);
    expect(tx.addedTemporalSteps[0].stepNo).toBe(60);
    expect(tx.addedTemporalSteps[0].invocations[0].targetNodeId).toBe(tx.addedNodes[0].id);
  });
});

describe('GhostDiffBanner', () => {
  const sampleTx: GhostGraphTransaction = {
    txId: 'TX_TEST_1',
    stationId: 'ST20',
    summary: 'AI 已生成 2 条 NG 抛料虚影步序超边',
    addedNodes: [],
    addedGuardEdges: [],
    addedTemporalSteps: [
      {
        id: 'GW_1',
        stepNo: 35,
        title: 'NG移至抛料位',
        fromNode: 'INST_ST20_CAM',
        fromPort: 'OUT_NG',
        invocations: [
          {
            targetNodeId: 'INST_ST20_X',
            methodId: 'MoveReject',
            actionLabel: '移至NG抛料位 (410mm)',
            targetDiscreteState: 'Pos_Reject_410',
            sclStatement: '#DB_ST20_AxisX.MoveAbs(410.0);',
            waitPredicateScl: '"DB_ST20_AxisX".o_bInPos',
          },
        ],
        branchPredicate: 'NG',
      },
    ],
    verificationPassed: true,
    verifierWarnings: [],
  };

  it('returns null when transaction is null', () => {
    const tree = expand(
      <GhostDiffBanner
        transaction={null}
        onCommit={vi.fn()}
        onDiscard={vi.fn()}
      />
    );
    expect(tree).toBeNull();
  });

  it('renders .af5-ghost-banner with transaction counts, pin guarantee, and invokes onCommit/onDiscard', () => {
    const onCommit = vi.fn();
    const onDiscard = vi.fn();
    const tree = expand(
      <GhostDiffBanner
        transaction={sampleTx}
        onCommit={onCommit}
        onDiscard={onDiscard}
      />
    );

    const markup = html(tree);
    expect(markup).toContain('af5-ghost-banner');
    expect(markup).toContain(sampleTx.summary);
    expect(markup).toContain('新增 0 个实例 · 1 条虚影超边');
    expect(markup).toContain('既有锚定节点保持零位移');
    expect(markup).toContain('符号验证通过');

    const commitBtn = findElement(
      tree,
      (el) => el.type === 'button' && textContent(el).includes('实化采纳')
    )!;
    const discardBtn = findElement(
      tree,
      (el) => el.type === 'button' && textContent(el).includes('撤回')
    )!;

    (commitBtn.props.onClick as () => void)();
    expect(onCommit).toHaveBeenCalledOnce();

    (discardBtn.props.onClick as () => void)();
    expect(onDiscard).toHaveBeenCalledOnce();
  });

  it('surfaces collision violations and triggers onAutoFixGuard when verification fails', () => {
    const onAutoFixGuard = vi.fn();
    const report: VerificationReport = {
      passed: false,
      elapsedMs: 12,
      exploredStateCount: 18,
      violations: [
        {
          kind: 'COLLISION_REACHABLE',
          stepNo: 30,
          nodeId: 'INST_ST20_X',
          interferingNodeId: 'INST_ST20_Z',
          message: 'X轴移动时 Z轴气缸可能未在原位，存在机械碰撞风险',
        },
      ],
      warnings: ['缺少 Z轴 -> X轴 永久安全护栏'],
    };

    const tree = expand(
      <GhostDiffBanner
        transaction={sampleTx}
        verifierReport={report}
        onCommit={vi.fn()}
        onDiscard={vi.fn()}
        onAutoFixGuard={onAutoFixGuard}
      />
    );

    const markup = html(tree);
    expect(markup).toContain('COLLISION_REACHABLE');
    expect(markup).toContain('X轴移动时 Z轴气缸可能未在原位，存在机械碰撞风险');
    expect(markup).toContain('缺少 Z轴 -&gt; X轴 永久安全护栏');

    const fixBtn = findElement(
      tree,
      (el) => el.type === 'button' && textContent(el).includes('补齐防撞护栏')
    )!;
    (fixBtn.props.onClick as () => void)();
    expect(onAutoFixGuard).toHaveBeenCalledOnce();
  });

  it('uses Ctrl+Enter to apply a draft while leaving Tab and editable controls alone', () => {
    const onCommit = vi.fn();
    const onDiscard = vi.fn();

    const preventApply = vi.fn();
    const handledApply = handleGhostBannerKeydown(
      {
        key: 'Enter',
        target: null,
        preventDefault: preventApply,
        ctrlKey: true,
        metaKey: false,
        altKey: false,
      },
      { onCommit, onDiscard }
    );
    expect(handledApply).toBe(true);
    expect(preventApply).toHaveBeenCalledOnce();
    expect(onCommit).toHaveBeenCalledOnce();
    expect(handleGhostBannerKeydown({
      key: 'Tab', target: null, preventDefault: vi.fn(), ctrlKey: false, metaKey: false, altKey: false,
    }, { onCommit, onDiscard })).toBe(false);

    const preventEsc = vi.fn();
    const handledEsc = handleGhostBannerKeydown(
      {
        key: 'Escape',
        target: null,
        preventDefault: preventEsc,
        ctrlKey: false,
        metaKey: false,
        altKey: false,
      },
      { onCommit, onDiscard }
    );
    expect(handledEsc).toBe(true);
    expect(onDiscard).toHaveBeenCalledOnce();

    for (const tagName of ['INPUT', 'TEXTAREA', 'SELECT']) {
      const ignored = handleGhostBannerKeydown(
        {
          key: 'Enter',
          target: { tagName } as unknown as EventTarget,
          preventDefault: vi.fn(),
          ctrlKey: true,
          metaKey: false,
          altKey: false,
        },
        { onCommit, onDiscard }
      );
      expect(ignored).toBe(false);
    }
    expect(onCommit).toHaveBeenCalledTimes(1);
  });
});

describe('ExcelColdStartDrop', () => {
  it('renders .af5-coldstart-card and triggers onRunDemoColdStart when demo button is clicked', () => {
    const onImportTables = vi.fn();
    const onRunDemoColdStart = vi.fn();

    const tree = expand(
      <ExcelColdStartDrop
        stationId="ST30"
        onImportTables={onImportTables}
        onRunDemoColdStart={onRunDemoColdStart}
      />
    );

    const markup = html(tree);
    expect(markup).toContain('af5-coldstart-card');
    expect(markup).toContain('ST30');
    expect(markup).toContain('一键导入时序表生成蓝图');

    const demoBtn = findElement(
      tree,
      (el) => el.type === 'button' && textContent(el).includes('一键导入时序表生成蓝图')
    )!;
    (demoBtn.props.onClick as () => void)();
    expect(onRunDemoColdStart).toHaveBeenCalledOnce();
  });

  it('reads dropped .tsv / .csv files and invokes onImportTables', async () => {
    const onImportTables = vi.fn();
    const tree = expand(
      <ExcelColdStartDrop
        stationId="ST30"
        onImportTables={onImportTables}
        onRunDemoColdStart={vi.fn()}
      />
    );

    const dropzone = findElement(
      tree,
      (el) =>
        typeof el.props.className === 'string' &&
        el.props.className.includes('af5-coldstart-dropzone')
    )!;

    const timingContent = '步号\t工步名称\t机构\t动作\n10\t伸出\t吹气缸\t伸出';
    const ioContent = '机构\t位号\t输出点\n吹气缸\tDB_ST30_Cyl\t%Q20.1';
    const preventDefault = vi.fn();

    (dropzone.props.onDrop as (e: unknown) => void)({
      preventDefault,
      dataTransfer: {
        files: [
          {
            name: 'ST30_timing.tsv',
            type: 'text/tab-separated-values',
            text: async () => timingContent,
          },
          {
            name: 'EPLAN_IO.csv',
            type: 'text/csv',
            text: async () => ioContent,
          },
        ],
      },
    });

    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(preventDefault).toHaveBeenCalledOnce();
    expect(onImportTables).toHaveBeenCalledWith(timingContent, ioContent);
  });

  it('expands paste form and submits pasted timing & IO tables to onImportTables', () => {
    const states: unknown[] = [];
    let stateIdx = 0;

    const stateSpy = vi
      .spyOn(React, 'useState')
      .mockImplementation(((initial: unknown) => {
        const idx = stateIdx;
        stateIdx += 1;
        if (!(idx in states)) {
          states[idx] = initial;
        }
        const setter = (next: unknown) => {
          states[idx] =
            typeof next === 'function'
              ? (next as (prev: unknown) => unknown)(states[idx])
              : next;
        };
        return [states[idx], setter];
      }) as typeof React.useState);

    const refSpy = vi
      .spyOn(React, 'useRef')
      .mockImplementation(((initial: unknown) => ({ current: initial })) as typeof React.useRef);

    try {
      const onImportTables = vi.fn();
      const renderOnce = () => {
        stateIdx = 0;
        return ExcelColdStartDrop({
          stationId: 'ST20',
          onImportTables,
          onRunDemoColdStart: vi.fn(),
        });
      };

      let tree = renderOnce();
      expect(
        findElement(
          tree,
          (el) => el.type === 'form'
        )
      ).toBeUndefined();

      const toggleBtn = findElement(
        tree,
        (el) =>
          el.type === 'button' &&
          typeof el.props.className === 'string' &&
          el.props.className.includes('af5-coldstart-btn--toggle')
      )!;
      (toggleBtn.props.onClick as () => void)();

      tree = renderOnce();
      const form = findElement(tree, (el) => el.type === 'form')!;
      expect(form).toBeDefined();

      const timingArea = findElement(
        tree,
        (el) => el.type === 'textarea' && el.props['aria-label'] === '动作时序表文本'
      )!;
      const ioArea = findElement(
        tree,
        (el) => el.type === 'textarea' && el.props['aria-label'] === 'EPLAN IO表文本'
      )!;

      const pastedTiming = '步号\t工步名称\t机构\t动作\n10\t夹紧\t辅助夹爪\t闭合';
      const pastedIo = '机构\t位号\t输出点\n辅助夹爪\tDB_ST20_GripAux\t%Q12.0';

      (timingArea.props.onChange as (e: { target: { value: string } }) => void)({
        target: { value: pastedTiming },
      });
      (ioArea.props.onChange as (e: { target: { value: string } }) => void)({
        target: { value: pastedIo },
      });

      tree = renderOnce();
      const updatedForm = findElement(tree, (el) => el.type === 'form')!;
      const preventDefault = vi.fn();
      (updatedForm.props.onSubmit as (e: { preventDefault: () => void }) => void)({
        preventDefault,
      });

      expect(preventDefault).toHaveBeenCalledOnce();
      expect(onImportTables).toHaveBeenCalledWith(pastedTiming, pastedIo);
    } finally {
      stateSpy.mockRestore();
      refSpy.mockRestore();
    }
  });
});
