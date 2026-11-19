import React, { useEffect, useState } from 'react';
import type { AddStationPayload, NewProjectPayload } from '../../state/hyperGraphStore';
import type { ProjectCompoundStation, StationKind } from '../../core/ir/afHyperGraph.types';
import '../../styles/afStudioV5.css';

export interface NewProjectModalProps {
  isOpen: boolean;
  initialMode?: 'project' | 'station';
  currentProjectName: string;
  existingStationIds: string[];
  copySource?: ProjectCompoundStation;
  onClose: () => void;
  onCreateProject: (payload: NewProjectPayload) => void;
  onAddStation: (payload: AddStationPayload) => void;
}

export const NewProjectModal: React.FC<NewProjectModalProps> = ({
  isOpen,
  initialMode = 'project',
  currentProjectName,
  existingStationIds,
  copySource,
  onClose,
  onCreateProject,
  onAddStation,
}) => {
  const [mode, setMode] = useState<'project' | 'station'>(initialMode);
  const [projectName, setProjectName] = useState('NewAssemblyLine_01');
  const [template, setTemplate] = useState<'blank' | 'single_station' | 'three_station_line'>(
    'single_station'
  );
  const [firstStationId, setFirstStationId] = useState('ST10');
  const [firstStationTitle, setFirstStationTitle] = useState('ST10 · 主装配工站');

  let nextNumber = 10;
  while (existingStationIds.includes(`ST${nextNumber}`)) nextNumber += 10;
  const suggestedNextStation = `ST${nextNumber}`;
  const [newStationId, setNewStationId] = useState(suggestedNextStation);
  const [newStationTitle, setNewStationTitle] = useState(`${suggestedNextStation} · 新建工艺工站`);
  const [stationErr, setStationErr] = useState('');
  const [stationKind, setStationKind] = useState<StationKind>('PHYSICAL');

  useEffect(() => {
    if (isOpen) {
      setMode(initialMode);
      setNewStationId(suggestedNextStation);
      setNewStationTitle(copySource ? `${copySource.title}（副本）` : `${suggestedNextStation} · 新建工艺工站`);
      setStationKind(copySource?.kind ?? 'PHYSICAL');
      setStationErr('');
    }
  }, [isOpen, initialMode, suggestedNextStation, copySource]);

  if (!isOpen) return null;

  const handleCreateProjectSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onCreateProject({
      projectName: projectName.trim() || 'NewAssemblyLine_01',
      template,
      firstStationId: firstStationId.trim() || 'ST10',
      firstStationTitle: firstStationTitle.trim() || `${firstStationId || 'ST10'} · 主装配工站`,
    });
  };

  const handleAddStationSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const cleanId = newStationId.trim().toUpperCase().replace(/\s+/g, '_');
    if (!/^[A-Z][A-Z0-9_]*$/.test(cleanId)) {
      setStationErr('工站编号须以字母开头，可包含数字和下划线');
      return;
    }
    if (existingStationIds.includes(cleanId)) {
      setStationErr(`工站编号 ${cleanId} 已存在，请换一个编号`);
      return;
    }
    onAddStation({
      stationId: cleanId,
      title: newStationTitle.trim() || `${cleanId} · 新建工站`,
      kind: stationKind,
      copyFromId: copySource?.id,
    });
  };

  return (
    <div
      className="af5-modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      data-testid="new-project-modal"
    >
      <div
        className="af5-modal"
        style={{
          width: '100%',
          maxWidth: 540,
          display: 'flex',
          flexDirection: 'column',
          background: 'var(--bg-card, #F7F4EE)',
        }}
      >
        <div className="af5-modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 16 }}>📁</span>
            <div>
              <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--ink-primary, #161514)' }}>
                {copySource ? `复制工位 · ${copySource.title}` : '新建工程项目 / 新增产线工站'}
              </div>
              <div style={{ fontSize: 11, color: 'var(--ink-secondary, #5C5A55)' }}>
                当前工程：{currentProjectName}
              </div>
            </div>
          </div>

          <button
            type="button"
            className="af5-btn"
            style={{ padding: '2px 8px', fontSize: 12 }}
            onClick={onClose}
            aria-label="关闭弹窗"
            data-testid="close-new-project-modal-btn"
          >
            ✕
          </button>
        </div>

        <div className="af5-modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* 双模式切换栏 */}
          {!copySource && <div style={{ display: 'flex', gap: 8 }}>
            <button
              type="button"
              className={`af5-btn ${mode === 'project' ? 'af5-btn--primary' : ''}`}
              style={{ flex: 1, fontSize: 12, padding: '6px 10px' }}
              onClick={() => setMode('project')}
              data-testid="tab-new-project"
            >
              ➕ 新建整套超图项目
            </button>
            <button
              type="button"
              className={`af5-btn ${mode === 'station' ? 'af5-btn--primary' : ''}`}
              style={{ flex: 1, fontSize: 12, padding: '6px 10px' }}
              onClick={() => setMode('station')}
              data-testid="tab-add-station"
            >
              🏭 在当前项目添加新工站
            </button>
          </div>}

          {mode === 'project' ? (
            <form
              onSubmit={handleCreateProjectSubmit}
              style={{ display: 'flex', flexDirection: 'column', gap: 12 }}
              data-testid="new-project-form"
            >
              <div>
                <label style={{ display: 'block', fontSize: 11, fontWeight: 600, marginBottom: 4 }}>
                  新项目名称 (Project Name)
                </label>
                <input
                  type="text"
                  value={projectName}
                  onChange={(e) => setProjectName(e.target.value)}
                  placeholder="例如：PackLine_EV_02"
                  style={{
                    width: '100%',
                    boxSizing: 'border-box',
                    padding: '6px 10px',
                    fontSize: 12,
                    borderRadius: 6,
                    border: '1px solid var(--border-line, #D0C9BC)',
                    background: 'var(--bg-paper, #EFECE6)',
                  }}
                  data-testid="new-project-name-input"
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: 11, fontWeight: 600, marginBottom: 6 }}>
                  选择初始工程模板
                </label>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <label
                    style={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: 8,
                      padding: 8,
                      borderRadius: 8,
                      border:
                        template === 'single_station'
                          ? '1.5px solid var(--af5-klein, #2563EB)'
                          : '1px solid var(--border-line, #D0C9BC)',
                      background: 'var(--bg-paper, #EFECE6)',
                      cursor: 'pointer',
                    }}
                  >
                    <input
                      type="radio"
                      name="projectTemplate"
                      checked={template === 'single_station'}
                      onChange={() => setTemplate('single_station')}
                      data-testid="tpl-single-station"
                    />
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 700 }}>单工站快速起步模板</div>
                      <div style={{ fontSize: 11, color: 'var(--ink-secondary, #5C5A55)' }}>
                        含 1 个完整工站、气缸与伺服节点及标准互锁/步序连线，立即可调可编
                      </div>
                    </div>
                  </label>

                  <label
                    style={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: 8,
                      padding: 8,
                      borderRadius: 8,
                      border:
                        template === 'blank'
                          ? '1.5px solid var(--af5-klein, #2563EB)'
                          : '1px solid var(--border-line, #D0C9BC)',
                      background: 'var(--bg-paper, #EFECE6)',
                      cursor: 'pointer',
                    }}
                  >
                    <input
                      type="radio"
                      name="projectTemplate"
                      checked={template === 'blank'}
                      onChange={() => setTemplate('blank')}
                      data-testid="tpl-blank"
                    />
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 700 }}>空白工站工程（从零设计）</div>
                      <div style={{ fontSize: 11, color: 'var(--ink-secondary, #5C5A55)' }}>
                        仅含左输入与右输出边界端口，从左侧母版库自由拖放执行器并连线
                      </div>
                    </div>
                  </label>

                  <label
                    style={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: 8,
                      padding: 8,
                      borderRadius: 8,
                      border:
                        template === 'three_station_line'
                          ? '1.5px solid var(--af5-klein, #2563EB)'
                          : '1px solid var(--border-line, #D0C9BC)',
                      background: 'var(--bg-paper, #EFECE6)',
                      cursor: 'pointer',
                    }}
                  >
                    <input
                      type="radio"
                      name="projectTemplate"
                      checked={template === 'three_station_line'}
                      onChange={() => setTemplate('three_station_line')}
                      data-testid="tpl-three-station"
                    />
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 700 }}>三工站视觉压装产线模板</div>
                      <div style={{ fontSize: 11, color: 'var(--ink-secondary, #5C5A55)' }}>
                        重置为含 ST10/ST20/ST30 完整复合超图与跨站护栏联锁的示范产线
                      </div>
                    </div>
                  </label>
                </div>
              </div>

              {template !== 'three_station_line' && (
                <div style={{ display: 'flex', gap: 8 }}>
                  <div style={{ width: 110 }}>
                    <label style={{ display: 'block', fontSize: 10, fontWeight: 600, marginBottom: 3 }}>
                      首个工站编号
                    </label>
                    <input
                      type="text"
                      value={firstStationId}
                      onChange={(e) => setFirstStationId(e.target.value)}
                      style={{
                        width: '100%',
                        boxSizing: 'border-box',
                        padding: '5px 8px',
                        fontSize: 11,
                        fontFamily: 'var(--font-mono, monospace)',
                        borderRadius: 5,
                        border: '1px solid var(--border-line, #D0C9BC)',
                        background: 'var(--bg-paper, #EFECE6)',
                      }}
                    />
                  </div>
                  <div style={{ flex: 1 }}>
                    <label style={{ display: 'block', fontSize: 10, fontWeight: 600, marginBottom: 3 }}>
                      工站描述名称
                    </label>
                    <input
                      type="text"
                      value={firstStationTitle}
                      onChange={(e) => setFirstStationTitle(e.target.value)}
                      style={{
                        width: '100%',
                        boxSizing: 'border-box',
                        padding: '5px 8px',
                        fontSize: 11,
                        borderRadius: 5,
                        border: '1px solid var(--border-line, #D0C9BC)',
                        background: 'var(--bg-paper, #EFECE6)',
                      }}
                    />
                  </div>
                </div>
              )}

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 4 }}>
                <button type="button" className="af5-btn" onClick={onClose}>
                  取消
                </button>
                <button
                  type="submit"
                  className="af5-btn af5-btn--primary"
                  data-testid="confirm-create-project-btn"
                >
                  🚀 创建并打开项目
                </button>
              </div>
            </form>
          ) : (
            <form
              onSubmit={handleAddStationSubmit}
              style={{ display: 'flex', flexDirection: 'column', gap: 12 }}
              data-testid="add-station-form"
            >
              {copySource ? (
                <p>复制站内配置。现场 I/O 和跨站关系需要重新绑定。</p>
              ) : (
                <label className="af5-station-field">
                  工位类型
                  <select value={stationKind} onChange={(event) => setStationKind(event.target.value as StationKind)}>
                    <option value="PHYSICAL">实体工位</option>
                    <option value="LOGIC">虚拟逻辑工位</option>
                  </select>
                </label>
              )}
              <div>
                <label style={{ display: 'block', fontSize: 11, fontWeight: 600, marginBottom: 4 }}>
                  新工站编号 (如 ST40)
                </label>
                <input
                  type="text"
                  value={newStationId}
                  onChange={(e) => {
                    setNewStationId(e.target.value);
                    setStationErr('');
                  }}
                  style={{
                    width: '100%',
                    boxSizing: 'border-box',
                    padding: '6px 10px',
                    fontSize: 12,
                    fontFamily: 'var(--font-mono, monospace)',
                    borderRadius: 6,
                    border: '1px solid var(--border-line, #D0C9BC)',
                    background: 'var(--bg-paper, #EFECE6)',
                  }}
                  data-testid="new-station-id-input"
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: 11, fontWeight: 600, marginBottom: 4 }}>
                  新工站标题 (Station Title)
                </label>
                <input
                  type="text"
                  value={newStationTitle}
                  onChange={(e) => setNewStationTitle(e.target.value)}
                  style={{
                    width: '100%',
                    boxSizing: 'border-box',
                    padding: '6px 10px',
                    fontSize: 12,
                    borderRadius: 6,
                    border: '1px solid var(--border-line, #D0C9BC)',
                    background: 'var(--bg-paper, #EFECE6)',
                  }}
                  data-testid="new-station-title-input"
                />
              </div>

              {stationErr && (
                <div style={{ fontSize: 11, color: 'var(--af5-vermilion, #DC2626)' }}>
                  {stationErr}
                </div>
              )}

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 4 }}>
                <button type="button" className="af5-btn" onClick={onClose}>
                  取消
                </button>
                <button
                  type="submit"
                  className="af5-btn af5-btn--primary"
                  data-testid="confirm-add-station-btn"
                >
                  {copySource ? '复制工位' : '➕ 添加工站并进入'}
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
};
