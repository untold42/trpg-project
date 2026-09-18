# -*- coding: utf-8 -*-
"""把整个文件夹拼成一段提示文本（供规则层全量注入）。

**注入前剥掉 markdown 标记**：模型不需要加粗 / 标题井号 / 反引号，它们只占 token。
（`.md` 文件本身仍保持好看、给人读；只有"送进 prompt 的那一份"被清洗。）
"""

import re
from pathlib import Path

_HEADING = re.compile(r"^#{1,6}[ \t]*", re.M)   # ## 标题
_QUOTE = re.compile(r"^>[ \t]?", re.M)          # > 引用


def strip_markdown(text: str) -> str:
    """剥掉纯装饰性的 markdown 标记（不改语义）。"""
    text = text.replace("**", "").replace("*", "")   # 加粗 / 斜体
    text = text.replace("`", "")                      # 反引号
    text = _HEADING.sub("", text)                     # 标题井号
    text = _QUOTE.sub("", text)                       # 引用符号
    return text


def folder_to_prompt(folder_path, clean: bool = True):
    folder = Path(folder_path)
    prompt = ""
    for file in folder.rglob("*"):
        if not file.is_file():
            continue
        try:
            content = file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            continue
        if clean:
            content = strip_markdown(content)
        relative_path = file.relative_to(folder)
        prompt += f"""
===== 补充文件: {relative_path} =====
{content}

"""
    return prompt
