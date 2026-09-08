from pathlib import Path

def folder_to_prompt(folder_path):
    folder = Path(folder_path)
    prompt = ""
    for file in folder.rglob("*"):
        if not file.is_file():
            continue
        try:
            content = file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            continue
        relative_path = file.relative_to(folder)
        prompt += f"""
===== 补充文件: {relative_path} =====
{content}

"""
    return prompt