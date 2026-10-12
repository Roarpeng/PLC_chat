import { useCallback, useEffect, useMemo, useState } from "react";
import {
  annotatePlcDeviceCard,
  fetchPlcDeviceCard,
  listPlcDeviceCards,
  type DeviceSensorCard,
} from "../api";
import type { CanvasJumpIntent } from "./canvas/jump";

const STATUS_LABEL: Record<string, string> = {
  cited: "已引用注释",
  annotated: "工程师批注",
  meaning_unconfirmed: "含义未确认",
};

function statusClass(status: string): string {
  if (status === "annotated") return "ok";
  if (status === "cited") return "cited";
  return "unknown";
}

function parseCardId(id: string): { kind: string; name: string } {
  const idx = id.indexOf(":");
  if (idx < 0) return { kind: "tag", name: id };
  return { kind: id.slice(0, idx), name: id.slice(idx + 1) };
}

export function meaningHeadline(card: DeviceSensorCard): string {
  if (card.meaning_status === "meaning_unconfirmed" || !card.meaning_text) {
    return "含义未确认 — 工程未提供注释/HMI 文本，系统不会编造工艺含义。";
  }
  return card.meaning_text;
}

export function DeviceSensorCardView({
  card,
  busy,
  onAnnotate,
  onJumpCanvas,
}: {
  card: DeviceSensorCard;
  busy?: boolean;
  onAnnotate?: (text: string) => Promise<void> | void;
  onJumpCanvas?: (intent: CanvasJumpIntent) => void;
}) {
  const [note, setNote] = useState(card.annotation?.text || "");
  useEffect(() => {
    setNote(card.annotation?.text || "");
  }, [card.id, card.annotation?.text]);

  const users = card.used_by || [];
  return (
    <article className="io-card" aria-label={`设备卡片 ${card.symbol_name}`}>
      <header className="io-card-head">
        <div>
          {onJumpCanvas ? (
            <button
              type="button"
              className="io-jump-symbol"
              title={`定位到画布：${card.symbol_name}`}
              onClick={() => onJumpCanvas({ symbol: card.symbol_name })}
            >
              {card.symbol_name}
            </button>
          ) : (
            <strong>{card.symbol_name}</strong>
          )}
          <span className="io-card-meta">
            {[card.io_type, card.address, card.data_type, card.tag_table]
              .filter(Boolean)
              .join(" · ")}
          </span>
        </div>
        <span className={`io-status ${statusClass(String(card.meaning_status))}`}>
          {STATUS_LABEL[String(card.meaning_status)] || card.meaning_status}
        </span>
      </header>
      <p className={`io-meaning ${card.meaning_status === "meaning_unconfirmed" ? "unknown" : ""}`}>
        {meaningHeadline(card)}
      </p>
      {card.comment && card.meaning_source !== "tag_comment" ? (
        <p className="io-sub">IR 注释（低于批注）：{card.comment}</p>
      ) : null}
      {card.hardware ? (
        <p className="io-sub">
          硬件 {card.hardware.type || "device"}
          {card.hardware.address ? ` · ${card.hardware.address}` : ""}
          {card.hardware.rack ? ` · rack ${card.hardware.rack}` : ""}
        </p>
      ) : null}
      <div className="io-used">
        <div className="k">谁在用</div>
        {users.length ? (
          <ul>
            {users.map((u, i) => (
              <li key={`${u.block}-${u.access}-${u.network_id}-${i}`}>
                {onJumpCanvas ? (
                  <button
                    type="button"
                    className="io-jump-block"
                    title={`定位到画布：${u.block}`}
                    onClick={() => onJumpCanvas({ blockName: u.block })}
                  >
                    {u.block}
                  </button>
                ) : (
                  <code>{u.block}</code>
                )}{" "}
                {u.access}
                {u.network_title ? ` · ${u.network_title}` : u.network_id ? ` · ${u.network_id}` : ""}
              </li>
            ))}
          </ul>
        ) : (
          <p className="empty">图谱中暂无 READS/WRITES</p>
        )}
      </div>
      {(card.hmi_texts || []).length ? (
        <div className="io-used">
          <div className="k">HMI</div>
          <ul>
            {(card.hmi_texts || []).map((h, i) => (
              <li key={`${h.device}-${h.screen}-${i}`}>
                {h.device}/{h.screen}
                {h.text ? ` — ${h.text}` : "（无画面文本）"}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {onAnnotate ? (
        <form
          className="io-annotate"
          onSubmit={(e) => {
            e.preventDefault();
            const text = note.trim();
            if (!text) return;
            void onAnnotate(text);
          }}
        >
          <label>
            工程师批注（优先于模型/注释猜测）
            <textarea
              rows={2}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="例如：这是安全门到位，不是启动按钮"
            />
          </label>
          <button type="submit" className="btn-primary compact" disabled={busy || !note.trim()}>
            保存批注
          </button>
        </form>
      ) : null}
    </article>
  );
}

export function DeviceSensorInspect({
  jobId,
  symbol,
  onJumpCanvas,
}: {
  jobId: string;
  symbol: string;
  onJumpCanvas?: (intent: CanvasJumpIntent) => void;
}) {
  const [card, setCard] = useState<DeviceSensorCard | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setError("");
    try {
      const next = await fetchPlcDeviceCard(jobId, "tag", symbol.replace(/^#/, ""));
      setCard(next);
    } catch {
      try {
        const next = await fetchPlcDeviceCard(jobId, "device", symbol);
        setCard(next);
      } catch (exc) {
        setCard(null);
        setError(exc instanceof Error ? exc.message : "未找到该传感器卡片");
      }
    }
  }, [jobId, symbol]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) {
    return <p className="io-inline-empty">{error}</p>;
  }
  if (!card) {
    return <p className="io-inline-empty">正在加载 {symbol} 卡片…</p>;
  }
  return (
    <DeviceSensorCardView
      card={card}
      busy={busy}
      onJumpCanvas={onJumpCanvas}
      onAnnotate={async (text) => {
        const { kind, name } = parseCardId(card.id);
        setBusy(true);
        try {
          setCard(await annotatePlcDeviceCard(jobId, kind, name, text));
        } finally {
          setBusy(false);
        }
      }}
    />
  );
}

type Filter = "all" | "unconfirmed" | "DI" | "DO" | "AI" | "AO" | "device";

type DeviceCardListCounts = {
  total?: number;
  returned?: number;
  cited?: number;
  annotated?: number;
  meaning_unconfirmed?: number;
};

export function DeviceSensorPanel({
  jobId,
  focusSymbol,
  onJumpCanvas,
}: {
  jobId: string | null;
  focusSymbol?: string | null;
  onJumpCanvas?: (intent: CanvasJumpIntent) => void;
}) {
  const [cards, setCards] = useState<DeviceSensorCard[]>([]);
  const [counts, setCounts] = useState<DeviceCardListCounts>({});
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!jobId) return;
    setError("");
    try {
      const list = await listPlcDeviceCards(jobId, q.trim() ? { q: q.trim() } : undefined);
      setCards(list.cards || []);
      setCounts(list.counts || {});
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载设备卡片失败");
    }
  }, [jobId, q]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!focusSymbol) return;
    const hit = cards.find(
      (c) => c.symbol_name === focusSymbol || c.symbol_name === `#${focusSymbol}`,
    );
    if (hit) setSelectedId(hit.id);
  }, [focusSymbol, cards]);

  const visible = useMemo(() => {
    return cards.filter((c) => {
      if (filter === "unconfirmed") return c.meaning_status === "meaning_unconfirmed";
      if (filter === "device") return c.kind === "device";
      if (filter === "all") return true;
      return c.io_type === filter;
    });
  }, [cards, filter]);

  const selected = visible.find((c) => c.id === selectedId) || visible[0] || null;

  if (!jobId) {
    return <p className="empty">请先解析 PLC 工程，再查看 I/O 与传感器含义。</p>;
  }

  return (
    <div className="io-panel">
      <div className="io-toolbar">
        <input
          type="search"
          placeholder="搜索符号 / 地址 / 注释"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          aria-label="搜索设备或传感器"
        />
        <div className="io-filters" role="tablist" aria-label="过滤">
          {(
            [
              ["all", `全部 ${counts.total ?? cards.length}`],
              ["unconfirmed", `未确认 ${counts.meaning_unconfirmed ?? 0}`],
              ["DI", "DI"],
              ["DO", "DO"],
              ["device", "硬件"],
            ] as Array<[Filter, string]>
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              className={filter === key ? "on" : ""}
              onClick={() => setFilter(key)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      {counts.total ? (
        <p className="io-brief-hint">
          Q1 设备/传感器卡片 {counts.total} 张，{counts.meaning_unconfirmed || 0} 未确认含义
        </p>
      ) : null}
      {error ? <p className="empty">{error}</p> : null}
      <div className="io-split">
        <ul className="io-list" aria-label="设备与传感器">
          {visible.map((c) => (
            <li key={c.id}>
              <button
                type="button"
                className={selected?.id === c.id ? "on" : ""}
                onClick={() => setSelectedId(c.id)}
              >
                <span className="io-sym">{c.symbol_name}</span>
                <span className="io-addr">{c.address || c.io_type}</span>
                <span className={`io-status ${statusClass(String(c.meaning_status))}`}>
                  {STATUS_LABEL[String(c.meaning_status)] || c.meaning_status}
                </span>
              </button>
            </li>
          ))}
          {!visible.length ? <li className="empty-li">没有匹配的 I/O 卡片</li> : null}
        </ul>
        <div className="io-detail">
          {selected ? (
            <DeviceSensorCardView
              card={selected}
              busy={busy}
              onJumpCanvas={onJumpCanvas}
              onAnnotate={async (text) => {
                if (!jobId) return;
                const { kind, name } = parseCardId(selected.id);
                setBusy(true);
                try {
                  const next = await annotatePlcDeviceCard(jobId, kind, name, text);
                  setCards((prev) => prev.map((c) => (c.id === next.id ? next : c)));
                } finally {
                  setBusy(false);
                }
              }}
            />
          ) : (
            <p className="empty">选择一个传感器，约 30 秒内应能看到它测什么、谁在用，或明确的「未知」。</p>
          )}
        </div>
      </div>
    </div>
  );
}
