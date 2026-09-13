import backgroundImages from "../assets/背景";

// 背景控制从大模型的 bg 指令转交给 UI 事件（kind:"bg"）。
// 这里集中处理「地点 + 时辰 → 背景图」的映射，供 GameController 在收到 UI 事件时使用。

// 将十二时辰映射为白天 / 黄昏 / 黑夜
function convertTime(specificTime: string): string {
  if (["卯时", "辰时", "巳时", "午时", "未时", "申时"].includes(specificTime)) return "白天";
  if (specificTime === "酉时") return "黄昏";
  if (["戌时", "亥时", "子时", "丑时", "寅时"].includes(specificTime)) return "黑夜";
  return "白天";
}

/** 默认背景（尚未收到任何 bg 事件时） */
export const 默认背景 = backgroundImages[`./主页面.png`] as string;

/**
 * 取背景图：
 * 优先「地点/时段」，其次「地点/白天」，都没有则回落到主页面。
 * time 可传时辰（如「酉时」）或已转换的时段（如「黄昏」）。
 */
export function getBackgroundImage(position: string, time: string): string {
  const period = convertTime(time);
  const p_and_t = backgroundImages[`./${position}/${period}.png`] as string | undefined;
  if (p_and_t) return p_and_t;

  const just_p = backgroundImages[`./${position}/白天.png`] as string | undefined;
  if (just_p) return just_p;

  return 默认背景;
}
