//预加载图片
function preloadImages(images: string[]) {
    return Promise.all(
        images.map(async (src) => {
            const img = new Image();
            img.src = src;

            try {
                await img.decode();
            } catch {
                // 忽略单张图片解码失败
            }
        })
    );
}

export default preloadImages;