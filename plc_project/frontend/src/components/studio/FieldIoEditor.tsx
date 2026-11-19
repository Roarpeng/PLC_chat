import { useState, type FormEvent } from 'react';
import type { AfStudioWorkspaceData, SpatialInstanceNode } from '../../core/ir/afHyperGraph.types';
import {
  bindingError, cmProfiles, fieldIoOwners, fieldIoTypes, parseFieldAddress,
  type FieldIoPoint, type FieldIoType,
} from '../../core/ir/fieldIo';

export function FieldIoTable({ workspace, onSave, onDelete, onClose }: {
  workspace: AfStudioWorkspaceData;
  onSave: (point: FieldIoPoint) => string | undefined;
  onDelete: (pointId: string) => string | undefined;
  onClose: () => void;
}) {
  const [editing, setEditing] = useState<string>();
  const [name, setName] = useState('');
  const [address, setAddress] = useState('');
  const [type, setType] = useState<FieldIoType>('BOOL');
  const [error, setError] = useState('');
  const points = workspace.fieldIoPoints ?? [];
  const clear = () => { setEditing(undefined); setName(''); setAddress(''); setType('BOOL'); setError(''); };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const failure = onSave({ id: editing ?? crypto.randomUUID(), name, address, type });
    if (failure) setError(failure);
    else clear();
  };
  return (
    <div className="af5-modal-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className="af5-modal af5-field-io-modal" role="dialog" aria-modal="true" aria-label="工程 I/O 点表">
        <div className="af5-modal-header">
          <strong>工程 I/O 点表</strong>
          <button className="af5-btn" type="button" onClick={onClose} aria-label="关闭工程 I/O 点表">关闭</button>
        </div>
        <div className="af5-modal-body">
          <form className="af5-io-form" onSubmit={submit}>
            <label className="af5-station-field">点位名称<input value={name} onChange={(event) => setName(event.target.value)} /></label>
            <label className="af5-station-field">PLC 地址<input value={address} placeholder="%I0.0" onChange={(event) => setAddress(event.target.value)} /></label>
            <label className="af5-station-field">数据类型<select value={type} onChange={(event) => setType(event.target.value as FieldIoType)}>
              {fieldIoTypes.map((value) => <option key={value}>{value}</option>)}
            </select></label>
            <button className="af5-btn af5-btn--primary" type="submit">{editing ? '保存点位' : '添加点位'}</button>
            {editing && <button className="af5-btn" type="button" onClick={clear}>取消编辑</button>}
          </form>
          {error && <p role="alert">{error}</p>}
          {points.length ? (
            <table className="af5-io-table">
              <thead><tr><th>点位</th><th>PLC 地址</th><th>方向</th><th>类型</th><th>绑定设备</th><th>操作</th></tr></thead>
              <tbody>{points.map((point) => {
                const owners = fieldIoOwners(workspace, point.id);
                return <tr key={point.id}>
                  <td>{point.name}</td><td>{point.address}</td>
                  <td>{parseFieldAddress(point.address, point.type)?.direction === 'INPUT' ? '输入' : '输出'}</td><td>{point.type}</td>
                  <td>{owners.length ? owners.map(({ label, portId }) => `${label} · ${portId}`).join('、') : '未绑定'}</td>
                  <td>
                    <button className="af5-btn" type="button" aria-label={`编辑点位 ${point.name}`} onClick={() => {
                      setEditing(point.id); setName(point.name); setAddress(point.address); setType(point.type); setError('');
                    }}>编辑</button>
                    <button className="af5-btn" type="button" aria-label={`删除点位 ${point.name}`} disabled={owners.length > 0}
                      onClick={() => { const failure = onDelete(point.id); if (failure) setError(failure); else if (editing === point.id) clear(); }}>删除</button>
                  </td>
                </tr>;
              })}</tbody>
            </table>
          ) : <p>从 PLC 点表录入实际地址，再在设备属性中绑定 CM 端口。</p>}
        </div>
      </section>
    </div>
  );
}

export function CmFieldBindings({ workspace, stationId, node, onBind, onOpenPointTable }: {
  workspace: AfStudioWorkspaceData;
  stationId: string;
  node: SpatialInstanceNode;
  onBind: (portId: string, pointId: string) => string | undefined;
  onOpenPointTable: () => void;
}) {
  const [error, setError] = useState('');
  if (!node.cmProfile) return null;
  const { driver, ports, communicationPending } = cmProfiles[node.cmProfile];
  return (
    <section className="af5-card af5-cm-bindings" aria-label="CM 现场 I/O 绑定">
      <strong>CM 现场 I/O 绑定</strong>
      <span>{driver} · {node.cmProfile}</span>
      {ports.map((port) => {
        const points = (workspace.fieldIoPoints ?? []).filter((point) =>
          point.type === port.type && parseFieldAddress(point.address, point.type)?.direction === port.direction);
        return <label key={port.id} className="af5-station-field">
          {port.label}
          <small>{port.direction === 'INPUT' ? '输入' : '输出'} · {port.type}{port.optional ? ' · 选配' : ''}</small>
          <select aria-label={port.label} value={node.fieldBindings?.[port.id] ?? ''} onChange={(event) => setError(onBind(port.id, event.target.value) ?? '')}>
            <option value="">{port.optional ? '未选配' : '待绑定'}</option>
            {points.map((point) => {
              const reason = bindingError(workspace, stationId, node, port.id, point.id);
              return <option key={point.id} value={point.id} disabled={Boolean(reason)}>
                {point.address} · {point.name}{reason ? '（已占用）' : ''}
              </option>;
            })}
          </select>
        </label>;
      })}
      {communicationPending && <span>{node.cmProfile === 'Robot6Axis@1'
        ? '机器人通讯点位待定义，请按实际 KUKA 接口配置。' : '轴控制和定位反馈需按实际伺服驱动报文配置。'}</span>}
      {error && <span role="alert">{error}</span>}
      <button className="af5-btn" type="button" onClick={onOpenPointTable}>打开工程 I/O 点表</button>
    </section>
  );
}
