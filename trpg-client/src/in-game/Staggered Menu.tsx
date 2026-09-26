import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from 'react';
import '../styles/StaggeredMenu.css';

import { useEsc } from "../escStack";

export interface StatusMenuProps {
  /** 菜单从哪一侧滑出 */
  position?: 'left' | 'right';
  /** 触发按钮上的文字 */
  menuLabel?: string;
  /** 强调色（标题、编号等，通过 CSS 变量 --sm-accent 使用） */
  accentColor?: string;
  /** 点击面板内容后是否自动关闭（菜单项按钮用） */
  closeOnContentClick?: boolean;
  /** 受控开合：传了就用外部状态（配合 hideToggle，把触发按钮放到外部按钮栏里） */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** 不渲染自带的触发按钮 */
  hideToggle?: boolean;
  /** 内容容器的类名（默认 `sm-panel-content` = 菜单 6 宫格；数据面板传 `sm-data-inner`） */
  contentClassName?: string;
  /** 面板内容 */
  children?: ReactNode;
}

/**
 * 玩家状态菜单：宣纸面板 + 左上角触发按钮。
 *
 * 开合动画 = **宣纸缓缓铺开**（纯 CSS `clip-path` 揭幕，0.6s）：
 *   左→右揭开（`position="left"`），关闭时反向收回左侧。
 * 旧的「多层背景滑入 + 面板左滑 + 内容块 stagger」已废弃删掉，不再依赖 gsap。
 */
export function StaggeredMenu({
  position = 'left',
  menuLabel = '菜单',
  accentColor = '#c0392b',
  closeOnContentClick = false,
  open: openProp,
  onOpenChange,
  hideToggle = false,
  contentClassName = 'sm-panel-content',
  children,
}: StatusMenuProps) {
  const [openState, setOpenState] = useState(false);
  const controlled = openProp !== undefined;
  const open = controlled ? !!openProp : openState;
  const openRef = useRef(false);

  // 开合统一走这里：受控时上报外部，非受控时自管
  const setMenuOpen = useCallback((target: boolean) => {
    openRef.current = target;
    if (controlled) onOpenChange?.(target);
    else setOpenState(target);
  }, [controlled, onOpenChange]);

  // 受控模式下 open 由父级决定，同步给 openRef（供 toggle / Esc 用）
  useEffect(() => { openRef.current = open; }, [open]);

  const toggleMenu = useCallback(() => {
    setMenuOpen(!openRef.current);
  }, [setMenuOpen]);

  // 点击面板内容（菜单项）后自动关闭
  const handleContentClick = useCallback(() => {
    if (closeOnContentClick && openRef.current) toggleMenu();
  }, [closeOnContentClick, toggleMenu]);

  // Esc：菜单自己也是一层（面板在上面时先退面板，再退菜单）
  useEsc(() => { if (openRef.current) toggleMenu(); }, open);

  return (
    <div
      className="staggered-menu-wrapper"
      data-position={position}
      data-open={open || undefined}
      style={accentColor ? ({ ['--sm-accent']: accentColor } as CSSProperties) : undefined}
    >
      {!hideToggle && (
        <button
          className="sm-toggle"
          onClick={toggleMenu}
          aria-label={menuLabel}
          aria-expanded={open}
          type="button"
        >
          {menuLabel}
        </button>
      )}

      <aside className="staggered-menu-panel" aria-hidden={!open}>
        <div
          className={`sm-panel-inner ${contentClassName}`}
          onClick={closeOnContentClick ? handleContentClick : undefined}
        >
          {children}
        </div>
      </aside>
    </div>
  );
}

export default StaggeredMenu;
