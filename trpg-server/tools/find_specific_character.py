from pathlib import Path

CHARACTER_DIR = Path("../trpg-world/角色静态档案.md")

def find_specific_character(name: str):
    path = CHARACTER_DIR / f"{name}.md"
    if not path.exists():
        return f"没有找到人物：{name}"
    return path.read_text(encoding="utf-8")