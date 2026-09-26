import type { SVGProps } from "react";

// ------------------------------------------------------------
// 游戏内菜单图标（8 个）
// ------------------------------------------------------------
// 统一 48×48 线性墨描：stroke = currentColor，跟按钮字色走（hover 一起变红）。
// 想换成美术图，把 GameController 里的 <IconXxx /> 换成 <img> 即可。
type IconProps = SVGProps<SVGSVGElement>;

const base: IconProps = {
    viewBox: "0 0 48 48",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round",
    strokeLinejoin: "round",
};

/** 存档游戏：卷册 + 字行 */
export function IconSave(p: IconProps) {
    return (
        <svg {...base} {...p}>
            <rect x="11" y="12" width="26" height="26" rx="3" />
            <path d="M17 20h14M17 26h14M17 32h9" />
        </svg>
    );
}

/** 放弃本轮：沙漏 */
export function IconAbandon(p: IconProps) {
    return (
        <svg {...base} {...p}>
            <path d="M15 9h18M15 39h18" />
            <path d="M17 9v6l7 9-7 9v6" />
            <path d="M31 9v6l-7 9 7 9v6" />
        </svg>
    );
}

/** 驳回本轮：左回箭头 */
export function IconReject(p: IconProps) {
    return (
        <svg {...base} {...p}>
            <path d="M18 13l-6 6 6 6" />
            <path d="M12 19h15a9 9 0 0 1 0 18h-5" />
        </svg>
    );
}

/** 势力：旗 */
export function IconFaction(p: IconProps) {
    return (
        <svg {...base} {...p}>
            <path d="M16 7v34" />
            <path d="M16 9h17l-4 7 4 7H16z" />
        </svg>
    );
}

/** 技能树：三节点树 */
export function IconSkill(p: IconProps) {
    return (
        <svg {...base} {...p}>
            <circle cx="24" cy="35" r="3" />
            <circle cx="13" cy="15" r="3" />
            <circle cx="35" cy="15" r="3" />
            <path d="M24 32c0-6-6-7-8-11M24 32c0-6 6-7 8-11" />
        </svg>
    );
}

/** 返回主菜单：屋舍 */
export function IconHome(p: IconProps) {
    return (
        <svg {...base} {...p}>
            <path d="M9 22L24 11l15 11" />
            <path d="M14 22v15h20V22" />
            <path d="M21 37v-8h6v8" />
        </svg>
    );
}

/** 任务：清单 + 勾 */
export function IconQuest(p: IconProps) {
    return (
        <svg {...base} {...p}>
            <rect x="12" y="9" width="24" height="30" rx="3" />
            <path d="M17 18l2.5 2.5L24 16" />
            <path d="M27 19h5" />
            <path d="M17 28l2.5 2.5L24 26" />
            <path d="M27 29h5" />
        </svg>
    );
}

/** 脱离卡死：从框里逃出去（箭头破框） */
export function IconUnstick(p: IconProps) {
    return (
        <svg {...base} {...p}>
            <path d="M14 13H11v24h24v-9" />
            <path d="M22 26L36 12" />
            <path d="M27 12h9v9" />
        </svg>
    );
}
