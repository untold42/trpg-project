import { useLayoutEffect, useRef, useState } from "react";

type CharacterLayer = {
  image: string | undefined;
  className: string;
};

type CharacterTransitionProps = CharacterLayer;

//: 淡出 / 淡入时长（毫秒）——**必须与 `styles/Character.css` 的动画时长一致**
const FADE_MS = 175;

/** 预加载 + 解码：保证新立绘「随时可画」再开始切换，避免先空白 / 先闪。 */
function preload(src: string | undefined): Promise<void> {
  return new Promise((resolve) => {
    if (!src) {
      resolve();
      return;
    }
    const img = new Image();
    img.onload = () => {
      const d = (img as HTMLImageElement & { decode?: () => Promise<void> }).decode;
      if (typeof d === "function") {
        d.call(img).catch(() => {}).finally(() => resolve());
      } else {
        resolve();
      }
    };
    img.onerror = () => resolve();
    img.src = src;
  });
}

/**
 * 立绘切换：**先等新图 preload+decode 完成，再淡出旧图 → 淡入新图**。
 * 这样立绘可以不进「启动批量预加载」（省 233MB / 启动秒开 / 不挤爆内存），
 * 首次登场也不会空白或闪烁。
 */
function CharacterTransition({ image, className }: CharacterTransitionProps) {
  const initialLayer: CharacterLayer = { image, className };
  const currentLayerRef = useRef(initialLayer);
  const [currentLayer, setCurrentLayer] = useState(initialLayer);
  const [previousLayer, setPreviousLayer] = useState<CharacterLayer | null>(null);
  //: 递增切换号：预加载是异步的，用它丢弃「过期」的切换（快速连续换人时）
  const transitionIdRef = useRef(0);

  useLayoutEffect(() => {
    const oldLayer = currentLayerRef.current;

    if (oldLayer.image === image && oldLayer.className === className) {
      return;
    }

    const nextLayer: CharacterLayer = { image, className };
    const id = ++transitionIdRef.current;
    let cancelled = false;
    let timer: number | undefined;

    // 先等新立绘加载 + 解码完成，再开始淡出旧图 / 淡入新图
    preload(image).then(() => {
      if (cancelled || id !== transitionIdRef.current) {
        return;
      }
      setPreviousLayer(oldLayer);
      timer = window.setTimeout(() => {
        if (cancelled || id !== transitionIdRef.current) {
          return;
        }
        setPreviousLayer(null);
        setCurrentLayer(nextLayer);
        currentLayerRef.current = nextLayer;
      }, FADE_MS);
    });

    return () => {
      cancelled = true;
      if (timer !== undefined) {
        window.clearTimeout(timer);
      }
    };
  }, [image, className]);

  return previousLayer ? (
    <img
      src={previousLayer.image}
      className={`${previousLayer.className} character-fade-layer character-fade-out`}
      alt=""
    />
  ) : (
    <img
      src={currentLayer.image}
      className={`${currentLayer.className} character-fade-layer character-fade-in`}
      alt=""
    />
  );
}

export default CharacterTransition;
