import backgroundImages from "../assets/背景_重构";

// 背景控制从大模型的 bg 指令转交给 UI 事件（kind:"bg"）。
// 这里集中处理「地点 + 时辰 → 背景图」的映射，供 GameController 在收到 UI 事件时使用。

// 将十二时辰映射为白天 / 黄昏 / 黑夜
// 也接受已经算好的时段字符串（前端按当前时钟自己算时直接传）——
// 否则传「黑夜」会被当成未知时辰而回退成白天。
function convertTime(specificTime: string): string {
  const t = (specificTime || "").trim();
  if (t === "白天" || t === "黄昏" || t === "黑夜") return t;
  if (["卯时", "辰时", "巳时", "午时", "未时", "申时"].includes(t)) return "白天";
  if (t === "酉时") return "黄昏";
  if (["戌时", "亥时", "子时", "丑时", "寅时"].includes(t)) return "黑夜";
  return "白天";
}

/** 十二时辰名（索引 0=子 … 11=亥） */
export const SHICHEN_NAMES = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"];

/** 时辰索引 → 时段（白天/黄昏/黑夜）。与 convertTime 同一套规则。 */
export function periodOfShichen(i: number): string {
  if (!Number.isInteger(i) || i < 0 || i > 11) return "白天";
  return convertTime(SHICHEN_NAMES[i] + "时");
}

/** 默认背景（尚未收到任何 bg 事件时）：主页面图；没放主页面就退回任意一张已有的图 */
export const 默认背景 = (backgroundImages[`./主页面.png`] ??
  Object.values(backgroundImages)[0] ??
  "") as string;

/**
 * 取背景图（回退链）：
 *   ① 「地点/时段」 ② 「地点/白天」 ③ 「地点」下其他时段的图 ④ 主页面。
 * ③ 是给「只有一种时段图」的场景兜底（画舫只有黑夜图）——
 * 宁可看错时段，也别把背景打回主页面。
 * time 可传时辰（如「酉时」）或已转换的时段（如「黄昏」）。
 */
export function getBackgroundImage(position: string, time: string): string {
  const period = convertTime(time);
  const p_and_t = backgroundImages[`./${position}/${period}.png`] as string | undefined;
  if (p_and_t) return p_and_t;

  const just_p = backgroundImages[`./${position}/白天.png`] as string | undefined;
  if (just_p) return just_p;

  const prefix = `./${position}/`;
  for (const name of ["黄昏", "黑夜"]) {
    const hit = backgroundImages[`${prefix}${name}.png`] as string | undefined;
    if (hit) return hit;
  }
  const any = Object.keys(backgroundImages).find((k) => k.startsWith(prefix));
  if (any) return backgroundImages[any] as string;

  return 默认背景;
}
