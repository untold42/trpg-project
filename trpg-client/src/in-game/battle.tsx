import { useEffect, useMemo, useRef, useState } from "react";
import "../styles/Battle.css";
import { playMusic, stopMusic } from "./music";
import BattleBoard from "./BattleBoard";

// ---- 与后端 /battle/* 对齐的类型 ----
export type BattleBuff = { 名称: string; 层数?: number; 剩余回合?: number };
export type BattleCombatant = {
    名字: string; 阵营: string; 是玩家: boolean; 格: [number, number]; 朝向?: string;
    生命: number; 生命上限: number; 内力: number; 内力上限: number;
    梯度?: string; 兵器?: string; 武器类型?: string; 五行?: string;
    轻功?: number; 移动力?: number;
    buff?: BattleBuff[]; 招式?: string[];
    存活: boolean; 已撤离: boolean; 已行动: boolean; 防守: boolean; 约定撤退?: boolean;
};
export type BattleLog = { 回合?: number; 类型?: string; 文本?: string;[k: string]: unknown };
export type BattleState = {
    active: boolean; 缘由?: string; 音乐?: string; 等待玩家?: boolean; 阶段?: string; 先手方?: string;
    战场: {
        回合: number; 宽度: number; 高度: number;
        已结束: boolean; 胜方: string | null; 结束原因: string;
        参战者: BattleCombatant[];
        地形?: { 格: [number, number]; 类型: string }[];
        技能?: Record<string, { 射程?: number; 范围?: string; 内力?: number; 威力?: number; 五行?: string; 效果?: string[] }>;
    };
    最后的思路判定?: { 评价?: string; 修正?: number; 理由?: string; 模型?: string };
    日志?: BattleLog[];
    结果?: Record<string, unknown>;
};

const API = "http://localhost:5000";
const ACTIONS = ["移动", "舞剑", "防守", "技能", "交流", "撤退"] as const;
type ActionName = typeof ACTIONS[number];

type Props = {
    initial: BattleState;
    onExit: (st?: BattleState) => void;
};

// 单元格坐标 → token
function cellKey(x: number, y: number) { return `${x},${y}`; }

export default function BattleScene({ initial, onExit }: Props) {
    const [state, setState] = useState<BattleState>(initial);
    const [action, setAction] = useState<ActionName>("舞剑");
    const [target, setTarget] = useState<string>("");
    const [skill, setSkill] = useState<string>("");
    const [cell, setCell] = useState<[number, number] | null>(null);
    const [thought, setThought] = useState("");
    const [busy, setBusy] = useState(false);
    const [model, setModel] = useState("小模型");
    const [提示, set提示] = useState("");
    const logRef = useRef<HTMLDivElement>(null);

    const 战场 = state.战场;
    const 参战者 = 战场.参战者;
    const player = 参战者.find((c) => c.是玩家);
    const 招式表 = player?.招式 ?? [];
    const 技能表 = state.战场.技能 ?? {};
    const 选中技能 = 技能表[skill];
    const 是AOE = !!选中技能 && /^(区域|领域|扇形|直线|圆形)/.test(String(选中技能.范围 ?? ""));
    const 是自身 = !!选中技能 && String(选中技能.范围 ?? "") === "自身";
    const 半径 = (() => { const m = /(\d+)/.exec(String(选中技能?.范围 ?? "")); return m ? parseInt(m[1]) : 1; })();

    // 每格上的角色
    const byCell = useMemo(() => {
        const m: Record<string, BattleCombatant> = {};
        for (const c of 参战者) {
            if (c.存活 && !c.已撤离) m[cellKey(c.格[0], c.格[1])] = c;
        }
        return m;
    }, [参战者]);

    // 初始拉一次思路判定模型设置
    useEffect(() => {
        fetch(`${API}/battle/settings`).then((r) => r.json())
            .then((d) => { if (d?.思路判定模型) setModel(d.思路判定模型); })
            .catch(() => { });
    }, []);

    // 进入战斗：播放战斗 BGM；离开时停止（后续叙事音乐由调用方决定）
    useEffect(() => {
        if (initial.音乐) playMusic(initial.音乐);
        return () => stopMusic();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // 日志滚到底
    useEffect(() => {
        if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
    }, [state.日志]);

    async function 切模型(m: string) {
        setModel(m);
        try {
            await fetch(`${API}/battle/settings`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ 思路判定模型: m }),
            });
        } catch { /* 后端没起：忽略 */ }
    }

    function 选动作(a: ActionName) {
        setAction(a);
        setTarget(""); setCell(null);
        if (a === "技能" && !skill && 招式表.length) setSkill(招式表[0]);
    }

    function 点格(x: number, y: number) {
        if (action === "技能" && 是AOE) { setCell([x, y]); return; }   // AOE 中心格：任意格
        if (action === "移动") {
            // 只允许点到空格（不能移到有人处）
            if (!byCell[cellKey(x, y)]) setCell([x, y]);
            return;
        }
        const c = byCell[cellKey(x, y)];
        if (c) 点人(c.名字);
    }

    function 点人(name: string) {
        if (action === "移动") return;
        setTarget(name);
    }

    async function 出招() {
        if (busy || !state.等待玩家 || 战场.已结束) return;
        const body: Record<string, unknown> = { 动作: action, 思路: thought };
        if (action === "移动") body.目标格 = cell ?? player?.格 ?? [0, 0];
        if (action === "技能") {
            body.招式 = skill;
            if (是AOE) body.目标格 = cell ?? player?.格 ?? [0, 0];
            else body.目标 = target;
        }
        if (action === "舞剑" || action === "交流") body.目标 = target;
        setBusy(true); set提示("");
        const ctrl = new AbortController();
        const timer = setTimeout(() => ctrl.abort(), 90000);  // 90s 超时，不干等
        try {
            const res = await fetch(`${API}/battle/action`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
                signal: ctrl.signal,
            });
            const st: BattleState = await res.json();
            setState(st);
            setThought(""); setCell(null); setTarget("");
        } catch {
            set提示("结算超时/失败（后端可能在忙或未启动）。可点右上「中止」退出后重试。");
        } finally {
            clearTimeout(timer);
            setBusy(false);
        }
    }

    async function 中止() {
        try { await fetch(`${API}/battle/abort`, { method: "POST" }); } catch { /* 忽略 */ }
        onExit(state);
    }

    const 判定 = state.最后的思路判定;
    const 需目标 = action === "舞剑" || action === "交流" || (action === "技能" && !是AOE && !是自身);

    return (
        <div className="battle-overlay">
            <div className="battle-top">
                <span className="bt-title">回合 {战场.回合}</span>
                <span className="bt-tag">先手：{state.先手方 ?? "—"}</span>
                <span className="bt-tag">阶段：{state.阶段 ?? "—"}</span>
                {state.缘由 && <span className="bt-tag bt-reason">缘由：{state.缘由}</span>}
                <div className="bt-model">
                    <span>思路判定：</span>
                    {["小模型", "大模型"].map((m) => (
                        <button key={m}
                            className={"bt-model-btn" + (m === model ? " active" : "")}
                            onClick={() => 切模型(m)}>{m}</button>
                    ))}
                    <button className="bt-abort" onClick={中止}>中止</button>
                </div>
            </div>

            <div className="battle-body">
                <div className="battle-board">
                    <BattleBoard
                        战场={战场}
                        action={action}
                        selectedCell={cell}
                        target={target}
                        移动力={player?.移动力 ?? 1}
                        技能={选中技能}
                        onCellClick={点格}
                        onTokenClick={点人}
                    />
                    <div className="battle-hint">
                        {action === "移动"
                            ? <>移动（移动力 <b>{player?.移动力 ?? "?"}</b> 格）：点金色空格选择目的地；当前：<b>{cell ? `(${cell[0]},${cell[1]})` : "（未选格）"}</b></>
                            : action === "技能" && 是AOE
                                ? <>AOE「{skill}」（射程 <b>{选中技能?.射程}</b>、半径 <b>{半径}</b>）：点格子选中心；当前：<b>{cell ? `(${cell[0]},${cell[1]})` : "（未选格）"}</b></>
                                : action === "技能" && 是自身
                                    ? <>自身增益技「{skill}」：不需选目标，直接出招</>
                                    : <>点自己/敌人选择目标。当前选择：<b>{action}</b>{需目标 && <> → {target || "（未选目标）"}</>}</>}
                    </div>
                    {提示 && <div className="battle-err">{提示}</div>}
                </div>

                <div className="battle-side">
                    <div className="battle-judge">
                        {判定?.评价
                            ? <>思路判定：<b>{判定.评价}</b> {判定.修正 != null && (判定.修正 >= 0 ? `+${判定.修正}` : 判定.修正)}
                                <span className="bt-judge-reason">{判定.理由}</span>
                                <span className="bt-judge-model">（{判定.模型}）</span></>
                            : "思路判定：—"}
                    </div>
                    <div className="battle-log" ref={logRef}>
                        {(state.日志 ?? []).map((e, i) => (
                            <div key={i} className={"blog blog-" + (e.类型 ?? "")}>
                                {e.文本}
                            </div>
                        ))}
                    </div>
                </div>
            </div>

            <div className="battle-bottom">
                <div className="battle-actions">
                    {ACTIONS.map((a) => (
                        <button key={a}
                            className={"bt-act" + (a === action ? " active" : "")}
                            onClick={() => 选动作(a)}>{a}</button>
                    ))}
                </div>
                {action === "技能" && (
                    <select className="bt-skill" value={skill}
                        onChange={(e) => { setSkill(e.target.value); setCell(null); setTarget(""); }}>
                        {招式表.length
                            ? 招式表.map((s) => <option key={s} value={s}>{s}</option>)
                            : <option value="">（无可施招式）</option>}
                    </select>
                )}
                <textarea className="bt-thought" placeholder="思路（可空）：剑路怎么走、步法是否欺诈……写得好会加伤害"
                    value={thought} onChange={(e) => setThought(e.target.value)} />
                <button className="bt-submit"
                    disabled={busy || !state.等待玩家 || 战场.已结束
                        || (action === "移动" && !cell)
                        || (action === "技能" && 是AOE && !cell)}
                    onClick={出招}>{busy ? "结算中…" : "出招"}</button>
            </div>

            {战场.已结束 && (
                <div className="battle-result">
                    <h2>{战场.胜方 ? `${战场.胜方}胜` : "战斗结束"}</h2>
                    <p>{战场.结束原因}</p>
                    <button onClick={() => onExit(state)}>返回</button>
                </div>
            )}
        </div>
    );
}
