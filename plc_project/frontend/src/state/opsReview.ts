/**
 * OpsReview —— 对话内"修改确认块"的纯函数层。
 *
 * 交互约定：自然语言指令产出的画布 ops 不再直接应用，而是渲染为确认卡——
 * 每条 op 给出一句话"内容理解"(工艺语言，说清楚它动什么、影响什么、何时生效)，
 * 工程师确认后才写入画布。消息里只存轻量 items(不存原始 ops——SCL 体积大，
 * 且刷新后待确认批次本就应失效)；原始 ops 由 App 以 ref 持有。
 */
export interface OpsReviewItem {
  /** 动作徽标：新增块/修改变量/追加网络/新增HMI/修改逻辑/删除块/新增标签… */
  badge: string;
  /** 一行标题：对象名 + 关键参数 */
  title: string;
  /** 内容理解：它做什么、影响什么、何时生效(工艺语言,不用术语堆砌) */
  understanding: string;
}

export interface OpsReview {
  items: OpsReviewItem[];
  status: "pending" | "applied" | "rejected" | "expired";
  /** 附注(如 LLM 的修改说明/预检结论) */
  note?: string;
}

const TYPE_LABELS: Record<string, string> = {
  FB: "功能块(带背景DB,有记忆状态)",
  FC: "函数(无记忆状态)",
  DB: "数据块",
  OB: "组织块(循环/中断入口)",
  UDT: "用户自定义类型",
};

const SECTION_LABELS: Record<string, string> = {
  VAR_INPUT: "输入区",
  VAR_OUTPUT: "输出区",
  VAR_IN_OUT: " inout 区",
  VAR_STAT: "静态区(有记忆)",
  VAR_TEMP: "临时区(每周期清零)",
  VAR: "主体区",
};

/** 单条 op → 展示项(未知 op 原样透出,绝不吞) */
export function explainOp(op: any): OpsReviewItem {
  if (!op || typeof op !== "object") {
    return { badge: "未知", title: String(op), understanding: "无法解析的操作,已原样展示。" };
  }
  switch (op.op) {
    case "add_block": {
      const b = op.block ?? {};
      const vars = Array.isArray(b.interface) ? b.interface.length : 0;
      const typeLabel = TYPE_LABELS[String(b.block_type ?? "").toUpperCase()] ?? "逻辑块";
      return {
        badge: "新增块",
        title: `创建 ${b.block_type ?? "?"} ${b.name ?? "(未命名)"}`,
        understanding: `${typeLabel}。将以草稿状态加入画布${vars ? `,含 ${vars} 个接口变量` : ""}${
          b.comment ? `；注释:${b.comment}` : ""
        }。确认后写入画布,回写博图时才进真实工程。`,
      };
    }
    case "add_variable": {
      const v = op.variable ?? {};
      const sec = SECTION_LABELS[String(v.section ?? "VAR").toUpperCase()] ?? "接口区";
      return {
        badge: "新增变量",
        title: `${op.block}.${v.name} : ${v.data_type ?? "?"}`,
        understanding: `在块 ${op.block} 的${sec}新增变量。仅影响画布草稿;若该块已导入自博图,回写时一并写入。`,
      };
    }
    case "add_network": {
      const n = op.network ?? {};
      return {
        badge: "追加网络",
        title: `${op.block} · 网络「${n.title ?? "未命名"}」`,
        understanding: `在块 ${op.block} 末尾追加一段 ${n.language ?? "SCL"} 逻辑。确认后成为草稿网络,编译/回写前可再改。`,
      };
    }
    case "add_hmi_widget": {
      const w = op.widget ?? {};
      const kind =
        w.widget_type === "button" ? "按钮" : w.widget_type === "indicator" ? "指示灯" : (w.widget_type ?? "控件");
      return {
        badge: "新增 HMI",
        title: `${kind}「${w.title ?? "未命名"}」${w.plc_tag ? `→ ${w.plc_tag}` : ""}`,
        understanding: `在 HMI 画面新增${kind}${w.plc_tag ? `,绑定标签 ${w.plc_tag}` : "(暂未绑定标签)"}。画面为草稿,回写时生成。`,
      };
    }
    case "update_hmi_widget": {
      const keys = Object.keys(op.patch ?? {});
      return {
        badge: "改 HMI",
        title: `更新控件 ${op.id ?? "?"}${keys.length ? `(${keys.join("/")})` : ""}`,
        understanding: `调整既有 HMI 控件的属性。只改画布草稿,不影响博图原件,回写时生效。`,
      };
    }
    case "update_block":
    case "update_block_scl": {
      const patch = op.op === "update_block_scl" ? { scl_body: true } : (op.patch ?? {});
      const keys = Object.keys(patch ?? {});
      const name = op.name ?? "?";
      const detail =
        keys.includes("scl_body") ? "重写块内 SCL 主体(逻辑行为变更,请结合差异理解)"
        : keys.includes("interface") ? "接口变更(会牵动背景 DB 接口,回写时刷新)"
        : keys.includes("networks") ? "网络列表变更"
        : keys.includes("comment") ? "仅更新注释(不改逻辑)"
        : keys.join("/");
      return {
        badge: keys.includes("comment") && keys.length === 1 ? "改注释" : "修改逻辑",
        title: `${name}(${detail})`,
        understanding: `对既有块 ${name} 的修改:${detail}。确认后更新画布草稿;原件在回写前保持不变。`,
      };
    }
    case "remove_block": {
      return {
        badge: "删除块",
        title: `删除 ${op.name ?? "?"}(及其 HMI 绑定)`,
        understanding: `从画布移除该块与其 HMI 绑定。博图工程中的原件不受影响,直到下次回写不再包含它。`,
      };
    }
    case "add_tag": {
      const t = op.tag ?? {};
      return {
        badge: "新增标签",
        title: `${t.name ?? "?"} ${t.data_type ?? ""} ${t.logical_address ?? ""}`.trim(),
        understanding: `新增物理 I/O 标签。回写时写入博图标签表;地址若与既有标签冲突,预检会拦截。`,
      };
    }
    default:
      return {
        badge: String(op.op ?? "未知"),
        title: JSON.stringify(op).slice(0, 60),
        understanding: "未识别的操作类型,已原样透出;确认前请人工核对。",
      };
  }
}

/** ops 批次 → 待确认视图(pending;note 为 LLM 说明/预检附注) */
export function buildOpsReview(ops: any[], note?: string): OpsReview {
  const list = Array.isArray(ops) ? ops : [];
  return {
    items: list.map(explainOp),
    status: "pending",
    note: note?.trim() || undefined,
  };
}
