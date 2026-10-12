import type { PlcProjectBrief } from "../api";
import type { CanvasJumpIntent } from "./canvas/jump";

type ProjectBriefCardProps = {
  brief: PlcProjectBrief | null;
  compact?: boolean;
  onAsk?: (prompt: string) => void;
  onOpenFull?: () => void;
  onJumpCanvas?: (intent: CanvasJumpIntent) => void;
};

function JumpChip({
  label,
  title,
  onJump,
}: {
  label: string;
  title?: string;
  onJump?: () => void;
}) {
  if (!onJump) {
    return <span className="plc-chip">{label}</span>;
  }
  return (
    <button type="button" className="plc-chip is-jump" title={title || `定位到画布：${label}`} onClick={onJump}>
      {label}
    </button>
  );
}

function countLine(counts: Record<string, number> | undefined): string {
  if (!counts) return "";
  return Object.entries(counts)
    .filter(([, n]) => n)
    .map(([k, n]) => `${k} ${n}`)
    .join(" · ");
}

export function ProjectBriefCard({ brief, compact, onAsk, onOpenFull, onJumpCanvas }: ProjectBriefCardProps) {
  if (!brief?.brief_ready && !brief?.purpose) {
    return (
      <div className="plc-brief" aria-label="工程简报">
        <div className="plc-brief-kicker">Project Brief</div>
        <p className="muted">结构清单尚未就绪。全文翻译不会阻塞简报；解析出块名后即可阅读。</p>
      </div>
    );
  }
  const calls = (brief.top_level_calls || []).slice(0, compact ? 4 : 10);
  const gaps = (brief.export_gaps || []).slice(0, compact ? 4 : 16);
  const devices = brief.device_sensor_summary?.devices || [];
  const sensors = brief.device_sensor_summary?.sensors || [];
  const prompts = brief.engineer_prompts || [];

  return (
    <div className={`plc-brief${compact ? " compact" : ""}`} aria-label="工程简报">
      <div className="plc-brief-head">
        <div>
          <div className="plc-brief-kicker">Project Brief · {brief.phase || "queued"}</div>
          <strong>{brief.purpose || brief.project_name || "未命名工程"}</strong>
        </div>
        {compact && onOpenFull ? (
          <button type="button" className="ghost compact" onClick={onOpenFull}>
            展开简报
          </button>
        ) : null}
      </div>
      <div className="plc-brief-meta">
        入口{" "}
        {brief.main_ob || brief.main_entry ? (
          <JumpChip
            label={brief.main_ob || brief.main_entry || ""}
            onJump={
              onJumpCanvas
                ? () => onJumpCanvas({ blockName: brief.main_ob || brief.main_entry || undefined })
                : undefined
            }
          />
        ) : (
          "未识别"
        )}{" "}
        · {countLine(brief.block_counts_by_status)}
      </div>
      <div className="plc-brief-run">{brief.run_logic_entry}</div>
      {calls.length ? (
        <div className="plc-brief-calls">
          顶层调用：
          {calls.map((c) => (
            <JumpChip
              key={`${c.callee}-${c.network || ""}`}
              label={c.callee || ""}
              onJump={
                onJumpCanvas && c.callee
                  ? () => onJumpCanvas({ blockName: c.callee })
                  : undefined
              }
            />
          ))}
        </div>
      ) : null}
      {!compact ? (
        <>
          <div className="plc-brief-hw">
            {brief.device_sensor_summary?.note || "设备/传感器钩子"}
            {devices.length ? (
              <div>
                设备：
                {devices.slice(0, 8).map((d) => (
                  <JumpChip
                    key={d.name}
                    label={d.name}
                    onJump={onJumpCanvas ? () => onJumpCanvas({ symbol: d.name }) : undefined}
                  />
                ))}
              </div>
            ) : (
              <div className="muted">设备：未导出/未索引</div>
            )}
            {sensors.length ? (
              <div>
                传感器：
                {sensors.slice(0, 8).map((s) => (
                  <JumpChip
                    key={s.name}
                    label={s.name}
                    onJump={onJumpCanvas ? () => onJumpCanvas({ symbol: s.name }) : undefined}
                  />
                ))}
              </div>
            ) : (
              <div className="muted">传感器：未导出/未索引</div>
            )}
          </div>
          {gaps.length ? (
            <div className="plc-brief-gaps">
              导出缺口：
              {gaps.map((g) => (
                <JumpChip
                  key={g.block}
                  label={`${g.block} · ${g.status}`}
                  onJump={onJumpCanvas ? () => onJumpCanvas({ blockName: g.block }) : undefined}
                />
              ))}
            </div>
          ) : (
            <div className="muted">无导出缺口</div>
          )}
        </>
      ) : gaps.length ? (
        <div className="muted">缺口 {gaps.length}+ · 先读结构，不必等全文翻译</div>
      ) : null}
      {onAsk && prompts.length ? (
        <div className="plc-brief-prompts" aria-label="工程师三问">
          {prompts.map((p) => (
            <button
              key={p.id}
              type="button"
              className="ghost compact"
              onClick={() => onAsk(p.prompt)}
              title={p.prompt}
            >
              {p.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
