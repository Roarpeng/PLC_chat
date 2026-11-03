/**
 * OnboardingScreen —— 无工程时的引导屏（product-performs · 草稿纸风）。
 *
 * 灰白制图底 + 墨线两行大标题（基线后升起）；产品第一步已经打开：
 * 下方就是工作台自己的指令输入（真实控件，data-ui），敲下工艺句子
 * 点「新建工程」文字随行进入真实对话。底部是一张工程草稿线稿
 * （一句话 → SCL → PLC → 电机 的手绘回路示意，墨线 + 钴蓝标注，
 * 纯 SVG 线稿，无照片）。页脚一行支持格式。
 */
import React from "react";
import "./OnboardingScreen.css";

export interface OnboardingScreenProps {
  /** 打开导入(文件选择 / 路径) */
  onImport(): void;
  /** 进入对话模式(新建工程 + 首对话)；携带用户已敲的工艺句子 */
  onNewFromChat(prompt?: string): void;
}

/** 底部提示:支持的解析格式（页脚左侧） */
const SUPPORTED_FORMATS = ["SimaticML XML", "TIA 标签表", "DB SCL 文本"];

/** 工程草稿线稿：工艺一句话 → SCL → PLC 机架 → 电机（墨线，钴蓝标注） */
const LoopSketch: React.FC = () => (
  <svg
    className="onb-sketch-svg"
    viewBox="0 0 720 250"
    role="img"
    aria-label="工程草稿：一句话工艺意图生成 SCL，编译后驱动机电设备的回路示意"
  >
    {/* 构造线：虚线十字与基准圈（草稿感） */}
    <g className="sk-construct">
      <line x1="24" y1="212" x2="696" y2="212" />
      <line x1="52" y1="28" x2="52" y2="222" strokeDasharray="2 7" />
      <circle cx="52" cy="212" r="9" />
      <line x1="43" y1="212" x2="61" y2="212" />
      <line x1="52" y1="203" x2="52" y2="221" />
    </g>

    {/* ① 工艺一句话：手绘对话气泡 + 三条波浪字线 */}
    <g className="sk-ink" transform="rotate(-0.8 96 96)">
      <path d="M40 52 q4 -10 16 -10 h96 q12 0 14 10 l3 44 q1 10 -12 10 h-58 l-22 20 l4 -20 h-25 q-12 0 -12 -11 z" />
      <path className="sk-wave" d="M58 66 q8 -4 16 0 t16 0 t16 0 t16 0" />
      <path className="sk-wave" d="M58 84 q8 -4 16 0 t16 0 t16 0 t16 0" />
      <path className="sk-wave" d="M58 102 q8 -4 16 0 t16 0 t16 0" />
    </g>
    <text className="sk-label" x="40" y="150">工艺一句话</text>

    {/* 手绘箭头 → */}
    <g className="sk-accent">
      <path d="M188 92 q22 -6 42 0" />
      <path d="M222 84 l10 8 -11 7" />
    </g>

    {/* ② SCL 草稿卡：代码行 + 下划线删改痕迹 */}
    <g className="sk-ink" transform="rotate(0.6 300 96)">
      <path d="M246 50 h96 q6 0 6 6 v76 q0 6 -6 6 h-96 q-6 0 -6 -6 v-76 q0 -6 6 -6 z" />
      <line x1="240" y1="68" x2="354" y2="68" />
      <text className="sk-code" x="256" y="88">IF "EStop" THEN</text>
      <text className="sk-code" x="256" y="106">#Run := FALSE;</text>
      <text className="sk-code sk-dim" x="256" y="124">#Fault := TRUE;</text>
      <path className="sk-strike" d="M256 121 q24 4 78 1" />
    </g>
    <text className="sk-label" x="246" y="150">SCL 草稿</text>

    <g className="sk-accent">
      <path d="M366 92 q22 -6 42 0" />
      <path d="M400 84 l10 8 -11 7" />
    </g>

    {/* ③ PLC 机架：CPU + 两块模块，LED 圈点 */}
    <g className="sk-ink" transform="rotate(-0.5 470 96)">
      <path d="M424 52 h92 v92 h-92 z" />
      <line x1="424" y1="86" x2="516" y2="86" />
      <line x1="424" y1="120" x2="516" y2="120" />
      <line x1="462" y1="52" x2="462" y2="144" strokeDasharray="5 5" />
      <circle className="sk-dot" cx="438" cy="66" r="3.2" />
      <circle className="sk-dot" cx="448" cy="66" r="3.2" />
      <circle className="sk-dot sk-dot--on" cx="438" cy="100" r="3.2" />
      <circle className="sk-dot" cx="448" cy="100" r="3.2" />
      <circle className="sk-dot sk-dot--on" cx="438" cy="132" r="3.2" />
      <circle className="sk-dot--on" cx="448" cy="132" r="3.2" />
      <line x1="470" y1="66" x2="508" y2="66" />
      <line x1="470" y1="100" x2="500" y2="100" />
      <line x1="470" y1="132" x2="492" y2="132" />
    </g>
    <text className="sk-label" x="424" y="166">PLC · 博图回写</text>

    {/* ④ 电机：圆 + M + 转轴，钴蓝动力线去现场（断线标记收尾） */}
    <g className="sk-ink">
      <path d="M584 86 a34 34 0 1 1 -0.1 0 z" />
      <text className="sk-m" x="574" y="112">M</text>
      <path className="sk-accent" d="M618 104 h58" strokeDasharray="7 6" />
      <path d="M648 94 l-8 20" />
      <path d="M658 94 l-8 20" />
    </g>
    <text className="sk-label sk-label--accent" x="584" y="166">M1 电机</text>

    {/* 角标：图纸标角 + 引线指向回路 */}
    <g className="sk-construct">
      <path d="M596 28 h84 v40" />
      <path d="M600 72 L556 104" strokeDasharray="none" />
      <circle cx="556" cy="104" r="2.4" fill="var(--line-2)" stroke="none" />
    </g>
    <text className="sk-label" x="604" y="46">图 1</text>
    <text className="sk-label" x="604" y="62">急停回路草稿</text>
  </svg>
);

export const OnboardingScreen: React.FC<OnboardingScreenProps> = ({ onImport, onNewFromChat }) => {
  const [prompt, setPrompt] = React.useState("");

  const startWithPrompt = () => onNewFromChat(prompt.trim() || undefined);

  return (
    <div className="onb" role="region" aria-label="开始你的工程">
      {/* 舞台顶沿：字标 + 次级动作（文字链接） */}
      <div className="onb-top">
        <span className="onb-wordmark">PLC Co-Pilot</span>
        <button type="button" className="onb-toplink" onClick={onImport}>
          导入既有工程
        </button>
      </div>

      {/* 两行标题：从基线后升起（signature move，逐行 110ms 交错） */}
      <h2 className="onb-title" aria-label="把工艺说清楚，逻辑交给我">
        <span className="onb-title__line">
          <span className="onb-title__inner">把工艺说清楚，</span>
        </span>
        <span className="onb-title__line onb-title__line--2">
          <span className="onb-title__inner">逻辑交给我。</span>
        </span>
      </h2>

      <p className="onb-sub">一句话工艺意图，Co-Pilot 生成可编译的 SCL 逻辑并回写博图。</p>

      {/* 产品第一步已经打开：工作台自己的指令输入（真实控件） */}
      <div className="onb-firststep" data-ui="workbench-first-input">
        <input
          className="onb-input"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.nativeEvent.isComposing) {
              e.preventDefault();
              startWithPrompt();
            }
          }}
          placeholder="例如：增加急停信号并红灯指示"
          aria-label="工艺需求（将带入对话）"
          spellCheck={false}
        />
        <button type="button" className="onb-start" onClick={startWithPrompt}>
          新建工程
        </button>
        <span className="onb-firststep__note">需求先行 · 确认不产生任何修改</span>
      </div>

      {/* 工程草稿线稿带：产品的世界画成草图（无照片） */}
      <div className="onb-sketch" data-ui="engineering-sketch">
        <LoopSketch />
      </div>

      {/* 页脚一行：支持格式 */}
      <footer className="onb-foot">
        <span className="onb-foot__left">支持 {SUPPORTED_FORMATS.join(" / ")}</span>
        <span className="onb-foot__right">需求先行 · 确认不产生任何修改</span>
      </footer>
    </div>
  );
};
