// WeatherLayer.tsx
// ================
// 探索模式（大地图）专用天气动效层。**只读前端状态里的天气**，不调后端、不产事件。
//
//   rain  小雨 / 雨 / 大雨 / 暴雨 / 雷暴 / 台风   → 落雨粒子（Canvas）
//   snow  雪 / 暴雪 / 冰雹                        → 飘雪粒子（Canvas）
//   overcast 阴 / 风 / 山雾封路 / 海雾 / 沙暴      → 灰暗色罩 + 缓慢云影（CSS）
//   sun   晴 / 多云                              → 暖阳辉光（CSS）
//
// 屏幕空间叠加（不随地图平移）：pointer-events:none，绝不吃点击。
// 挂载点：GameController 的探索层里（`gameMode === "explore"` 时才渲染）。

import { useEffect, useRef } from "react";
import "../styles/WeatherLayer.css";

type Props = { weather?: string; isNight?: boolean };

type Kind = "rain" | "snow" | "overcast" | "sun" | "";

// 全部字段都必填（雨雪用到的不同，生成时都配上，省得 TS 收窄麻烦）
type Part = { x: number; y: number; sp: number; len: number; sl: number; r: number; dx: number; ph: number };

function kindOf(w: string): Kind {
  if (!w) return "";
  if (/暴雨|大雨|雷暴|台风|雨/.test(w)) return "rain";
  if (/暴雪|雪|冰雹/.test(w)) return "snow";
  if (/阴|雾|沙暴|风/.test(w)) return "overcast";
  if (/晴|多云/.test(w)) return "sun";
  return "";
}

const HEAVY = /暴雨|大雨|雷暴|台风|暴雪/;

export default function WeatherLayer({ weather = "", isNight }: Props) {
  const kind = kindOf(weather);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || (kind !== "rain" && kind !== "snow")) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const heavy = HEAVY.test(weather);
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    let W = 0, H = 0, raf = 0;
    const parts: Part[] = [];

    const resize = () => {
      const rect = canvas.parentElement?.getBoundingClientRect();
      W = Math.max(1, Math.floor(rect?.width ?? window.innerWidth));
      H = Math.max(1, Math.floor(rect?.height ?? window.innerHeight));
      canvas.width = W * dpr;
      canvas.height = H * dpr;
      canvas.style.width = `${W}px`;
      canvas.style.height = `${H}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const spawn = (randomY: boolean): Part => {
      const y = randomY ? Math.random() * H : -20;
      if (kind === "rain") {
        return { x: Math.random() * W, y, sp: (heavy ? 13 : 8) + Math.random() * 6,
                 len: 8 + Math.random() * 16, sl: 0.22 + Math.random() * 0.18,
                 r: 0, dx: 0, ph: 0 };
      }
      return { x: Math.random() * W, y, sp: 0.5 + Math.random() * 1.3,
               len: 0, sl: 0, r: 0.8 + Math.random() * 2.2,
               dx: (Math.random() - 0.5) * 0.7, ph: Math.random() * Math.PI * 2 };
    };

    resize();
    const count = kind === "rain" ? (heavy ? 460 : 190) : (heavy ? 300 : 150);
    for (let i = 0; i < count; i++) parts.push(spawn(true));

    const draw = () => {
      ctx.clearRect(0, 0, W, H);
      if (kind === "rain") {
        ctx.strokeStyle = heavy ? "rgba(186,206,236,0.62)" : "rgba(190,212,240,0.50)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        for (const p of parts) {
          ctx.moveTo(p.x, p.y);
          ctx.lineTo(p.x + p.len * p.sl, p.y + p.len);
          p.y += p.sp;
          p.x += p.sp * p.sl;
          if (p.y > H) { p.y = -p.len; p.x = Math.random() * W; }
        }
        ctx.stroke();
      } else {
        ctx.fillStyle = "rgba(255,255,255,0.88)";
        for (const p of parts) {
          const sway = Math.sin((p.y + p.ph) * 0.012) * 9;
          ctx.beginPath();
          ctx.arc(p.x + sway, p.y, p.r, 0, Math.PI * 2);
          ctx.fill();
          p.y += p.sp;
          p.x += p.dx;
          if (p.y > H + 6) { p.y = -6; p.x = Math.random() * W; }
          if (p.x < -6) p.x = W + 6;
          if (p.x > W + 6) p.x = -6;
        }
      }
      raf = requestAnimationFrame(draw);
    };
    draw();

    window.addEventListener("resize", resize);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
    };
  }, [kind, weather]);

  if (!kind) return null;

  return (
    <div className={`weather-layer w-${kind}${isNight ? " night" : ""}`} aria-hidden="true">
      <div className="weather-tint" />
      {(kind === "rain" || kind === "snow") && (
        <canvas ref={canvasRef} className="weather-canvas" />
      )}
      {kind === "overcast" && <div className="weather-cloud" />}
      {kind === "sun" && <div className="weather-sun" />}
    </div>
  );
}
