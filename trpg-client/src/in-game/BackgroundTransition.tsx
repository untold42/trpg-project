import { useEffect, useRef, useState } from "react";

type BackgroundTransitionProps = {
  image: string;
};

//: 交叉淡入淡出时长（毫秒）—— **必须与 `styles/Background.css` 的动画时长一致**
const FADE_MS = 500;

/** 预加载图片（含 decode）——保证开始淡入时新图已经可画，避免“淡入还是旧图、随后啪一下换新图”。 */
function preload(src: string): Promise<void> {
  return new Promise((resolve) => {
    if (!src) {
      resolve();
      return;
    }
    const img = new Image();
    img.onload = () => {
      // decode() 保证**解码完成**（不只是下载完成）再切换，避免首帧空白闪烁
      const d = (img as HTMLImageElement & { decode?: () => Promise<void> }).decode;
      if (typeof d === "function") {
        d.call(img).catch(() => {}).finally(() => resolve());
      } else {
        resolve();
      }
    };
    img.onerror = () => resolve(); // 加载失败也继续，交给 <img> 自己处理（保持原行为）
    img.src = src;
  });
}

function BackgroundTransition({ image }: BackgroundTransitionProps) {
  const currentImageRef = useRef(image);
  const [currentImage, setCurrentImage] = useState(image);
  const [previousImage, setPreviousImage] = useState<string | null>(null);
  //: 递增的切换号：预加载是异步的，用它丢弃“过期”的切换（快速连续换背景时）
  const transitionIdRef = useRef(0);

  useEffect(() => {
    if (image === currentImageRef.current) {
      return;
    }
    const id = ++transitionIdRef.current;
    let cancelled = false;
    let timer: number | undefined;

    // 先等新图加载 + 解码完成，再开始交叉淡化
    preload(image).then(() => {
      if (cancelled || id !== transitionIdRef.current) {
        return;
      }
      setPreviousImage(currentImageRef.current);
      timer = window.setTimeout(() => {
        if (cancelled || id !== transitionIdRef.current) {
          return;
        }
        setPreviousImage(null);
        setCurrentImage(image);
        currentImageRef.current = image;
      }, FADE_MS);
    });

    return () => {
      cancelled = true;
      if (timer !== undefined) {
        window.clearTimeout(timer);
      }
    };
  }, [image]);

  return previousImage ? (
    <>
      <img
        src={previousImage}
        className="background-image background-fade-layer background-fade-out"
        alt=""
      />

      <img
        src={image}
        className="background-image background-fade-layer background-fade-in"
        alt=""
      />
    </>
  ) : (
    <img
      src={currentImage}
      className="background-image"
      alt=""
    />
  );
}

export default BackgroundTransition;
