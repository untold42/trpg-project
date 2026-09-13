import {
  useCallback,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from 'react';
import { gsap } from 'gsap';
import '../styles/StaggeredMenu.css';

export interface StatusMenuProps {
  /** 菜单从哪一侧滑出 */
  position?: 'left' | 'right';
  /** 触发按钮上的文字 */
  menuLabel?: string;
  /** 强调色（标题、编号等，通过 CSS 变量 --sm-accent 使用） */
  accentColor?: string;
  /** 点击面板内容后是否自动关闭（菜单项按钮用） */
  closeOnContentClick?: boolean;
  /** 面板内容 */
  children?: ReactNode;
}

/**
 * 玩家状态菜单：左侧滑出的面板 + 左上角触发按钮。
 * 由 react-bits StaggeredMenu 精简而来，只保留：
 *   多层背景滑入 + 面板滑入 + 内容块 stagger 入场。
 */
export function StaggeredMenu({
  position = 'left',
  menuLabel = '菜单',
  accentColor = '#c0392b',
  closeOnContentClick = false,
  children,
}: StatusMenuProps) {
  const [open, setOpen] = useState(false);
  const openRef = useRef(false);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const preLayersRef = useRef<HTMLDivElement | null>(null);
  const preLayerElsRef = useRef<HTMLElement[]>([]);
  const openTlRef = useRef<gsap.core.Timeline | null>(null);
  const closeTweenRef = useRef<gsap.core.Tween | null>(null);
  const busyRef = useRef(false);

  useLayoutEffect(() => {
    const ctx = gsap.context(() => {
      const panel = panelRef.current;
      const preContainer = preLayersRef.current;
      if (!panel) return;

      const preLayers = preContainer
        ? (Array.from(preContainer.querySelectorAll('.sm-prelayer')) as HTMLElement[])
        : [];
      preLayerElsRef.current = preLayers;

      // 初始状态：所有层 + 面板都移到屏幕外，等待打开
      const offscreen = position === 'left' ? -100 : 100;
      gsap.set([panel, ...preLayers], { xPercent: offscreen, opacity: 1 });
    });
    return () => ctx.revert();
  }, [position]);

  const buildOpenTimeline = useCallback(() => {
    const panel = panelRef.current;
    if (!panel) return null;

    openTlRef.current?.kill();
    closeTweenRef.current?.kill();

    const layers = preLayerElsRef.current;
    const blocks = Array.from(
      panel.querySelectorAll('.sm-panel-content > *'),
    ) as HTMLElement[];
    const offscreen = position === 'left' ? -100 : 100;

    // 内容块初始向下偏移并透明，入场时逐块上浮
    if (blocks.length) {
      gsap.set(blocks, { y: 30, opacity: 0 });
    }

    const tl = gsap.timeline({ paused: true });

    // 1. 多层背景依次滑入
    layers.forEach((el, i) => {
      tl.fromTo(
        el,
        { xPercent: offscreen },
        { xPercent: 0, duration: 0.5, ease: 'power4.out' },
        i * 0.07,
      );
    });

    // 2. 面板主体滑入
    const lastTime = layers.length ? (layers.length - 1) * 0.07 : 0;
    const panelInsertTime = lastTime + (layers.length ? 0.08 : 0);
    tl.fromTo(
      panel,
      { xPercent: offscreen },
      { xPercent: 0, duration: 0.65, ease: 'power4.out' },
      panelInsertTime,
    );

    // 3. 内容块 stagger 入场
    if (blocks.length) {
      tl.to(
        blocks,
        {
          y: 0,
          opacity: 1,
          duration: 0.6,
          ease: 'power3.out',
          stagger: { each: 0.08, from: 'start' },
        },
        panelInsertTime + 0.2,
      );
    }

    openTlRef.current = tl;
    return tl;
  }, [position]);

  const playOpen = useCallback(() => {
    if (busyRef.current) return;
    busyRef.current = true;
    const tl = buildOpenTimeline();
    if (tl) {
      tl.eventCallback('onComplete', () => {
        busyRef.current = false;
      });
      tl.play(0);
    } else {
      busyRef.current = false;
    }
  }, [buildOpenTimeline]);

  const playClose = useCallback(() => {
    openTlRef.current?.kill();
    openTlRef.current = null;

    const panel = panelRef.current;
    if (!panel) return;
    const layers = preLayerElsRef.current;
    const offscreen = position === 'left' ? -100 : 100;

    closeTweenRef.current?.kill();
    closeTweenRef.current = gsap.to([...layers, panel], {
      xPercent: offscreen,
      duration: 0.32,
      ease: 'power3.in',
      overwrite: 'auto',
      onComplete: () => {
        const blocks = Array.from(
          panel.querySelectorAll('.sm-panel-content > *'),
        ) as HTMLElement[];
        if (blocks.length) {
          gsap.set(blocks, { y: 30, opacity: 0 });
        }
        busyRef.current = false;
      },
    });
  }, [position]);

  const toggleMenu = useCallback(() => {
    const target = !openRef.current;
    openRef.current = target;
    setOpen(target);
    if (target) {
      playOpen();
    } else {
      playClose();
    }
  }, [playOpen, playClose]);

  // 点击面板内容（菜单项）后自动关闭
  const handleContentClick = useCallback(() => {
    if (closeOnContentClick && openRef.current) toggleMenu();
  }, [closeOnContentClick, toggleMenu]);

  return (
    <div
      className="staggered-menu-wrapper"
      data-position={position}
      data-open={open || undefined}
      style={accentColor ? ({ ['--sm-accent']: accentColor } as CSSProperties) : undefined}
    >
      <div ref={preLayersRef} className="sm-prelayers" aria-hidden="true">
        <div className="sm-prelayer sm-prelayer-1" />
        <div className="sm-prelayer sm-prelayer-2" />
      </div>

      <button
        className="sm-toggle"
        onClick={toggleMenu}
        aria-label={menuLabel}
        aria-expanded={open}
        type="button"
      >
        {menuLabel}
      </button>

      <aside ref={panelRef} className="staggered-menu-panel" aria-hidden={!open}>
        <div
          className="sm-panel-inner sm-panel-content"
          onClick={closeOnContentClick ? handleContentClick : undefined}
        >
          {children}
        </div>
      </aside>
    </div>
  );
}

export default StaggeredMenu;
