import React, { useState } from 'react';
import type { DriverMotherClass, SpatialNodeTheme } from '../../core/ir/afHyperGraph.types';
import type { CmDeviceProfile } from '../../core/ir/fieldIo';
import '../../styles/afStudioV5.css';

export interface MotherClassCategory {
  id: 'Cylinder2Pos' | 'SingleAxisServo' | 'VacuumSucker' | 'Robot6Axis' | 'PneumaticGripper' | 'DigitalSensor' | 'MotorStartStop';
  nameZh: string;
  nameEn: string;
  standardClass: string;
  driverClass: DriverMotherClass;
  cmProfile: CmDeviceProfile;
  theme: SpatialNodeTheme;
  typicalActions: string[];
  description: string;
  defaultTitlePrefix: string;
  defaultDbPrefix: string;
}

export const MOTHER_CLASS_CATEGORIES: MotherClassCategory[] = [
  {
    id: 'Cylinder2Pos',
    nameZh: '双位气缸',
    nameEn: 'Cylinder2Pos',
    standardClass: 'Cylinder2Pos',
    driverClass: 'FB_AF_Actuator2Pos',
    cmProfile: 'Cylinder2Pos@1',
    theme: 'emerald',
    typicalActions: ['伸出/缩回', '伸出到位/缩回到位'],
    description: '标准气动双位执行器，内聚原位/动位双磁开与到位检测',
    defaultTitlePrefix: '气缸',
    defaultDbPrefix: 'Cyl',
  },
  {
    id: 'SingleAxisServo',
    nameZh: '单轴伺服',
    nameEn: 'SingleAxisServo',
    standardClass: 'SingleAxisServo',
    driverClass: 'FB_AF_AxisMotion',
    cmProfile: 'ServoAxis@1',
    theme: 'klein',
    typicalActions: ['回原点', '绝对定位', '停止'],
    description: '高精度多点位伺服定位轴，支持工位配方目标位置示教',
    defaultTitlePrefix: '伺服轴',
    defaultDbPrefix: 'Axis',
  },
  {
    id: 'VacuumSucker',
    nameZh: '真空吸盘',
    nameEn: 'VacuumSucker',
    standardClass: 'VacuumSucker',
    driverClass: 'FB_AF_Vacuum',
    cmProfile: 'Vacuum@1',
    theme: 'amber',
    typicalActions: ['吸附/释放', '负压检测', '破真空'],
    description: '真空发生器与负压吸盘，内聚负压表信号与破空吹气阀',
    defaultTitlePrefix: '真空吸盘',
    defaultDbPrefix: 'Vac',
  },
  {
    id: 'Robot6Axis',
    nameZh: '六轴机器人',
    nameEn: 'Robot6Axis',
    standardClass: 'Robot6Axis',
    driverClass: 'FB_AF_Robot6Axis',
    cmProfile: 'Robot6Axis@1',
    theme: 'klein',
    typicalActions: ['作业请求', '作业应答', '安全区握手'],
    description: '六自由度工业机器人，包含干涉区安全互锁与多工艺轨迹',
    defaultTitlePrefix: '机器人',
    defaultDbPrefix: 'Robot',
  },
  {
    id: 'PneumaticGripper',
    nameZh: '气动夹爪',
    nameEn: 'PneumaticGripper',
    standardClass: 'PneumaticGripper',
    driverClass: 'FB_AF_Gripper',
    cmProfile: 'Gripper@1',
    theme: 'emerald',
    typicalActions: ['夹紧/松开', '带料保压', '防掉料保护'],
    description: '平行气动夹爪，内聚工件在位光电与断电保压安全回路',
    defaultTitlePrefix: '气动夹爪',
    defaultDbPrefix: 'Grip',
  },
  {
    id: 'DigitalSensor',
    nameZh: '数字传感器',
    nameEn: 'DigitalSensor',
    standardClass: 'DigitalSensor',
    driverClass: 'FB_AF_DigitalInput',
    cmProfile: 'DigitalInput@1',
    theme: 'ink',
    typicalActions: ['读取数字输入', '到位检测'],
    description: '被动读取 PLC 数字输入，提供工具在位等状态',
    defaultTitlePrefix: '传感器',
    defaultDbPrefix: 'Sens',
  },
  {
    id: 'MotorStartStop',
    nameZh: '启停电机',
    nameEn: 'MotorStartStop',
    standardClass: 'MotorStartStop',
    driverClass: 'FB_AF_MotorStartStop',
    cmProfile: 'MotorStartStop@1',
    theme: 'klein',
    typicalActions: ['启动/停止', '运行/停机反馈'],
    description: '用于启停电机和同类输送设备，支持运行与故障反馈。',
    defaultTitlePrefix: '电机',
    defaultDbPrefix: 'Motor',
  },
];

export interface MotherClassPaletteProps {
  isCollapsed?: boolean;
  onToggleCollapse?: () => void;
  onAddNode?: (category: MotherClassCategory) => void;
  currentStationId?: string;
}

export const MotherClassPalette: React.FC<MotherClassPaletteProps> = ({
  isCollapsed = false,
  onToggleCollapse,
  onAddNode,
  currentStationId = 'ST20',
}) => {
  const [searchQuery, setSearchQuery] = useState('');

  const filteredCategories = MOTHER_CLASS_CATEGORIES.filter((item) => {
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase().trim();
    return (
      item.nameZh.toLowerCase().includes(q) ||
      item.nameEn.toLowerCase().includes(q) ||
      item.standardClass.toLowerCase().includes(q) ||
      item.typicalActions.some((a) => a.toLowerCase().includes(q))
    );
  });

  const handleDragStart = (e: React.DragEvent, item: MotherClassCategory) => {
    e.dataTransfer.setData('application/af-mother-class', JSON.stringify(item));
    e.dataTransfer.setData('text/plain', item.standardClass);
    e.dataTransfer.effectAllowed = 'copy';
  };

  const handleAdd = (item: MotherClassCategory) => {
    if (onAddNode) {
      onAddNode(item);
    }
  };

  if (isCollapsed) {
    return (
      <aside
        className="af5-palette-collapsed"
        style={{
          width: 48,
          flexShrink: 0,
          background: 'var(--bg-paper, #EFECE6)',
          borderRight: '1px solid var(--border-line, #D0C9BC)',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          padding: '12px 0',
          gap: 12,
          userSelect: 'none',
          transition: 'width 0.2s ease',
        }}
        data-testid="mother-class-palette-collapsed"
      >
        <button
          type="button"
          className="af5-btn"
          style={{ width: 34, height: 34, padding: 0, borderRadius: 8 }}
          onClick={onToggleCollapse}
          title="展开驱动母版库"
          aria-label="展开驱动母版库"
          data-testid="expand-palette-btn"
        >
          ▶
        </button>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
          {MOTHER_CLASS_CATEGORIES.map((item) => (
            <div
              key={item.id}
              draggable
              onDragStart={(e) => handleDragStart(e, item)}
              onClick={() => handleAdd(item)}
              title={`${item.nameZh} (${item.standardClass}) - 点击添加或拖拽到画布`}
              style={{
                width: 34,
                height: 34,
                borderRadius: 8,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 11,
                fontWeight: 700,
                cursor: 'grab',
                border: '1px solid var(--border-line, #D0C9BC)',
                background: 'var(--bg-card, #F7F4EE)',
              }}
              data-testid={`mini-palette-item-${item.id}`}
            >
              {item.nameZh.slice(0, 1)}
            </div>
          ))}
        </div>
      </aside>
    );
  }

  return (
    <aside
      className="af5-sidebar-left af5-mother-class-palette"
      style={{
        width: 240,
        flexShrink: 0,
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        background: 'var(--bg-paper, #EFECE6)',
        borderRight: '1px solid var(--border-line, #D0C9BC)',
        padding: '12px 14px',
        gap: 10,
        overflow: 'hidden',
        userSelect: 'none',
        transition: 'width 0.2s ease',
      }}
      data-testid="mother-class-palette"
    >
      {/* 调色板头部 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          paddingBottom: 8,
          borderBottom: '1px solid var(--border-line, #D0C9BC)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 13, fontWeight: 700, letterSpacing: '0.02em' }}>
            驱动母版库
          </span>
          <span
            style={{
              fontSize: 10,
              padding: '1px 5px',
              borderRadius: 4,
              background: 'var(--af5-klein-soft, rgba(37, 99, 235, 0.10))',
              color: 'var(--af5-klein, #2563EB)',
              fontWeight: 600,
            }}
          >
            6 类
          </span>
        </div>

        {onToggleCollapse && (
          <button
            type="button"
            className="af5-btn"
            style={{ padding: '2px 6px', fontSize: 11, borderRadius: 6 }}
            onClick={onToggleCollapse}
            title="折叠驱动母版库"
            aria-label="折叠驱动母版库"
            data-testid="collapse-palette-btn"
          >
            ◀
          </button>
        )}
      </div>

      {/* 搜索与过滤 */}
      <div style={{ position: 'relative' }}>
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="搜索母版或动作..."
          style={{
            width: '100%',
            boxSizing: 'border-box',
            padding: '5px 8px',
            fontSize: 11,
            borderRadius: 6,
            border: '1px solid var(--border-line, #D0C9BC)',
            background: 'var(--bg-card, #F7F4EE)',
            color: 'var(--ink-primary, #161514)',
            outline: 'none',
          }}
          data-testid="palette-search-input"
        />
        {searchQuery && (
          <button
            type="button"
            onClick={() => setSearchQuery('')}
            style={{
              position: 'absolute',
              right: 6,
              top: '50%',
              transform: 'translateY(-50%)',
              border: 'none',
              background: 'transparent',
              cursor: 'pointer',
              color: 'var(--ink-tertiary, #8C887B)',
              fontSize: 11,
            }}
          >
            ×
          </button>
        )}
      </div>

      {/* 母版列表 */}
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
          paddingRight: 2,
        }}
        data-testid="palette-items-list"
      >
        {filteredCategories.map((item) => {
          return (
            <div
              key={item.id}
              draggable
              onDragStart={(e) => handleDragStart(e, item)}
              onDoubleClick={() => handleAdd(item)}
              className="af5-card"
              style={{
                padding: '8px 10px',
                borderRadius: 8,
                background: 'var(--bg-card, #F7F4EE)',
                border: '1px solid var(--border-line, #D0C9BC)',
                cursor: 'grab',
                display: 'flex',
                flexDirection: 'column',
                gap: 5,
                transition: 'box-shadow 0.15s ease, border-color 0.15s ease',
              }}
              data-testid={`palette-item-${item.id}`}
            >
              {/* 标题栏 */}
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span
                    style={{
                      fontSize: 12,
                      fontWeight: 700,
                      color: 'var(--ink-primary, #161514)',
                    }}
                  >
                    {item.nameZh}
                  </span>
                  <span
                    style={{
                      fontSize: 10,
                      fontFamily: 'var(--font-mono, monospace)',
                      color: 'var(--ink-secondary, #5C5A55)',
                    }}
                  >
                    {item.standardClass}
                  </span>
                </div>

                <button
                  type="button"
                  className="af5-btn"
                  style={{
                    padding: '1px 6px',
                    fontSize: 11,
                    height: 22,
                    borderRadius: 4,
                  }}
                  onClick={(e) => {
                    e.stopPropagation();
                    handleAdd(item);
                  }}
                  title={`添加到当前工站 (${currentStationId})`}
                  data-testid={`add-node-btn-${item.id}`}
                >
                  +
                </button>
              </div>

              {/* 典型动作标签 */}
              <div
                style={{
                  display: 'flex',
                  flexWrap: 'wrap',
                  gap: 4,
                  marginTop: 2,
                }}
              >
                {item.typicalActions.map((act) => (
                  <span
                    key={act}
                    style={{
                      fontSize: 10,
                      padding: '1px 5px',
                      borderRadius: 4,
                      background: 'var(--bg-subtle, #E5E0D5)',
                      color: 'var(--ink-secondary, #5C5A55)',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {act}
                  </span>
                ))}
              </div>

              {/* 描述信息 */}
              <div
                style={{
                  fontSize: 10,
                  color: 'var(--ink-tertiary, #8C887B)',
                  lineHeight: 1.3,
                  marginTop: 2,
                }}
              >
                {item.description}
              </div>
            </div>
          );
        })}

        {filteredCategories.length === 0 && (
          <div
            style={{
              padding: 16,
              textAlign: 'center',
              color: 'var(--ink-tertiary, #8C887B)',
              fontSize: 11,
            }}
          >
            未检索到匹配的驱动母版
          </div>
        )}
      </div>

      {/* 底部提示 */}
      <div
        style={{
          paddingTop: 8,
          borderTop: '1px solid var(--border-line, #D0C9BC)',
          fontSize: 10,
          color: 'var(--ink-tertiary, #8C887B)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <span>双击或拖拽实例入站</span>
        <span style={{ fontFamily: 'var(--font-mono, monospace)' }}>
          {currentStationId}
        </span>
      </div>
    </aside>
  );
};
