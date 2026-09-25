// 界面图「先用先解码」小工具
// ------------------------------------------------------------
// 问题：`assets/**` 的批量预加载只 `decode()` 一次、不保留引用——
// 在几百 MB 立绘的压力下，小 UI 图会被浏览器驱逐；于是面板一打开，
// CSS 背景图要现解码，出现「文字先出、背景后到」。
//
// 做法：`ensureDecoded(src)` 解码后用 **模块级 Map 保留 HTMLImageElement 引用**，
// 并在每次「要显示某个面板」前 await 一次，保证首帧就能画出来、且不易被驱逐。
// 找不到图 / 解码失败都静默放过（界面照常显示，只是没有背景图）。

const cache = new Map<string, HTMLImageElement>();

/** 确保 `src` 已解码可画；返回该图片元素（引用被缓存，避免被驱逐）。 */
export function ensureDecoded(src: string): Promise<HTMLImageElement> {
    let img = cache.get(src);
    if (!img) {
        img = new Image();
        img.src = src;
        cache.set(src, img);
    }
    const dec = (img as HTMLImageElement & { decode?: () => Promise<void> }).decode;
    if (typeof dec === "function") {
        return dec.call(img).then(() => img).catch(() => img);
    }
    return img.complete ? Promise.resolve(img) : new Promise((res) => {
        img!.onload = () => res(img!);
        img!.onerror = () => res(img!);
    });
}
