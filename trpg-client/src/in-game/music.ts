import musicFiles from "../assets/音乐";

// 背景音乐控制：由 UI 事件 kind:"music" 触发（后端小模型选择曲目）。
// 曲库 = assets/音乐/ 下子目录：叙事探索/（叙事 BGM，选曲见 trpg-world/音乐.json）+ 战斗/ + 固定/（界面专用）。
// 曲名 = 文件名去扩展名（不含子目录）；把 mp3 丢进对应目录即自动进曲库。
const 曲库: Record<string, string> = {};
for (const [path, url] of Object.entries(musicFiles)) {
  const name = path.split("/").pop()!.replace(/\.[^.]+$/, "");
  曲库[name] = url as string;
}
console.info(`[music] 曲库载入 ${Object.keys(曲库).length} 首`);

let 当前: HTMLAudioElement | null = null;
let 当前曲 = "";
let 待播: string | null = null; // 被浏览器自动播放策略挡下的曲目，等用户手势后重试

function 开始播放(track: string) {
  const url = 曲库[track];
  if (!url) {
    console.warn("[music] 无此曲目:", track, "｜曲库:", Object.keys(曲库).join("、"));
    return;
  }
  当前?.pause();
  const audio = new Audio(url);
  audio.loop = true; // 循环播放
  audio.volume = 0.5;
  当前 = audio;
  // ⚠️ 立即置位，别等 play() 的 then：play 是异步的，若在它 resolve 前
  //    又被切走（popUiMusic 恢复旧曲），去重判断会读到旧值而跳过恢复，
  //    结果新曲在后面才响 → BGM 残留在界面上。
  当前曲 = track;
  audio
    .play()
    .then(() => {
      if (当前 === audio) {
        待播 = null;
        console.info("[music] ▶", track, "（循环）");
      }
    })
    .catch((e) => {
      if (当前 !== audio) return;   // 已被切走（切曲时 pause 会抛 AbortError）：忽略
      待播 = track;
      console.warn("[music] 播放被拦（需用户手势）:", track, e?.name);
    });
}

/** 播放/循环背景音乐。同名不重启；track 为「无」时停止播放。 */
export function playMusic(track: string) {
  if (!track || track === "无") {
    stopMusic();
    return;
  }
  if (track === 当前曲) return;
  开始播放(track);
}

// 用户任意手势后，重试被拦下的曲目（浏览器自动播放限制）
function 重试() {
  if (待播) 开始播放(待播);
}
if (typeof window !== "undefined") {
  window.addEventListener("pointerdown", 重试);
  window.addEventListener("keydown", 重试);
}

/** 停止背景音乐（离开游戏时调用）。 */
export function stopMusic() {
  当前?.pause();
  当前 = null;
  当前曲 = "";
  待播 = null;
}

/** 当前正在播放的曲名（未播放时为空串）——供界面临时换曲后恢复。 */
export function currentTrack(): string {
  return 当前曲;
}

// 界面专用曲（技能树等）：压倒游戏 BGM，关掉界面后恢复原曲。
// 存在模块里而不是组件里——“之前那首”与 当前曲 同源，不会读到旧值。
let 界面前曲: string | null = null;

/** 开始播放界面专用曲（记下当前曲，供 popUiMusic 恢复）。可重入：已压过则不覆盖存档。 */
export function pushUiMusic(track: string) {
  if (界面前曲 === null) 界面前曲 = 当前曲;
  playMusic(track);
}

/** 退出界面：恢复 pushUiMusic 之前的曲；之前没在放就停掉。没压过则不动。 */
export function popUiMusic() {
  if (界面前曲 === null) return;
  const 前 = 界面前曲;
  界面前曲 = null;
  if (前) playMusic(前);
  else stopMusic();
}
