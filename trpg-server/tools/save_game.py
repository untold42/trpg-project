from pathlib import Path

PATH = Path("../trpg-world/存档流程.md")
with open(PATH, "r", encoding="utf-8") as f:
    content = f.read()
def save_game():
    return content