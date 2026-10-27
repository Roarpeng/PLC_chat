/**
 * OnboardingScreen —— 无工程时的引导屏(docs/25 §3,S 线)。
 *
 * 取代旧启动屏,主区中央两张大卡片:
 *   1. 导入工程:上传 IO 表 / DB 定义 / 项目文件(.xlsx/.txt/.xml/.zip);
 *   2. 新建工程:进入对话模式(新建工程 + 首对话),描述工艺需求自动生成。
 * 底部标注支持的解析格式(SimaticML XML / TIA 标签表 / DB SCL 文本)。
 *
 * 低调工业感:制图纸网格底 + 方角卡片 + 钢蓝唯一强调,不做花哨 landing page。
 * 样式走 OnboardingScreen.css(前缀 onb-)与现有设计令牌;入口动作全部
 * 由上层接线(与 ImportDialog / 新建工程流的整合在 L/P 线)。
 */
import React from "react";
import "./OnboardingScreen.css";

export interface OnboardingScreenProps {
  /** 打开导入(文件选择 / 路径) */
  onImport(): void;
  /** 进入对话模式(新建工程 + 首对话) */
  onNewFromChat(): void;
}

/** 导入卡片展示的文件扩展名 */
const IMPORT_FORMATS = [".xlsx", ".txt", ".xml", ".zip"];

/** 底部提示:支持的解析格式 */
const SUPPORTED_FORMATS = ["SimaticML XML", "TIA 标签表", "DB SCL 文本"];

export const OnboardingScreen: React.FC<OnboardingScreenProps> = ({ onImport, onNewFromChat }) => (
  <div className="onb" data-ui="onboarding-screen" role="region" aria-label="开始你的工程">
    <div className="onb-head">
      <svg className="onb-mark" width="26" height="26" viewBox="0 0 100 100" aria-hidden="true">
        <rect width="100" height="100" fill="#1E5F97" />
        <rect x="20" y="32" width="60" height="9" fill="#fff" />
        <rect x="20" y="47" width="40" height="9" fill="#fff" />
        <rect x="20" y="62" width="50" height="9" fill="#fff" />
      </svg>
      <h2 className="onb-title">开始你的工程</h2>
      <p className="onb-sub">
        工程是画布与对话的容器 —— 导入既有资料,或直接描述工艺需求,由 Co-Pilot 自动生成
      </p>
    </div>

    <div className="onb-cards">
      {/* 入口 1:导入工程(IO 表 / DB 定义 / 项目文件) */}
      <button type="button" className="onb-card" onClick={onImport}>
        <span className="onb-card__mark" aria-hidden="true">
          <svg width="18" height="18" viewBox="0 0 20 20" aria-hidden="true">
            <path
              d="M10 2.5v9M6.4 8.2 10 11.8l3.6-3.6M3 14.2v2.3h14v-2.3"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </span>
        <span className="onb-card__title">导入工程</span>
        <span className="onb-card__text">上传 IO 表、DB 定义或项目文件,自动解析为工程画布</span>
        <span className="onb-card__chips">
          {IMPORT_FORMATS.map((fmt) => (
            <span className="onb-chip" key={fmt}>
              {fmt}
            </span>
          ))}
        </span>
      </button>

      {/* 入口 2:新建工程(对话描述工艺 → 自动生成) */}
      <button type="button" className="onb-card onb-card--primary" onClick={onNewFromChat}>
        <span className="onb-card__mark" aria-hidden="true">
          <svg width="18" height="18" viewBox="0 0 20 20" aria-hidden="true">
            <path d="M10 2.2 11.9 8 17.8 10 11.9 12 10 17.8 8.1 12 2.2 10 8.1 8Z" fill="currentColor" />
            <path d="M16 2.6l.9 2.3 2.3.9-2.3.9-.9 2.3-.9-2.3-2.3-.9 2.3-.9Z" fill="currentColor" opacity="0.55" />
          </svg>
        </span>
        <span className="onb-card__title">新建工程</span>
        <span className="onb-card__text">在对话中描述工艺需求,Co-Pilot 自动生成逻辑块与画布</span>
        <span className="onb-card__hint">对话描述 → 自动生成</span>
      </button>
    </div>

    <div className="onb-foot">
      <span className="onb-foot__label">支持格式</span>
      {SUPPORTED_FORMATS.map((fmt) => (
        <span className="onb-chip" key={fmt}>
          {fmt}
        </span>
      ))}
    </div>
  </div>
);
