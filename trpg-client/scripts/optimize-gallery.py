# -*- coding: utf-8 -*-
"""
画廊图片压缩脚本
================
把 src/assets/画廊/ 下的原图（png）压缩成 src/assets/画廊/web/ 下的 jpg。
原图不动，画廊代码会优先用 web/ 里的优化版。

用法（在 trpg-client 目录下）：
    python scripts/optimize-gallery.py

加了新帮派图之后跑一次即可；已有的图会自动跳过。
"""
import os

from PIL import Image

SRC = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'src', 'assets', '画廊'))
DST = os.path.join(SRC, 'web')
QUALITY = 82
MAX_WIDTH = 1920  # 原图比这个宽才缩

os.makedirs(DST, exist_ok=True)

done = skipped = 0
for f in sorted(os.listdir(SRC)):
    if not f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
        continue
    src_path = os.path.join(SRC, f)
    if not os.path.isfile(src_path):
        continue

    name = os.path.splitext(f)[0]
    out_path = os.path.join(DST, name + '.jpg')

    # 优化版比原图新就跳过
    if os.path.exists(out_path) and os.path.getmtime(out_path) >= os.path.getmtime(src_path):
        skipped += 1
        continue

    im = Image.open(src_path)
    if im.mode != 'RGB':
        im = im.convert('RGB')
    if im.width > MAX_WIDTH:
        ratio = MAX_WIDTH / im.width
        im = im.resize((MAX_WIDTH, round(im.height * ratio)), Image.LANCZOS)

    im.save(out_path, 'JPEG', quality=QUALITY, optimize=True, progressive=True)
    a, b = os.path.getsize(src_path), os.path.getsize(out_path)
    print(f'{name}: {a // 1024}KB -> {b // 1024}KB')
    done += 1

print(f'完成：压缩 {done} 张，跳过 {skipped} 张。')
print(f'输出目录：{DST}')
