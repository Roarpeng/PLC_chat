import React, { useEffect, useState, useCallback } from 'react';
import type {
  CameraFlyToStage,
  CutSetTraceResult,
  GhostGraphTransaction,
  HomingSynthesisResult,
  ProjectCompoundEdge,
  ProjectCompoundStation,
  ProjectHyperGraph,
  RadialMethodOption,
  SafetyGuardEdge,
  SelectedHyperEntity,
  SpatialInstanceNode,
  StationHyperGraph,
  TemporalStepHyperEdge,
  VerificationReport,
  VerifierViolation,
} from '../../core/ir/afHyperGraph.types';
import { useHyperGraphStore } from '../../state/hyperGraphStore';
import { exportTiaV19 } from '../../lib/afStudioV5Api';
import { stationHasUnboundSignals } from '../../core/ir/stationWorkspace';
import { cmBindingStatus, cmPresetWait, defaultCmControl } from '../../core/ir/fieldIo';
import { advanceOrchestration, initialOrchestrationRun, orchestrationPhaseLabels, type OrchestrationRun } from '../../core/ir/stationOrchestration';
import { synthesizeGhostFromPrompt } from '../../core/copilot/nlGhostSynthesizer';
import {
  parseColdStartTables,
  createDemoExcelColdStartPayload,
} from '../../core/copilot/excelColdStartParser';

import { MotherClassPalette, type MotherClassCategory } from './MotherClassPalette';
import { NodeInspectorDrawer } from './NodeInspectorDrawer';
import { AutoHomingModal } from './AutoHomingModal';
import { VerificationReportModal } from './VerificationReportModal';
import { CutSetModal } from './CutSetModal';
import { MerkleSyncDrawer } from './MerkleSyncDrawer';
import { NewProjectModal } from './NewProjectModal';
import { StationOrchestrationEditor } from './StationOrchestrationEditor';
import { FieldIoTable } from './FieldIoEditor';
import { GhostDiffBanner } from '../copilot/GhostDiffBanner';
import { ExcelColdStartDrop } from '../copilot/ExcelColdStartDrop';
import { SemanticZoomStage, type RadialApplyPayload } from '../viewport/SemanticZoomStage';
import { TimeRibbonScrubber } from '../timeline/TimeRibbonScrubber';

import '../../styles/afStudioV5.css';

export interface AfStudioV5ShellProps {
  onSwitch?: (target: 'legacy' | 'classic') => void;
}

export const AfStudioV5Shell: React.FC<AfStudioV5ShellProps> = ({ onSwitch: _onSwitch }) => {
  const store = useHyperGraphStore();

  const {
    workspace,
    currentLayer,
    currentStationId,
    zoomScale,
    focusedStepNo,
    selectedEntity,
    activeGhost,
    verifierReport,
    cutSetTrace,
    faultFlyActive,
    flyToStage,
    activeModal,
    isMerkleDrawerOpen,
    isInspectorOpen,
    paletteCollapsed,
    st10SensorHealthy,
    setLayer,
    setStation,
    setZoomScale,
    setFocusedStepNo,
    setSelectedEntity,
    setActiveGhost,
    commitGhost,
    discardGhost,
    runVerification,
    applyAutoFix,
    runCutSetTrace,
    stepFaultCruise,
    stopFaultCruise,
    openModal,
    closeModal,
    toggleMerkleDrawer,
    toggleInspector,
    togglePaletteCollapse,
    setSt10SensorHealthy,
    addNode,
    updateNode,
    deleteNode,
    addGuardEdge,
    updateGuardEdge,
    deleteGuardEdge,
    addTemporalStep,
    updateTemporalStep,
    deleteTemporalStep,
    updateProjectStation,
    arrangeProjectStations,
    deleteProjectStation,
    addProjectEdge,
    updateProjectEdge,
    deleteProjectEdge,
    createNewProject,
    addStationToProject,
    updateOrchestration,
    saveFieldPoint,
    deleteFieldPoint,
    bindFieldPoint,
    applyHomingResult,
  } = store;

  const [newProjectModalMode, setNewProjectModalMode] = useState<'project' | 'station'>('project');
  const [copySource, setCopySource] = useState<ProjectCompoundStation>();
  const [runs, setRuns] = useState<Record<string, OrchestrationRun>>({});
  const [tiaExporting, setTiaExporting] = useState(false);
  const [tiaExportStatus, setTiaExportStatus] = useState<{ message: string; error?: boolean }>();

  const downloadTiaArchive = async () => {
    setTiaExporting(true);
    setTiaExportStatus({ message: '正在生成 V19 离线归档，博途将编译并校验还原，请保持页面打开。' });
    try {
      const archive = await exportTiaV19(workspace);
      const url = URL.createObjectURL(archive);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'KUKA_V5_Offline.zap19';
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setTiaExportStatus({ message: 'V19 归档已生成并开始下载。' });
    } catch (error) {
      setTiaExportStatus({ message: error instanceof Error ? error.message : 'V19 导出失败。', error: true });
    } finally {
      setTiaExporting(false);
    }
  };
  const [jobMessages, setJobMessages] = useState<Record<string, { sourceId: string; durationSeconds: number }>>({});
  const [showStationWireLabels, setShowStationWireLabels] = useState(false);
  const currentStation = workspace.stationGraphs[currentStationId] ?? null;
  const orchestration = currentLayer === 'STATION' ? currentStation?.orchestration : undefined;
  const pendingSignals = Boolean(currentStation && stationHasUnboundSignals(currentStation));
  const physicalStatus = currentStation ? cmBindingStatus(currentStation) : undefined;
  const projectPreview: ProjectHyperGraph = {
    edges: [
      ...workspace.projectGraph.edges,
      ...workspace.projectGraph.stations.flatMap((source) => {
        const plan = workspace.stationGraphs[source.stationId]?.orchestration;
        if (!plan) return [];
        const stationIds = new Set(plan.operations.map(({ stationId }) => stationId));
        if (plan.interrupt) stationIds.add(plan.interrupt.stationId);
        return workspace.projectGraph.stations.filter(({ stationId, kind }) => kind !== 'LOGIC' && stationIds.has(stationId))
          .map((target): ProjectCompoundEdge => ({
            id: `ORCH_${source.id}_${target.id}`,
            fromNode: source.id,
            fromPort: 'P_HANDOVER',
            toNode: target.id,
            toPort: 'P_UP',
            kind: 'SEQ',
            label: target.stationId === plan.interrupt?.stationId ? '附件更换请求' : '工位调用',
            managedByOrchestration: true,
          }));
      }),
    ],
    stations: workspace.projectGraph.stations.map((station) => {
      const graph = workspace.stationGraphs[station.stationId];
      if (!graph) return station;
      const run = runs[station.stationId];
      const count = graph.spatialNodes.filter((node) => node.role === 'ACTUATOR').length;
      return {
        ...station,
        instanceSummaries: graph.orchestration
          ? [run ? `${orchestrationPhaseLabels[run.phase]} · 工具 ${run.tool || '无'}` : '编排与离线握手模拟']
          : [`${count} 个设备实例 · ${graph.temporalSteps.length} 个站内工步`],
      };
    }),
  };

  useEffect(() => {
    if (typeof document !== 'undefined') {
      document.title = 'AF-Studio v5 · 工业自动化时空超图工作台';
    }
  }, []);

  // 全局键盘快捷键响应
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // 忽略输入框焦点
      const target = e.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.tagName === 'SELECT' ||
          target.isContentEditable)
      ) {
        return;
      }

      // Ctrl + 1: 切换整线 (L1)
      if (e.ctrlKey && e.key === '1') {
        e.preventDefault();
        setLayer('PROJECT');
        return;
      }

      // Ctrl + 2: 切换当前工站 (L2)
      if (e.ctrlKey && e.key === '2') {
        e.preventDefault();
        setLayer('STATION', currentStationId);
        return;
      }

      // Ctrl + V: 触发符号学验证
      if (e.ctrlKey && (e.key === 'v' || e.key === 'V')) {
        e.preventDefault();
        runVerification();
        openModal('verifier');
        return;
      }

      // Ctrl + B: 打开 Merkle 编译抽屉
      if (e.ctrlKey && (e.key === 'b' || e.key === 'B')) {
        e.preventDefault();
        toggleMerkleDrawer();
        return;
      }

      // Ctrl + H: 打开自动归航合成
      if (e.ctrlKey && (e.key === 'h' || e.key === 'H')) {
        e.preventDefault();
        openModal('homing');
        return;
      }

      // Ctrl + I: 切换属性检查器
      if (e.ctrlKey && (e.key === 'i' || e.key === 'I')) {
        e.preventDefault();
        toggleInspector();
        return;
      }

      // Escape: 关闭当前弹窗/抽屉或放弃 Ghost
      if (e.key === 'Escape') {
        if (activeModal) {
          e.preventDefault();
          closeModal();
          return;
        }
        if (isMerkleDrawerOpen) {
          e.preventDefault();
          toggleMerkleDrawer(false);
          return;
        }
        if (activeGhost) {
          e.preventDefault();
          discardGhost();
          return;
        }
      }

      // Delete / Backspace: 删除当前选中的节点或逻辑连线
      if (
        (e.key === 'Delete' || e.key === 'Backspace') &&
        !activeModal &&
        selectedEntity
      ) {
        e.preventDefault();
        if (selectedEntity.kind === 'NODE') {
          deleteNode(currentStationId, selectedEntity.id);
        } else if (selectedEntity.kind === 'STEP') {
          deleteTemporalStep(currentStationId, selectedEntity.id);
        } else if (selectedEntity.kind === 'GUARD') {
          deleteGuardEdge(currentStationId, selectedEntity.id);
        } else if (selectedEntity.kind === 'L1_EDGE') {
          deleteProjectEdge(selectedEntity.id);
        } else if (selectedEntity.kind === 'STATION') {
          deleteProjectStation(selectedEntity.id);
        }
        return;
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [
    currentStationId,
    activeModal,
    isMerkleDrawerOpen,
    activeGhost,
    selectedEntity,
    setLayer,
    runVerification,
    openModal,
    closeModal,
    toggleMerkleDrawer,
    toggleInspector,
    discardGhost,
    deleteNode,
    deleteTemporalStep,
    deleteGuardEdge,
    deleteProjectEdge,
    deleteProjectStation,
  ]);

  // 从调色板添加实例
  const handleAddNodeFromPalette = useCallback(
    (category: MotherClassCategory) => {
      if (currentLayer !== 'STATION' || !currentStation || currentStation.orchestration) return;
      const uid = crypto.randomUUID().slice(0, 8).toUpperCase();
      const nodeId = `INST_${currentStationId}_${category.defaultDbPrefix}_${uid}`;
      const { cmProfile } = category;
      let index = 0;
      const positionAt = (i: number) => ({ x: 40 + (i % 3) * 270, y: 342 + Math.floor(i / 3) * 250 });
      while (currentStation.spatialNodes.some(({ position }) =>
        Math.abs(position.x - positionAt(index).x) < 250 && Math.abs(position.y - positionAt(index).y) < 235)) index += 1;
      const newNode: SpatialInstanceNode = {
        id: nodeId,
        role: 'ACTUATOR',
        title: `${category.nameZh}_${uid}`,
        driverClass: category.driverClass,
        cmProfile,
        instanceDb: `DB_${currentStationId}_${category.defaultDbPrefix}_${uid}`,
        position: positionAt(index),
        isPinned: false,
        ...defaultCmControl(cmProfile),
        cohesiveIoMap: {},
        theme: category.theme,
      };
      addNode(currentStationId, newNode);
      toggleInspector(true);
    },
    [currentLayer, currentStation, currentStationId, addNode, toggleInspector]
  );

  // 画布节点位置移动与钉选 (同时支持 L1 全局总图工站与 L2 工站内部执行器)
  const handleMoveAndPinNode = useCallback(
    (layer: 'PROJECT' | 'STATION', nodeId: string, position: { x: number; y: number }) => {
      if (layer === 'PROJECT') {
        updateProjectStation(nodeId, { position, isPinned: true });
      } else {
        updateNode(currentStationId, nodeId, { position, isPinned: true });
      }
    },
    [currentStationId, updateNode, updateProjectStation]
  );

  // 径向菜单应用动作或护栏 (支持创建永久安全护栏边 + 创建时序步连线并进入检查器编辑)
  const handleApplyRadialOption = useCallback(
    (payload: RadialApplyPayload) => {
      if (!currentStation) return;
      const uid = Date.now().toString(36).slice(-4).toUpperCase();
      if (payload.option.isGuard) {
        const targetGuardPort =
          payload.targetNode.inPorts.find((p) => p.type === 'GUARD')?.id ?? 'IN_GUARD';
        const guardEdge: SafetyGuardEdge = {
          id: `G_${payload.targetNode.id}_${uid}`,
          fromNode: payload.fromNodeId,
          fromPort: payload.fromPortId,
          toNode: payload.targetNode.id,
          toPort: targetGuardPort,
          requiredSourceState: payload.option.targetDiscreteState,
          diagCodeHex: '16#0299',
          humanDescription: `${payload.targetNode.title} 须处于 ${payload.option.targetDiscreteState} 状态`,
          isHealthy: true,
        };
        addGuardEdge(currentStationId, guardEdge);
        setSelectedEntity({ kind: 'GUARD', id: guardEdge.id });
        toggleInspector(true);
      } else {
        const maxStepNo = currentStation.temporalSteps.reduce(
          (max, step) => Math.max(max, step.stepNo),
          0
        );
        const nextStepNo = maxStepNo + 10;
        const targetExecPort =
          payload.option.targetPortId ?? payload.targetNode.inPorts.find((p) => p.type === 'SEQ')?.id ?? 'IN_EXEC';
        const newStep: TemporalStepHyperEdge = {
          id: `T_RADIAL_S${nextStepNo}_${uid}`,
          stepNo: nextStepNo,
          title: `${payload.targetNode.title} · ${payload.option.label}`,
          fromNode: payload.fromNodeId,
          fromPort: payload.fromPortId,
          branchPredicate: 'ALWAYS',
          invocations: [
            {
              targetNodeId: payload.targetNode.id,
              targetPortId: targetExecPort,
              methodId: payload.option.methodId,
              actionLabel: payload.option.label,
              targetDiscreteState: payload.option.targetDiscreteState,
              sclStatement: payload.option.sclCommand,
              waitPredicateScl: cmPresetWait(payload.targetNode, payload.option),
              waitDescription: payload.option.waitDescription,
            },
          ],
        };
        addTemporalStep(currentStationId, newStep);
        setSelectedEntity({ kind: 'STEP', id: newStep.id });
        setFocusedStepNo(nextStepNo);
        toggleInspector(true);
      }
    },
    [
      currentStation,
      currentStationId,
      addGuardEdge,
      addTemporalStep,
      setSelectedEntity,
      setFocusedStepNo,
      toggleInspector,
    ]
  );

  // 时序底栏提交自然语言 Copilot 提示词合成 Ghost 补丁
  const handleSubmitPrompt = useCallback(
    (text: string) => {
      if (!currentStation) return;
      try {
        const ghost = synthesizeGhostFromPrompt(text, currentStation);
        setActiveGhost(ghost);
      } catch (err) {
        console.error('Copilot prompt synthesis failed:', err);
      }
    },
    [currentStation, currentStationId, setActiveGhost]
  );

  // 表格冷启动导入处理
  const handleImportColdStartTables = useCallback(
    (timingTableText: string, ioTableText?: string) => {
      if (!currentStation) return;
      try {
        const ghost = parseColdStartTables(timingTableText, ioTableText ?? '', {
          stationId: currentStationId,
          existingNodes: currentStation.spatialNodes,
          startStepNo: 25,
        });
        setActiveGhost(ghost);
        closeModal();
      } catch (err) {
        console.error('Cold start import failed:', err);
      }
    },
    [currentStation, currentStationId, setActiveGhost, closeModal]
  );

  // 演示冷启动导入
  const handleRunDemoColdStart = useCallback(() => {
    try {
      const demoPayload = createDemoExcelColdStartPayload(currentStationId);
      setActiveGhost(demoPayload.transaction);
      closeModal();
    } catch (err) {
      console.error('Run demo cold start failed:', err);
    }
  }, [currentStationId, setActiveGhost, closeModal]);

  // 验证状态灯色彩计算
  const violationCount = verifierReport?.violations?.length ?? 0;
  const warningCount = verifierReport?.warnings?.length ?? 0;
  const healthColor =
    violationCount > 0
      ? 'var(--af5-vermilion, #DC2626)'
      : warningCount > 0
        ? 'var(--af5-amber, #D97706)'
        : 'var(--af5-emerald, #059669)';

  const healthText =
    orchestration ? '离线逻辑模拟' : currentLayer === 'PROJECT'
      ? (store.workspaceSaved ? '本机草稿已保存' : '全局预览')
      : violationCount > 0
      ? `${violationCount} 项安全违例`
      : warningCount > 0
        ? `${warningCount} 项工程警告`
        : physicalStatus ?? (pendingSignals ? '待绑定现场 I/O' : '形式化验证通过');

  return (
    <div className="af5-shell" data-testid="af-studio-v5-shell">
      {/* 顶部导航条 */}
      <header className="af5-topbar" data-testid="af5-topbar">
        {/* 左区：工坊品牌与工站切换下拉 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 18 }}>⚙️</span>
            <div>
              <div
                style={{
                  fontSize: 14,
                  fontWeight: 800,
                  letterSpacing: '0.04em',
                  color: 'var(--ink-primary, #161514)',
                }}
                data-testid="studio-brand-title"
              >
                AF-Studio v5
              </div>
              <div style={{ fontSize: 9, color: 'var(--ink-tertiary, #8C887B)', letterSpacing: '0.06em' }}>
                INDUSTRIAL HYPERGRAPH
              </div>
            </div>
          </div>

          <div
            style={{
              height: 20,
              width: 1,
              background: 'var(--border-line, #D0C9BC)',
            }}
          />

          {/* 工站选择下拉 (动态绑定当前工程与工站列表) */}
          <select
            value={currentLayer === 'PROJECT' ? 'PROJECT' : currentStationId}
            onChange={(e) => {
              const val = e.target.value;
              if (val === 'PROJECT') {
                setLayer('PROJECT');
              } else {
                setStation(val);
                setLayer('STATION', val);
              }
            }}
            style={{
              padding: '4px 8px',
              fontSize: 12,
              fontWeight: 600,
              borderRadius: 6,
              border: '1px solid var(--border-line, #D0C9BC)',
              background: 'var(--bg-card, #F7F4EE)',
              color: 'var(--ink-primary, #161514)',
              cursor: 'pointer',
              outline: 'none',
              maxWidth: 230,
            }}
            data-testid="station-select-dropdown"
          >
            <option value="PROJECT">{workspace.projectName} (产线全局总图)</option>
            {workspace.projectGraph.stations.map((st) => (
              <option key={st.stationId} value={st.stationId}>
                {st.title}
              </option>
            ))}
          </select>

          {/* 新建项目 / 新建工站入口 */}
          <button
            type="button"
            className="af5-btn af5-btn--primary"
            style={{ fontSize: 11, padding: '3px 8px', whiteSpace: 'nowrap' }}
            onClick={() => {
              setCopySource(undefined);
              setNewProjectModalMode('project');
              openModal('newProject');
            }}
            title="新建空工程、单工站或三工站示范项目"
            data-testid="nav-new-project-btn"
          >
            ➕ 新建项目
          </button>

          <button
            type="button"
            className="af5-btn"
            style={{ fontSize: 11, padding: '3px 8px', whiteSpace: 'nowrap' }}
            onClick={() => {
              setCopySource(undefined);
              setNewProjectModalMode('station');
              openModal('newProject');
            }}
            title="在当前项目中添加新的工艺工站"
            data-testid="nav-new-station-btn"
          >
            ➕ 加工站
          </button>

          {/* L1/L2 语义缩放指示器 */}
          <button
            type="button"
            className="af5-btn"
            style={{
              padding: '2px 8px',
              fontSize: 11,
              fontWeight: 700,
              background:
                currentLayer === 'PROJECT'
                  ? 'var(--af5-klein-soft, rgba(37, 99, 235, 0.10))'
                  : 'var(--af5-emerald-soft, rgba(5, 150, 105, 0.11))',
              color:
                currentLayer === 'PROJECT'
                  ? 'var(--af5-klein, #2563EB)'
                  : 'var(--af5-emerald, #059669)',
              border: '1px solid var(--border-line, #D0C9BC)',
            }}
            onClick={() => {
              if (currentLayer === 'PROJECT') {
                setLayer('STATION', currentStationId);
              } else {
                setLayer('PROJECT');
              }
            }}
            title="点击在 L1 产线图与 L2 空间玻璃盒间切换 (快捷键: Ctrl+1 / Ctrl+2)"
            data-testid="layer-mode-indicator"
          >
            {currentLayer === 'PROJECT' ? 'L1 · 产线总图' : `L2 · 空间玻璃盒 (${currentStationId})`}
          </button>
        </div>

        {/* 右区：验证指示灯与操作工具栏 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {/* 验证健康度指示灯 */}
          <button
            type="button"
            className="af5-btn"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '4px 10px',
              fontSize: 11,
              fontWeight: 600,
            }}
            onClick={() => {
              runVerification();
              openModal('verifier');
            }}
            disabled={Boolean(orchestration) || currentLayer === 'PROJECT'}
            title="点击查看形式化验证报告 (快捷键: Ctrl+V)"
            data-testid="health-indicator-btn"
          >
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: healthColor,
                boxShadow: `0 0 6px ${healthColor}`,
              }}
              data-testid="health-light-dot"
            />
            <span data-testid="health-light-text">{healthText}</span>
          </button>

          <button type="button" className="af5-btn" onClick={() => openModal('fieldIo')}>I/O 点表</button>

          {/* 归航偏序合成按钮 */}
          <button
            type="button"
            className="af5-btn"
            style={{ fontSize: 11, padding: '4px 8px' }}
            onClick={() => openModal('homing')}
            title="一键安全归航合成 (Ctrl+H)"
            data-testid="nav-homing-btn"
          >
            🏠 归航偏序
          </button>

          {/* 割集追溯按钮 */}
          <button
            type="button"
            className="af5-btn"
            style={{ fontSize: 11, padding: '4px 8px' }}
            onClick={() => {
              runCutSetTrace(currentStationId);
              openModal('cutset');
            }}
            title="跨站因果追溯与最小割集"
            data-testid="nav-cutset-btn"
          >
            ⚡ 割集追溯
          </button>

          {/* 冷启动导入按钮 */}
          <button
            type="button"
            className="af5-btn"
            style={{ fontSize: 11, padding: '4px 8px' }}
            onClick={() => openModal('coldstart')}
            title="Excel/IO 表格冷启动导入"
            data-testid="nav-coldstart-btn"
          >
            📥 表格冷启动
          </button>

          {currentLayer === 'PROJECT' && <button
            type="button"
            className="af5-btn"
            onClick={() => {
              const url = URL.createObjectURL(new Blob([JSON.stringify(workspace, null, 2)], { type: 'application/json' }));
              const link = document.createElement('a');
              link.href = url;
              link.download = 'AF-Studio-v5-workspace.json';
              link.click();
              window.setTimeout(() => URL.revokeObjectURL(url), 1000);
            }}
          >导出工程快照</button>}

          {currentLayer === 'PROJECT' && (
            <button className="af5-btn af5-btn--primary" type="button" onClick={downloadTiaArchive}
              title="下载 KUKA 离线验收的 TIA Portal V19 原生归档" disabled={tiaExporting}>
              {tiaExporting ? '正在导出 TIA V19…' : '导出 TIA V19'}
            </button>
          )}

          {/* Merkle 增量编译抽屉按钮 */}
          <button
            type="button"
            className="af5-btn"
            style={{ fontSize: 11, padding: '4px 8px' }}
            onClick={() => toggleMerkleDrawer()}
            title="Merkle 增量编译与博途同步 (Ctrl+B)"
            data-testid="nav-merkle-btn"
          >
            ⚡ Merkle 同步
          </button>

          {/* 属性检查器切换按钮 */}
          <button
            type="button"
            className={`af5-btn ${isInspectorOpen ? 'af5-btn--primary' : ''}`}
            style={{ fontSize: 11, padding: '4px 8px' }}
            onClick={() => toggleInspector()}
            title="切换右侧属性检查器 (Ctrl+I)"
            data-testid="nav-inspector-btn"
          >
            🔍 检查器
          </button>
        </div>
      </header>

      {tiaExportStatus && (
        <div className="af5-tia-export-status" role={tiaExportStatus.error ? 'alert' : 'status'}>
          {tiaExportStatus.message}
        </div>
      )}

      {/* 顶部协同横幅：GhostDiffBanner (绑定 activeGhost) */}
      {activeGhost && (
        <div data-testid="ghost-banner-container">
          <GhostDiffBanner
            transaction={activeGhost}
            verifierReport={verifierReport}
            onCommit={commitGhost}
            onDiscard={discardGhost}
            onAutoFixGuard={() => {
              if (verifierReport?.violations[0]) {
                applyAutoFix(verifierReport.violations[0]);
              }
            }}
          />
        </div>
      )}

      {/* 主视口区域：三栏布局 */}
      <main className="af5-workspace" data-testid="af5-workspace">
        {/* 左侧：驱动母版调色板 */}
        {currentLayer === 'STATION' && !orchestration && <MotherClassPalette
          isCollapsed={paletteCollapsed}
          onToggleCollapse={togglePaletteCollapse}
          onAddNode={handleAddNodeFromPalette}
          currentStationId={currentStationId}
        />}

        {/* 中央视口容器 */}
        <div
          style={{
            flex: 1,
            minWidth: 0,
            display: 'flex',
            flexDirection: 'column',
            position: 'relative',
            overflow: 'hidden',
          }}
          data-testid="center-viewport-container"
        >
          {orchestration ? <StationOrchestrationEditor
            title={currentStation!.stationName}
            stationId={currentStationId}
            plan={orchestration}
            receivedDurationSeconds={jobMessages[currentStationId]?.durationSeconds}
            sentDurationSeconds={orchestration.jobDispatch &&
              jobMessages[orchestration.jobDispatch.stationId]?.sourceId === currentStationId
                ? jobMessages[orchestration.jobDispatch.stationId]?.durationSeconds : undefined}
            onSendJob={(targetId, durationSeconds) => setJobMessages((previous) => ({
              ...previous,
              [targetId]: { sourceId: currentStationId, durationSeconds },
            }))}
            stations={workspace.projectGraph.stations}
            run={runs[currentStationId]}
            onChange={(plan) => {
              updateOrchestration(currentStationId, plan);
              setRuns((previous) => ({ ...previous, [currentStationId]: initialOrchestrationRun(plan) }));
            }}
            onEvent={(event) => setRuns((previous) => ({
              ...previous,
              [currentStationId]: advanceOrchestration(orchestration, previous[currentStationId] ?? initialOrchestrationRun(orchestration), event),
            }))}
          /> : <>
          {/* 画布视口核心 (包裹 HyperEdgeSvgLayer, SpatialNodeCard, RadialCraftMenu) */}
          <div
            style={{
              flex: 1,
              minHeight: 0,
              width: '100%',
              height: '100%',
              display: 'flex',
              flexDirection: 'column',
              position: 'relative',
              overflow: 'hidden',
            }}
          >
            <SemanticZoomStage
              layer={currentLayer}
              zoomScale={zoomScale}
              projectGraph={projectPreview}
              projectName={workspace.projectName}
              station={currentStation}
              focusedStepNo={focusedStepNo}
              showStationWireLabels={showStationWireLabels}
              selectedEntity={selectedEntity}
              ghostTransaction={activeGhost}
              verifierReport={verifierReport}
              cutSetTrace={cutSetTrace}
              faultFlyActive={faultFlyActive}
              flyToStage={flyToStage}
              st10SensorHealthy={st10SensorHealthy}
              onZoomScaleChange={setZoomScale}
              onSwitchLayer={(layer, stId) => setLayer(layer, stId)}
              onSelectEntity={(entity) => {
                setSelectedEntity(entity);
                if (entity && entity.kind !== 'NODE' && entity.kind !== 'STATION') toggleInspector(true);
              }}
              onOpenNode={(nodeId) => {
                setSelectedEntity({ kind: 'NODE', id: nodeId });
                toggleInspector(true);
              }}
              onMoveAndPinNode={handleMoveAndPinNode}
              onApplyRadialOption={handleApplyRadialOption}
              onCreateProjectEdge={(payload) => {
                const newEdge: ProjectCompoundEdge = {
                  id: `E_L1_${Date.now().toString(36).slice(-5)}`,
                  fromNode: payload.fromNode,
                  fromPort: payload.fromPort,
                  toNode: payload.toNode,
                  toPort: payload.toPort,
                  kind: payload.kind,
                  label: payload.label,
                  diagCodeHex: payload.kind === 'GUARD' ? '16#0299' : undefined,
                };
                addProjectEdge(newEdge);
                toggleInspector(true);
              }}
              onSelectStepNo={(stepNo) => setFocusedStepNo(stepNo)}
              onDeleteNode={(nodeId) => deleteNode(currentStationId, nodeId)}
              onDeleteGuard={(edgeId) => deleteGuardEdge(currentStationId, edgeId)}
              onDeleteStep={(stepId) => deleteTemporalStep(currentStationId, stepId)}
              onDeleteProjectEdge={deleteProjectEdge}
              onDeleteProjectStation={deleteProjectStation}
              onArrangeProjectStations={arrangeProjectStations}
              onCopyProjectStation={(station) => {
                setCopySource(station);
                setNewProjectModalMode('station');
                openModal('newProject');
              }}
              onRepairRootCause={() => setSt10SensorHealthy(true)}
              onStopFaultFly={stopFaultCruise}
            />
          </div>

          {/* 底部时序透镜 (TimeRibbonScrubber) */}
          {currentLayer === 'STATION' && <TimeRibbonScrubber
            layer={currentLayer}
            station={currentStation}
            focusedStepNo={focusedStepNo}
            onFocusStep={(stepNo) => {
              setFocusedStepNo(stepNo);
              const step = currentStation?.temporalSteps.find(({ stepNo: candidate }) => candidate === stepNo);
              setSelectedEntity(step ? { kind: 'STEP', id: step.id } : null);
            }}
            showWireLabels={showStationWireLabels}
            onToggleWireLabels={() => setShowStationWireLabels((visible) => !visible)}
            onEditStep={(id) => {
              setSelectedEntity({ kind: 'STEP', id });
              toggleInspector(true);
            }}
            onSubmitPrompt={handleSubmitPrompt}
          />}
          </>}
        </div>

        {/* 右侧：属性与连线逻辑检查抽屉 */}
        <NodeInspectorDrawer
          isOpen={isInspectorOpen && !orchestration}
          onClose={() => toggleInspector(false)}
          selectedNodeId={selectedEntity?.kind === 'NODE' ? selectedEntity.id : null}
          selectedEntity={selectedEntity}
          layer={currentLayer}
          projectGraph={workspace.projectGraph}
          station={currentStation}
          fieldIoWorkspace={workspace}
          onBindFieldPoint={(nodeId, portId, pointId) => bindFieldPoint(currentStationId, nodeId, portId, pointId)}
          onOpenPointTable={() => openModal('fieldIo')}
          onUpdateNode={(nodeId, patch) => updateNode(currentStationId, nodeId, patch)}
          onDeleteNode={(nodeId) => deleteNode(currentStationId, nodeId)}
          onCenterFocus={(nodeId) => setSelectedEntity({ kind: 'NODE', id: nodeId })}
          onSelectStep={(stepNo) => setFocusedStepNo(stepNo)}
          onSelectEntity={(entity) => setSelectedEntity(entity)}
          onAddGuardEdge={(edge) => addGuardEdge(currentStationId, edge)}
          onUpdateGuardEdge={(edgeId, patch) => updateGuardEdge(currentStationId, edgeId, patch)}
          onDeleteGuardEdge={(edgeId) => deleteGuardEdge(currentStationId, edgeId)}
          onAddTemporalStep={(step) => addTemporalStep(currentStationId, step)}
          onUpdateTemporalStep={(stepId, patch) => updateTemporalStep(currentStationId, stepId, patch)}
          onDeleteTemporalStep={(stepId) => deleteTemporalStep(currentStationId, stepId)}
          onUpdateProjectStation={updateProjectStation}
          onDeleteProjectStation={deleteProjectStation}
          onAddProjectEdge={addProjectEdge}
          onUpdateProjectEdge={updateProjectEdge}
          onDeleteProjectEdge={deleteProjectEdge}
          onEnterStation={(stId) => {
            setStation(stId);
            setLayer('STATION', stId);
          }}
        />
      </main>

      {/* 模态弹窗插槽 */}
      <NewProjectModal
        isOpen={activeModal === 'newProject'}
        initialMode={newProjectModalMode}
        currentProjectName={workspace.projectName}
        existingStationIds={Object.keys(workspace.stationGraphs)}
        copySource={copySource}
        onClose={closeModal}
        onCreateProject={(payload) => {
          setRuns({});
          setJobMessages({});
          createNewProject(payload);
        }}
        onAddStation={addStationToProject}
      />

      <AutoHomingModal
        isOpen={activeModal === 'homing'}
        onClose={closeModal}
        station={currentStation}
        onApplyHoming={(result) => applyHomingResult(currentStationId, result)}
      />

      <VerificationReportModal
        isOpen={activeModal === 'verifier'}
        onClose={closeModal}
        report={verifierReport}
        stationName={currentStation?.stationName || currentStationId}
        onApplyAutoFix={applyAutoFix}
        onReverify={runVerification}
      />

      <CutSetModal
        isOpen={activeModal === 'cutset'}
        onClose={closeModal}
        cutSetTrace={cutSetTrace}
        onStepFaultCruise={stepFaultCruise}
        onStopFaultCruise={stopFaultCruise}
        currentActiveStage={flyToStage}
      />

      <MerkleSyncDrawer
        isOpen={isMerkleDrawerOpen}
        onClose={() => toggleMerkleDrawer(false)}
        station={currentStation?.orchestration ? null : currentStation}
        pendingSignals={pendingSignals}
        physicalStatus={physicalStatus}
      />

      {activeModal === 'fieldIo' && <FieldIoTable workspace={workspace}
        onSave={saveFieldPoint} onDelete={deleteFieldPoint} onClose={closeModal} />}

      {/* Excel 表格冷启动导入弹窗 */}
      {activeModal === 'coldstart' && (
        <div
          className="af5-modal-backdrop"
          onClick={(e) => {
            if (e.target === e.currentTarget) closeModal();
          }}
          data-testid="coldstart-modal"
        >
          <div
            className="af5-modal"
            style={{
              width: '100%',
              maxWidth: 680,
              maxHeight: '85vh',
              display: 'flex',
              flexDirection: 'column',
              background: 'var(--bg-card, #F7F4EE)',
            }}
          >
            <div className="af5-modal-header">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 16 }}>📥</span>
                <div>
                  <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--ink-primary, #161514)' }}>
                    Excel / EPLAN 时序表与点表冷启动导入
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--ink-secondary, #5C5A55)' }}>
                    工站: {currentStationId} · 快速注入物理执行器与时序超边
                  </div>
                </div>
              </div>

              <button
                type="button"
                className="af5-btn"
                style={{ padding: '2px 8px', fontSize: 12 }}
                onClick={closeModal}
                aria-label="关闭弹窗"
                data-testid="close-coldstart-modal-btn"
              >
                ✕
              </button>
            </div>

            <div className="af5-modal-body" style={{ flex: 1, overflowY: 'auto' }}>
              <ExcelColdStartDrop
                stationId={currentStationId}
                onImportTables={handleImportColdStartTables}
                onRunDemoColdStart={handleRunDemoColdStart}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
