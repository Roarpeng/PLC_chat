/**
 * 结构节点编辑（从原 GreenfieldPanel.tsx:199-474 原样迁出，props 零改）。
 *
 * 工站 / 执行单元 / 执行件增删改 + 重命名 + 重挂 + 改标签，全部走
 * `POST /patch` 的原子 op；服务端拒绝时整批回滚、画布不变。
 * GreenfieldLinkPanel 通过 GreenfieldPanel 的兼容重导出继续引用本组件。
 */
import React, { useEffect, useMemo, useState } from "react";
import type { GFCanvasOp, GFNodeKind } from "../../state/greenfield";

export interface NodeEditorProps {
  ir: Record<string, unknown> | null;
  busy?: boolean;
  onPatch: (ops: GFCanvasOp[]) => void;
}

const NODE_KIND_LABEL: Record<GFNodeKind, string> = {
  unit: "工站",
  em: "执行单元",
  cm: "执行件",
};

function asArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? (value as Array<Record<string, unknown>>) : [];
}

function str(value: unknown): string {
  return typeof value === "string" ? value : value == null ? "" : String(value);
}

interface NodeRowProps {
  id: string;
  kind: GFNodeKind;
  name: string;
  label: string;
  parentId: string;
  parents: Array<{ id: string; label: string }>;
  busy?: boolean;
  onPatch: (ops: GFCanvasOp[]) => void;
}

const NodeRow: React.FC<NodeRowProps> = ({
  id,
  kind,
  name,
  label,
  parentId,
  parents,
  busy,
  onPatch,
}) => {
  const [draftName, setDraftName] = useState(name);
  const [draftLabel, setDraftLabel] = useState(label);
  const [draftParent, setDraftParent] = useState(parentId);

  useEffect(() => {
    setDraftName(name);
    setDraftLabel(label);
    setDraftParent(parentId);
  }, [id, name, label, parentId]);

  const changed =
    draftName !== name || draftLabel !== label || (parents.length > 0 && draftParent !== parentId);

  return (
    <div className="gf-node-row" data-node-id={id}>
      <div className="gf-node-row__head">
        <span className="gf-node-kind">{NODE_KIND_LABEL[kind]}</span>
        <code className="gf-node-id">{id}</code>
        <span className="gf-muted">业务标签与名称可直接改写</span>
        <button
          type="button"
          className="gf-btn gf-btn--xs gf-btn--ghost gf-node-row__del"
          disabled={busy}
          title={`删除该${NODE_KIND_LABEL[kind]}（走 /patch remove_node）`}
          onClick={() => onPatch([{ op: "remove_node", node_id: id }])}
        >
          删除
        </button>
      </div>
      <div className="gf-node-row__fields">
        <label className="gf-node-field">
          <span>业务标签</span>
          <input
            type="text"
            value={draftLabel}
            disabled={busy}
            onChange={(e) => setDraftLabel(e.target.value)}
          />
        </label>
        <label className="gf-node-field">
          <span>名称</span>
          <input
            type="text"
            value={draftName}
            disabled={busy}
            onChange={(e) => setDraftName(e.target.value)}
          />
        </label>
        {parents.length > 0 && (
          <label className="gf-node-field">
            <span>重挂到</span>
            <select
              value={draftParent}
              disabled={busy}
              onChange={(e) => setDraftParent(e.target.value)}
            >
              {parents.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>
        )}
        <button
          type="button"
          className="gf-btn gf-btn--xs gf-btn--primary"
          disabled={busy || !changed || !draftLabel.trim()}
          title="按差异组装 rename_node / relabel_node / reparent_node 三个 op，一次原子提交"
          onClick={() => {
            const ops: GFCanvasOp[] = [];
            if (draftLabel !== label) {
              ops.push({ op: "relabel_node", node_id: id, label: draftLabel.trim() });
            }
            if (draftName !== name) {
              ops.push({ op: "rename_node", node_id: id, name: draftName.trim() });
            }
            if (parents.length > 0 && draftParent !== parentId) {
              ops.push({ op: "reparent_node", node_id: id, parent_id: draftParent });
            }
            if (ops.length > 0) onPatch(ops);
          }}
        >
          保存变更
        </button>
      </div>
    </div>
  );
};

export const NodeEditor: React.FC<NodeEditorProps> = ({ ir, busy, onPatch }) => {
  const units = useMemo(() => asArray(ir?.units), [ir]);
  const ems = useMemo(() => asArray(ir?.ems), [ir]);
  const cms = useMemo(() => asArray(ir?.cms), [ir]);

  const unitOptions = units.map((u) => ({
    id: str(u.id),
    label: str(u.business_label) || str(u.name) || str(u.id),
  }));
  const emOptions = ems.map((e) => ({
    id: str(e.id),
    label: str(e.business_label) || str(e.name) || str(e.id),
  }));

  const [addKind, setAddKind] = useState<GFNodeKind>("unit");
  const [addLabel, setAddLabel] = useState("");
  const [addName, setAddName] = useState("");
  const [addParent, setAddParent] = useState("");

  const parentOptions = addKind === "em" ? unitOptions : addKind === "cm" ? emOptions : [];

  const canAdd =
    !busy &&
    addLabel.trim().length > 0 &&
    (addKind === "unit" || addParent.length > 0);

  const submitAdd = () => {
    if (!canAdd) return;
    const label = addLabel.trim();
    const name = addName.trim() || label;
    let ops: GFCanvasOp[] = [];
    // ops 字段以服务端 IRPatch.from_dict / _apply_node_op 为准：
    // add_* 负载放 node，父节点用 parent_id，标签用 business_label（写进 node）。
    if (addKind === "unit") {
      ops = [{ op: "add_unit", node: { name, business_label: label } }];
    } else if (addKind === "em") {
      ops = [{ op: "add_em", parent_id: addParent, node: { name, business_label: label } }];
    } else {
      ops = [{ op: "add_cm", parent_id: addParent, node: { business_label: label } }];
    }
    onPatch(ops);
    setAddLabel("");
    setAddName("");
  };

  return (
    <div className="gf-node-editor" data-ui="greenfield-node-editor">
      <div className="gf-node-editor__hint">
        节点增删改 / 重命名 / 重挂 / 改标签均走 <code>POST /patch</code> 的原子 op；
        提交后由服务端重投影并刷新四视图（步序流程图 · 层级 · 时序 · 状态机），变更事件入账。
      </div>

      <div className="gf-node-add">
        <span className="gf-muted">新增：</span>
        <select
          value={addKind}
          disabled={busy}
          onChange={(e) => {
            setAddKind(e.target.value as GFNodeKind);
            setAddParent("");
          }}
        >
          <option value="unit">工站</option>
          <option value="em">执行单元</option>
          <option value="cm">执行件</option>
        </select>
        <input
          type="text"
          placeholder="业务标签（如：夹紧工位）"
          value={addLabel}
          disabled={busy}
          onChange={(e) => setAddLabel(e.target.value)}
        />
        <input
          type="text"
          placeholder="名称（可选）"
          value={addName}
          disabled={busy}
          onChange={(e) => setAddName(e.target.value)}
        />
        {parentOptions.length > 0 && (
          <select
            value={addParent}
            disabled={busy}
            onChange={(e) => setAddParent(e.target.value)}
          >
            <option value="">选择所属{addKind === "em" ? "工站" : "执行单元"}</option>
            {parentOptions.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        )}
        <button
          type="button"
          className="gf-btn gf-btn--xs gf-btn--primary"
          disabled={!canAdd}
          onClick={submitAdd}
        >
          + 新增{NODE_KIND_LABEL[addKind]}
        </button>
      </div>

      <div className="gf-node-list">
        {units.length === 0 && ems.length === 0 && cms.length === 0 && (
          <div className="gf-muted gf-node-empty">
            当前画布还没有结构节点。可先在对话中描述工艺生成首版，或直接用上方「新增」建立工站。
          </div>
        )}
        {units.map((u) => (
          <NodeRow
            key={str(u.id)}
            id={str(u.id)}
            kind="unit"
            name={str(u.name)}
            label={str(u.business_label) || str(u.name)}
            parentId=""
            parents={[]}
            busy={busy}
            onPatch={onPatch}
          />
        ))}
        {ems.map((e) => (
          <NodeRow
            key={str(e.id)}
            id={str(e.id)}
            kind="em"
            name={str(e.name)}
            label={str(e.business_label) || str(e.name)}
            parentId={str(e.unit_id)}
            parents={unitOptions}
            busy={busy}
            onPatch={onPatch}
          />
        ))}
        {cms.map((c) => (
          <NodeRow
            key={str(c.id)}
            id={str(c.id)}
            kind="cm"
            name={str(c.id)}
            label={str(c.business_label) || str(c.id)}
            parentId={str(c.em_id)}
            parents={emOptions}
            busy={busy}
            onPatch={onPatch}
          />
        ))}
      </div>
    </div>
  );
};
