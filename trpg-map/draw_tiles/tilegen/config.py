import os


# ============================================================
# 文件配置
# ============================================================

# 本项目根目录（tilegen/ 的上一级）= draw_tiles/
# 输入数据在 trpg-map/数据/；输出（tiles/）在 draw_tiles/
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

# 数据目录：trpg-map/数据/（与 draw_tiles/ 同级）
DATA_DIR = os.path.join(os.path.dirname(PROJECT_ROOT), "数据")

# ---- 城市（决定数据源与画框）----
# 可用 TRPG_CITY 环境变量覆盖
CITY = os.environ.get("TRPG_CITY", "扬州")

INPUT_FILE = os.path.join(
    DATA_DIR,
    f"{CITY}_南宋世界.json"   # 南宋世界（含布点），瓦片与点击层同源
)

# ---- 画框：与 PBF 裁剪共用同一份定义（trpg-map/城市.py）----
# 这是本文件最重要的约束：裁剪与取景必须一致，
# 否则会重现“数据里大半天生没被画出来”的老问题。
import sys as _sys

_MAP_ROOT = os.path.dirname(PROJECT_ROOT)

if _MAP_ROOT not in _sys.path:
    _sys.path.insert(0, _MAP_ROOT)

from 城市 import frame_bbox as _frame_bbox, map_id as _map_id  # noqa: E402

FRAME = _frame_bbox(CITY)                 # (min_lon, min_lat, max_lon, max_lat)

# 一城市一个瓦片目录：draw_tiles/tiles/<map_id>/，避免双城互相覆盖
OUTPUT_DIR = os.path.join(
    PROJECT_ROOT,
    "tiles",
    _map_id(CITY)
)

TILE_SIZE = 256

MIN_ZOOM = 11
MAX_ZOOM = 16

# 是否跳过没有任何对象的空瓦片
# 16:9 强制画框模式下建议保持 False（铺满整个矩形，边缘留白也生成）
SKIP_EMPTY_TILES = False


# ============================================================
# 画框说明
#
# 画框不再由数据自动推导（那会和上游 PBF 裁剪不一致），
# 而是读 trpg-map/城市.py 的 CITIES[城市]（中心 + 画框宽），
# 保证「PBF 裁到哪」= 「瓦片画到哪」。
# ============================================================


# ============================================================
# 风格总览：A —— 古地图 / 木刻版画
#
# 只有四类色：纸、墨、赭石（路）、青绿（水木）。
# 房屋不绘制（民居已在 classifier 中排除），POI 由前端 icon 承担。
# ============================================================

# ---- 纸底 ----
BACKGROUND_COLOR = (220, 177, 108)      # #DCB16C

# ---- 墨（轮廓 / 文字） ----
INK_COLOR = (58, 48, 36)                # #3A3024
LIGHT_INK = (112, 98, 76)               # #70624C
FAINT_INK = (156, 142, 116)             # #9C8E74


# ============================================================
# 水（偏灰、偏深）
# ============================================================

WATER_COLOR = (118, 137, 142)           # #76898E 深灰青
WATER_OUTLINE = (62, 80, 85)            # #3E5055 水岸线

# 水道（线状河渠）：直接用深灰青画线，无河岸
RIVER_COLOR = (100, 120, 126)           # #64787E
RIVER_BANK = (150, 168, 170)            # 保留（不再使用）

WAVE_COLOR = (140, 158, 162)


# ============================================================
# 土地
# ============================================================

FARMLAND_COLOR = (232, 206, 140)        # #E8CE8C 农田（比底色浅，留出对比）
FARMLAND_HATCH = (188, 160, 92)         # 农田斜线

FOREST_COLOR = (128, 148, 92)           # #80945C 林地
FOREST_DOT = (96, 116, 66)              # 林地密点

GRASS_COLOR = (176, 186, 106)           # #B0BA6A 草地（偏绿，拉开与底色）

CEMETERY_COLOR = (196, 176, 132)        # #C4B084 墓地

SCRUB_COLOR = (162, 174, 102)           # #A2AE66 灌木
SCRUB_DOT = (128, 140, 76)

BARE_ROCK_COLOR = (206, 196, 172)       # #CEC4AC
WETLAND_COLOR = (138, 166, 116)         # #8AA674


# ============================================================
# 建筑（保留常量以兼容旧 import；瓦片上不再绘制）
# ============================================================

BUILDING_COLOR = (213, 204, 178)
BUILDING_OUTLINE = (119, 108, 88)

HISTORIC_BUILDING_COLOR = (197, 179, 143)
HISTORIC_BUILDING_OUTLINE = (102, 87, 67)

TEMPLE_COLOR = (201, 184, 150)
TEMPLE_OUTLINE = (104, 82, 58)


# ============================================================
# 城墙：纯黑，粗
# ============================================================

WALL_COLOR = (0, 0, 0)                  # 纯黑
WALL_LIGHT = (0, 0, 0)                  # 保留（不再使用）


# ============================================================
# 道路：单色，无描边。官道最深，巷最浅。
# ============================================================

PRIMARY_COLOR = (98, 68, 34)            # #624422 官道（最深）
SECONDARY_COLOR = (120, 86, 46)         # #78562E
TERTIARY_COLOR = (140, 104, 60)         # #8C683C
RESIDENTIAL_COLOR = (162, 128, 80)      # #A28050 坊巷 / 小道（最浅）
OTHER_ROAD_COLOR = (176, 144, 96)       # #B09060

# 旧 casing 变量：保留以兼容，不再使用
PRIMARY_FILL = PRIMARY_COLOR
SECONDARY_FILL = SECONDARY_COLOR
TERTIARY_FILL = TERTIARY_COLOR
RESIDENTIAL_FILL = RESIDENTIAL_COLOR
OTHER_ROAD_FILL = OTHER_ROAD_COLOR


# ============================================================
# POI
# ============================================================

POINT_COLOR = (91, 68, 48)


# ============================================================
# 真实世界尺寸（米）——按 zoom 换算成像素
#
# 这样做的好处：任何 zoom 下宽度都物理一致，z17/z18 直接正确，
# 不需要为每级 zoom 维护一张宽度表。
# ============================================================

REF_LAT = 32.4                          # 换算参考纬度（地图范围很小，误差可忽略）

# 道路真实宽度（米）：官道 / 次街 / 巷
ROAD_WIDTH_M = {
    "primary": 11.0,
    "secondary": 8.0,
    "tertiary": 6.0,
    "residential": 3.5,
    "living_street": 3.5,
    "unclassified": 3.5,
    "road": 3.5,
}

# 木刻地图习惯把路画粗一点，便于辨认
ROAD_WIDTH_SCALE = 1.35

# 水道真实宽度（米）
WATERWAY_WIDTH_M = {
    "river": 26.0,
    "canal": 16.0,
    "dock": 12.0,
    "stream": 5.0,
    "ditch": 2.5,
    "drain": 2.5,
}
WATERWAY_DEFAULT_M = 3.0

# 城墙真实厚度（米）——故意比实际加粗，保证低 zoom 也看得清
WALL_WIDTH_M = 26.0

# 水岸线（米）
WATER_EDGE_M = 1.5

# 像素宽度的下限 / 上限
MIN_LINE_PX = 1
MAX_LINE_PX = 64


# ============================================================
# 宣纸纹理（paper texture）
#
# 基于「全局像素坐标」计算 → 跨瓦片连续，不会出现接缝。
# ============================================================

# ---- 细颗粒 ----
# 逐像素随机噪声 PNG 完全压不动（单张 55–88KB），已停用。
# 需要颗粒感时在前端叠一张可平铺的小图（零瓦片成本）。
PAPER_GRAIN_STRENGTH = 0.0

# 低频纸浆不匀
PAPER_MOTTLE_STRENGTH = 6.0

# 成品量化步长：所有瓦片用同一张量化表 → 不会产生接缝，
# 但把 PNG 体积从 14.9KB 降到 8.9KB。
QUANTIZE_STEP = 4

# ---- 色差（柔和的深浅 / 冷暖区块）----
PATCH_STRENGTH = 0.070                  # 明暗起伏
PATCH_HUE = 0.040                       # 冷暖偏色（旧纸泛黄/发青）

# ---- 污渍 / 霉斑 ----
STAIN_STRENGTH = 0.145                  # 陈年水渍（只压暗）
FOXING_COUNT = 0.00020                  # 霉斑密度（每像素）
FOXING_STRENGTH = 0.240                 # 霉斑压暗强度


# ============================================================
# 全局 Zoom
# ============================================================

CURRENT_ZOOM = 10
