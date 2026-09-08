from pathlib import Path

# ============================================================
# 文件工具
# ============================================================

# Agent 允许操作的根目录
# 建议设置成你的项目工作目录，而不是整个电脑
WORKSPACE = Path(__file__).parent.resolve()

# 游戏数据目录：由专用工具（update_location/update_time/update_weather 等）管理，
# 禁止文件工具直接写入，防止 LLM 绕过状态工具改坏 JSON。
GAME_DATA_DIR = (WORKSPACE / "游戏数据").resolve()


def _guard_game_data(target: Path):
    """目标在 游戏数据/ 目录内时拒绝写入。"""
    try:
        target.relative_to(GAME_DATA_DIR)
    except ValueError:
        return  # 不在游戏数据目录，放行
    raise PermissionError(
        "游戏数据目录由专用工具管理（位置 update_location、时间 update_time、天气 update_weather 等），禁止用文件工具直接修改"
    )


def safe_path(path: str) -> Path:
    """
    将用户/LLM提供的路径限制在 WORKSPACE 内。
    防止 ../ 越权访问电脑上的其他文件。
    """
    target = (WORKSPACE / path).resolve()
    try:
        target.relative_to(WORKSPACE)
    except ValueError:
        raise PermissionError("禁止访问工作目录之外的文件")
    return target

# ============================================================
# ls
# ============================================================

def list_directory(path: str = "."):
    """
    查看目录内容。
    """
    try:
        target = safe_path(path)
        if not target.exists():
            return {"success": False, "error": f"目录不存在: {path}"}
        if not target.is_dir():
            return {"success": False, "error": f"不是目录: {path}"}
        files = []
        for item in sorted(target.iterdir()):
            files.append(
                {"name": item.name, "type": "directory" if item.is_dir() else "file"}
            )
        return {"success": True, "path": path, "files": files}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================
# cat
# ============================================================

def read_file(path: str):
    """
    读取文本文件。
    """
    try:
        target = safe_path(path)
        if not target.exists():
            return {"success": False, "error": f"文件不存在: {path}"}
        if not target.is_file():
            return {"success": False, "error": f"不是文件: {path}"}
        # 防止读取特别大的文件
        max_size = 1024 * 1024  # 1 MB
        if target.stat().st_size > max_size:
            return {"success": False, "error": "文件过大，禁止直接读取（超过 1MB）"}
        content = target.read_text(encoding="utf-8")
        return {"success": True, "path": path, "content": content}
    
    except UnicodeDecodeError:
        return {"success": False, "error": "该文件不是 UTF-8 文本文件"}

    except Exception as e:
        return {"success": False, "error": str(e)}

# ============================================================
# write
# ============================================================

def write_file(path: str, content: str):
    """
    创建或覆盖文件。
    """
    try:
        target = safe_path(path)
        _guard_game_data(target)
        # 自动创建父目录
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"success": True, "path": path, "message": "文件写入成功"}
    
    except Exception as e:
        return {"success": False, "error": str(e)}

# ============================================================
# edit
# ============================================================

def edit_file(path: str, old_text: str, new_text: str):
    """
    将文件中的指定文本替换成新文本。
    要求 old_text 必须在文件中存在。
    """
    try:
        target = safe_path(path)
        _guard_game_data(target)
        if not target.exists():
            return {"success": False, "error": f"文件不存在: {path}"}
        if not target.is_file():
            return {"success": False, "error": f"不是文件: {path}"}
        content = target.read_text(encoding="utf-8")
        if old_text not in content:
            return {"success": False, "error": "没有找到要修改的文本"}
        # 防止一次匹配多个位置
        count = content.count(old_text)
        if count > 1:
            return {
                "success": False,
                "error": f"目标文本出现了 {count} 次，请提供更精确的 old_text",
            }

        new_content = content.replace(old_text, new_text)
        target.write_text(new_content, encoding="utf-8")
        return {"success": True, "path": path, "message": "文件修改成功"}

    except Exception as e:
        return {"success": False, "error": str(e)}