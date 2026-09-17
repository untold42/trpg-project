export type chat = {
  type: "chat";
  speaker: string;
  // 立绘表情：由引擎（小模型 expression_sim）填充，可能缺省（无立绘资源时）
  expression?: string;
  content: string;
};

export type narration = {
  type: "narration"
  content: string;
}

// UI 事件：由本地小模型 / 后端工具产生（旁路），不是大模型叙事。
// 【职责划分】大模型只负责 chat / narration；UI 事件由小模型负责。
// 例：背景切换 { type:"ui", kind:"bg", data:{ position, time } }
//     { type:"ui", kind:"music", data:{ track } }
//     { type:"ui", kind:"mode", data:{ mode: "explore"|"narrative" } }  切模式
//     { type:"ui", kind:"battle", data:{...} }                          开战斗
//     { type:"ui", kind:"minigame", data:{ game, sessionId } }
export type ui_event = {
  type: "ui";
  kind: string;
  data: Record<string, unknown>;
};

export type instruction = chat | narration | ui_event;
