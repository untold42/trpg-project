// Esc 层级栈：一次 Esc 只退一层，退的是「最后打开的那一层」。
//
// 用法（组件里一行）：
//   useEsc(() => setShowX(false), showX);      // showX 为真时才入栈
//
// 为什么要有它：面板是嵌套打开的（菜单 → 势力画廊 / 技能树 → 详情卡），
// 之前的做法是一个全局监听把面板「一次全关」，退不出层级。
// 现在谁最后打开谁最后入栈，就是 Esc 的第一个接收者。

type EscHandler = () => void;

const stack: EscHandler[] = [];
let listening = false;

function onKeyDown(e: KeyboardEvent) {
    if (e.key !== "Escape") return;
    const top = stack[stack.length - 1];
    if (!top) return;
    top();
}

function pushEsc(h: EscHandler) {
    stack.push(h);
    if (!listening) {
        document.addEventListener("keydown", onKeyDown);
        listening = true;
    }
}

function popEsc(h: EscHandler) {
    const i = stack.lastIndexOf(h);
    if (i >= 0) stack.splice(i, 1);
}

import { useEffect, useRef } from "react";

/** 把 handler 压入 Esc 栈（active 为真时）；关闭后自动出栈。 */
export function useEsc(handler: EscHandler, active: boolean = true) {
    const ref = useRef(handler);
    ref.current = handler;
    useEffect(() => {
        if (!active) return;
        const h = () => ref.current();
        pushEsc(h);
        return () => popEsc(h);
    }, [active]);
}
