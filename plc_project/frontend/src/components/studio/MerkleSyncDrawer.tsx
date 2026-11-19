import React, { useEffect, useState } from 'react';
import type {
  CompiledBlockArtifact,
  MerkleSyncManifest,
  StationHyperGraph,
} from '../../core/ir/afHyperGraph.types';
import { compileStationHyperGraph } from '../../core/compiler/multiTargetSclGen';
import { computeMerkleSyncManifest } from '../../core/compiler/merkleAstHasher';
import '../../styles/afStudioV5.css';

export interface MerkleSyncDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  station: StationHyperGraph | null;
  pendingSignals?: boolean;
  physicalStatus?: string;
  onSyncTia?: (manifest: MerkleSyncManifest) => Promise<void> | void;
  onDownloadScl?: (artifacts: CompiledBlockArtifact[]) => void;
}

function initCompileArtifacts(station: StationHyperGraph | null, isOpen: boolean): CompiledBlockArtifact[] {
  if (!isOpen || !station) return [];
  try {
    return compileStationHyperGraph(station);
  } catch {
    return [];
  }
}

function initMerkleManifest(
  station: StationHyperGraph | null,
  isOpen: boolean,
  compiled: CompiledBlockArtifact[]
): MerkleSyncManifest | null {
  if (!isOpen || !station || compiled.length === 0) return null;
  try {
    return computeMerkleSyncManifest(station.stationId, compiled, {});
  } catch {
    return null;
  }
}

export const MerkleSyncDrawer: React.FC<MerkleSyncDrawerProps> = ({
  isOpen,
  onClose,
  station,
  pendingSignals,
  physicalStatus,
  onSyncTia,
  onDownloadScl,
}) => {
  const blocked = Boolean(pendingSignals || physicalStatus);
  const initialArtifacts = React.useMemo(
    () => blocked ? [] : initCompileArtifacts(station, isOpen),
    [station, isOpen, blocked]
  );
  const initialManifest = React.useMemo(
    () => initMerkleManifest(station, isOpen, initialArtifacts),
    [station?.stationId, isOpen, initialArtifacts]
  );

  const [artifacts, setArtifacts] = useState<CompiledBlockArtifact[]>(initialArtifacts);
  const [manifest, setManifest] = useState<MerkleSyncManifest | null>(initialManifest);
  const [activeTabIdx, setActiveTabIdx] = useState<number>(0);
  const [compileElapsedMs, setCompileElapsedMs] = useState<number>(0);
  const [isSyncing, setIsSyncing] = useState<boolean>(false);
  const [syncDone, setSyncDone] = useState<boolean>(false);
  const [syncLogs, setSyncLogs] = useState<string[]>([]);
  const [updatedIdbList, setUpdatedIdbList] = useState<string[]>([]);

  useEffect(() => {
    if (!isOpen) return;
    if (!station || blocked) {
      setArtifacts([]);
      setManifest(null);
      setSyncDone(false);
      setSyncLogs([]);
      return;
    }
    const start = Date.now();
    try {
      const compiled = compileStationHyperGraph(station);
      const elapsed = Date.now() - start;
      setCompileElapsedMs(elapsed);
      setArtifacts(compiled);

      const computedManifest = computeMerkleSyncManifest(station.stationId, compiled, {});
      setManifest(computedManifest);
      setSyncDone(false);
      setSyncLogs([]);
    } catch (e) {
      setArtifacts([]);
      setManifest(null);
      console.error('Failed to compile station hypergraph:', e);
    }
  }, [isOpen, station, blocked]);

  if (!isOpen) return null;

  const currentArtifact = artifacts[activeTabIdx] ?? null;

  const handleSyncTia = async () => {
    if (!manifest) return;
    setIsSyncing(true);
    setSyncLogs((prev) => [
      ...prev,
      `[${new Date().toLocaleTimeString()}] 连接博途 TIA Openness STA V19 网关...`,
      `[${new Date().toLocaleTimeString()}] 比较 AST Merkle SHA-256 树指纹...`,
    ]);

    try {
      if (onSyncTia) {
        await onSyncTia(manifest);
      }
      const dirtyBlocks = manifest.entries.filter((e) => e.status === 'DIRTY').map((e) => e.blockName);
      const idbs = dirtyBlocks.filter((b) => b.startsWith('DB_'));
      setUpdatedIdbList(idbs.length > 0 ? idbs : [`DB_${station?.stationId}_Instances`]);

      setSyncLogs((prev) => [
        ...prev,
        `[${new Date().toLocaleTimeString()}] 增量同步完成：热替换 ${manifest.dirtyCount} 块，复用 ${manifest.unchangedCount} 块。`,
        `[${new Date().toLocaleTimeString()}] STA 写入完成，PLC 处于 RUN 模式无需停机。`,
      ]);
      setSyncDone(true);
    } catch (err) {
      setSyncLogs((prev) => [
        ...prev,
        `[${new Date().toLocaleTimeString()}] 同步失败: ${String(err)}`,
      ]);
    } finally {
      setIsSyncing(false);
    }
  };

  const handleDownload = () => {
    if (onDownloadScl) {
      onDownloadScl(artifacts);
      return;
    }
    if (artifacts.length === 0) return;
    const fullCode = artifacts.map((a) => `// ================= ${a.blockName} =================\n${a.sclCode}`).join('\n\n');
    const blob = new Blob([fullCode], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${station?.stationId || 'Station'}_V19_EXPORT.scl`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <>
      {/* 遮罩背景 */}
      <div
        className="af5-drawer-backdrop"
        onClick={onClose}
        style={{
          position: 'fixed',
          inset: 0,
          background: 'rgba(22, 21, 20, 0.36)',
          backdropFilter: 'blur(2px)',
          zIndex: 49,
        }}
        data-testid="merkle-drawer-backdrop"
      />

      <aside
        className="af5-drawer is-open"
        style={{
          width: 580,
          maxWidth: '90vw',
          zIndex: 50,
          display: 'flex',
          flexDirection: 'column',
          boxShadow: 'var(--elev-leaf, -16px 8px 24px -10px rgba(22, 21, 20, 0.25))',
        }}
        data-testid="merkle-sync-drawer"
      >
        {/* 抽屉头部 */}
        <div className="af5-drawer-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 16 }}>⚡</span>
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--ink-primary, #161514)' }}>
                AST Merkle 增量编译与博途 TIA Openness STA 同步
              </div>
              <div style={{ fontSize: 11, color: 'var(--ink-secondary, #5C5A55)' }}>
                工站: {station?.stationName || station?.stationId} · 4 大 SCL 块 AST 增量热同步
              </div>
            </div>
          </div>

          <button
            type="button"
            className="af5-btn"
            style={{ padding: '2px 8px', fontSize: 11 }}
            onClick={onClose}
            aria-label="关闭抽屉"
            data-testid="close-merkle-drawer-btn"
          >
            ✕
          </button>
        </div>

        {/* 编译耗时与 Merkle 概览条 */}
        <div
          style={{
            padding: '10px 16px',
            background: 'var(--bg-subtle, #E5E0D5)',
            borderBottom: '1px solid var(--border-line, #D0C9BC)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            fontSize: 11,
          }}
          data-testid="merkle-stats-bar"
        >
          <div style={{ display: 'flex', gap: 12 }}>
            <span>
              编译耗时: <strong style={{ fontFamily: 'var(--font-mono, monospace)' }}>{compileElapsedMs}ms</strong>
            </span>
            <span>
              变更块: <strong style={{ color: 'var(--af5-amber, #D97706)' }}>{manifest?.dirtyCount ?? 0} DIRTY</strong>
            </span>
            <span>
              复用块: <strong style={{ color: 'var(--af5-emerald, #059669)' }}>{manifest?.unchangedCount ?? 0} UNCHANGED</strong>
            </span>
          </div>

          <div style={{ fontSize: 10, color: 'var(--ink-secondary, #5C5A55)' }}>
            目标: {manifest?.tiaTarget ?? 'TIA_V19_STA'}
          </div>
        </div>

        {/* 4 大 SCL 块列表 */}
        <div
          style={{
            padding: '10px 16px',
            background: 'var(--bg-card, #F7F4EE)',
            borderBottom: '1px solid var(--border-line, #D0C9BC)',
            display: 'flex',
            flexDirection: 'column',
            gap: 6,
          }}
          data-testid="merkle-blocks-list"
        >
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--ink-secondary, #5C5A55)' }}>
            工站 4 大 SCL 块哈希指纹:
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {artifacts.map((art, idx) => {
              const diffEntry = manifest?.entries.find((e) => e.blockName === art.blockName);
              const isDirty = diffEntry?.status === 'DIRTY';
              const isSelected = activeTabIdx === idx;

              return (
                <div
                  key={art.blockName}
                  onClick={() => setActiveTabIdx(idx)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '5px 10px',
                    borderRadius: 6,
                    background: isSelected ? 'var(--bg-paper, #EFECE6)' : 'transparent',
                    border: isSelected ? '1px solid var(--af5-klein, #2563EB)' : '1px solid transparent',
                    cursor: 'pointer',
                    fontSize: 11,
                  }}
                  data-testid={`block-item-${art.blockName}`}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span
                      style={{
                        padding: '1px 4px',
                        borderRadius: 3,
                        fontSize: 9,
                        fontWeight: 700,
                        background: 'var(--bg-subtle, #E5E0D5)',
                        fontFamily: 'var(--font-mono, monospace)',
                      }}
                    >
                      {art.blockType}
                    </span>
                    <span style={{ fontWeight: 600 }}>{art.blockName}</span>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span
                      style={{
                        fontFamily: 'var(--font-mono, monospace)',
                        fontSize: 10,
                        color: 'var(--ink-secondary, #5C5A55)',
                      }}
                    >
                      SHA: {art.merkleHash.slice(0, 10)}…
                    </span>

                    <span
                      style={{
                        fontSize: 9,
                        padding: '1px 5px',
                        borderRadius: 4,
                        fontWeight: 700,
                        background: isDirty ? 'var(--af5-amber-soft, rgba(217, 119, 6, 0.12))' : 'var(--af5-emerald-soft, rgba(5, 150, 105, 0.11))',
                        color: isDirty ? 'var(--af5-amber, #D97706)' : 'var(--af5-emerald, #059669)',
                      }}
                      data-testid={`dirty-badge-${art.blockName}`}
                    >
                      {isDirty ? 'DIRTY' : 'UNCHANGED'}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* 块切换 Tabs */}
        <div className="af5-drawer-tabs">
          {artifacts.map((art, idx) => (
            <button
              key={art.blockName}
              type="button"
              className={`af5-drawer-tab ${activeTabIdx === idx ? 'is-active' : ''}`}
              onClick={() => setActiveTabIdx(idx)}
            >
              {art.blockName}
            </button>
          ))}
        </div>

        {/* SCL 代码预览区 */}
        <div className="af5-drawer-code" style={{ flex: 1, minHeight: 180 }} data-testid="scl-code-preview">
          <pre style={{ margin: 0 }}>
            {currentArtifact ? currentArtifact.sclCode : '// 暂无代码产物'}
          </pre>
        </div>

        {/* 同步结果展示区域 */}
        {(syncDone || syncLogs.length > 0) && (
          <div
            style={{
              padding: '10px 16px',
              background: 'var(--bg-paper, #EFECE6)',
              borderTop: '1px solid var(--border-line, #D0C9BC)',
              maxHeight: 140,
              overflowY: 'auto',
              display: 'flex',
              flexDirection: 'column',
              gap: 4,
              fontSize: 10,
              fontFamily: 'var(--font-mono, monospace)',
            }}
            data-testid="sync-result-panel"
          >
            <div style={{ fontWeight: 700, color: 'var(--ink-primary, #161514)' }}>
              同步状态与更新的 IDB 列表:
            </div>
            {updatedIdbList.length > 0 && (
              <div style={{ color: 'var(--af5-emerald, #059669)' }} data-testid="updated-idbs">
                更新的 IDB 数据块: {updatedIdbList.join(', ')}
              </div>
            )}
            {syncLogs.map((log, lIdx) => (
              <div key={lIdx} style={{ color: 'var(--ink-secondary, #5C5A55)' }}>
                {log}
              </div>
            ))}
          </div>
        )}

        {/* 抽屉底部操作栏 */}
        {blocked && <p role="alert">{physicalStatus ?? '绑定现场 I/O 和工步引用后，才能生成 SCL。'}</p>}
        <div className="af5-drawer-footer">
          <button
            type="button"
            className="af5-btn"
            onClick={handleDownload}
            disabled={!artifacts.length || blocked}
            data-testid="download-scl-btn"
          >
            📥 生成并下载 SCL (V19_EXPORT)
          </button>

          <button
            type="button"
            className="af5-btn af5-btn--primary"
            onClick={handleSyncTia}
            disabled={isSyncing || !manifest || blocked}
            data-testid="sync-tia-btn"
          >
            {isSyncing ? '⏳ 同步中...' : '⚡ 增量同步至博途 (TIA_V19_STA)'}
          </button>
        </div>
      </aside>
    </>
  );
};
