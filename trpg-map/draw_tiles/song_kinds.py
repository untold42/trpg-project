# -*- coding: utf-8 -*-
"""
song_kinds.py
=============
南宋基础设施 / 场所词表（v1）。

每个 kind:
  group : 功能大类（娱乐/市井百业/行旅/…）
  icon  : 前端图标键（public/mapicons/<键>.png，美术自备；None=暂无图标）
  zone  : 布点倾向
             core     → 城中心繁华处
             water    → 靠水（河/湖/运河）
             general  → 各处皆可
             edge     → 城郊/乡野
  note  : 备注

参考：宋及前代笔记（东京梦华录、梦粱录、武林旧事等）中的城市功能类别，
按“游戏可布点”的设施口径整理。
"""

KINDS = {

    # ---------- 风月 / 声色 ----------
    "青楼":   dict(group="风月", icon="qinglou",  zone="core",  note="以色艺为主的妓馆（夜夜笙歌处）"),
    "教坊":   dict(group="风月", icon="jiaofang", zone="core",  note="官/私乐舞教习之所，习曲舞、应宴演"),
    "画舫":   dict(group="风月", icon="huafang",  zone="water", note="水上歌舫/伎船，泊于河湖之间"),
    "瓦舍":   dict(group="百戏娱乐", icon="theater", zone="core",  note="宋时大型游艺场，勾栏居其中"),
    "勾栏":   dict(group="百戏娱乐", icon="theater", zone="core",  note="瓦舍中的戏棚，杂剧/傀儡/说唱"),
    "戏台":   dict(group="百戏娱乐", icon="stage",   zone="general", note="露台/乐棚，社戏庙会演出"),
    "书场":   dict(group="百戏娱乐", icon="story",   zone="core",  note="说书/评话/诸宫调场子"),
    "相扑棚": dict(group="百戏娱乐", icon="arena",   zone="general", note="相扑、角抵表演处"),
    "棋馆":   dict(group="百戏娱乐", icon="go",      zone="general", note="弈棋/博戏清谈之所"),
    "演武场": dict(group="军武", icon="arena",   zone="general", note="教习弓马武艺、比试之处"),
    "武馆":   dict(group="军武", icon="martial", zone="core",  note="拳脚器械教习之所"),

    # ---------- 市井百业（商）----------
    "钱铺":   dict(group="金融", icon="money",   zone="core",  note="兑换钱钞/金银"),
    "金银铺": dict(group="金融", icon="money",   zone="core",  note="打造买卖金银首饰"),
    "当铺":   dict(group="金融", icon="pawn",    zone="core",  note="质库/解库，抵押借贷"),
    "赌坊":   dict(group="市井娱乐", icon="gamble", zone="core",  note="博戏场所（宋代禁赌，多为暗坊）"),
    "镖行":   dict(group="行旅", icon="post",    zone="general", note="护货保镖（宋代作“标行/脚店”近似）"),
    "市集":   dict(group="商市", icon="market",  zone="core",  note="定期市、庙市"),
    "粮行":   dict(group="商市", icon="grain",   zone="general", note="米粮买卖行"),
    "鱼行":   dict(group="商市", icon="food",    zone="water",  note="水产市"),
    "绸缎庄": dict(group="商市", icon="textile", zone="core",  note="绸缎布匹"),
    "布行":   dict(group="商市", icon="textile", zone="core",  note="布匹批发零售"),
    "绣坊":   dict(group="百工", icon="textile", zone="core",  note="刺绣作"),
    "织坊":   dict(group="百工", icon="textile", zone="general", note="机房，织造"),
    "染坊":   dict(group="百工", icon="dye",     zone="water",  note="染布，需水"),
    "铁匠铺": dict(group="百工", icon="smith",   zone="general", note="打铁、制农具刀具"),
    "铜匠铺": dict(group="百工", icon="smith",   zone="general", note="铜器铸造修补"),
    "木匠行": dict(group="百工", icon="carpenter", zone="general", note="造屋制器"),
    "车马行": dict(group="行旅", icon="stable",  zone="edge",  note="车马租赁/歇脚"),
    "马厩":   dict(group="行旅", icon="stable",  zone="general", note="蓄养马骡"),
    "磨坊":   dict(group="百工", icon="mill",    zone="general", note="磨面榨油等"),
    "油坊":   dict(group="百工", icon="mill",    zone="general", note="榨油"),
    "豆腐坊": dict(group="百工", icon="mill",    zone="general", note="做豆腐"),
    "酱园":   dict(group="百工", icon="food",    zone="general", note="酱醋作坊"),
    "酒坊":   dict(group="饮食", icon="wine",    zone="general", note="酿酒发售"),
    "香烛铺": dict(group="礼用", icon="incense", zone="general", note="香烛纸马"),
    "棺材铺": dict(group="礼用", icon="coffin",  zone="edge",  note="寿材，多居城外"),
    "纸扎铺": dict(group="礼用", icon="coffin",  zone="edge",  note="纸人纸马冥器"),

    # ---------- 行旅 / 交通 ----------
    "客栈":   dict(group="行旅", icon="inn",     zone="general", note="客舍，可住店打尖"),
    "邸店":   dict(group="行旅", icon="inn",     zone="general", note="兼存货、堆货之客店"),
    "驿站":   dict(group="行旅", icon="post",    zone="edge",  note="官驿，传信换马"),
    "递铺":   dict(group="行旅", icon="post",    zone="edge",  note="急脚递/步递铺"),
    "码头":   dict(group="行旅", icon="ferry",   zone="water", note="装卸客货"),
    "渡口":   dict(group="行旅", icon="ferry",   zone="water", note="摆渡过河"),
    "浮桥":   dict(group="行旅", icon="bridge",  zone="water", note="舟桥"),
    "桥":     dict(group="行旅", icon="bridge",  zone="general", note="石桥/木桥"),
    "船行":   dict(group="行旅", icon="boat",    zone="water", note="租船/客货船行"),

    # ---------- 官署 / 城防 ----------
    "州衙":   dict(group="官署", icon="office", zone="core", note="州郡治所"),
    "县衙":   dict(group="官署", icon="office", zone="core", note="县治"),
    "巡检司": dict(group="官署", icon="office", zone="general", note="缉捕治安"),
    "牢狱":   dict(group="官署", icon="office", zone="general", note="监牢"),
    "粮仓":   dict(group="官署", icon="granary", zone="general", note="常平仓/义仓"),
    "税场":   dict(group="官署", icon="office",  zone="general", note="商税场务"),
    "城门":   dict(group="城防", icon="gate",   zone="edge", note="城郭门"),
    "城楼":   dict(group="城防", icon="gate",   zone="edge", note="城门上之楼"),
    "钟鼓楼": dict(group="城防", icon="gate",   zone="core", note="报时"),
    "望火楼": dict(group="城防", icon="fire",   zone="general", note="火警瞭望，宋制军中亦备"),
    "更房":   dict(group="城防", icon="fire",   zone="general", note="夜巡打更"),

    # ---------- 教育 / 医卜 ----------
    "书院":   dict(group="文教", icon="academy", zone="general", note="聚徒讲学"),
    "州学":   dict(group="文教", icon="academy", zone="core", note="州学/府学"),
    "县学":   dict(group="文教", icon="academy", zone="core", note="县学"),
    "蒙馆":   dict(group="文教", icon="academy", zone="general", note="启蒙塾"),
    "书坊":   dict(group="文教", icon="library", zone="general", note="刻书卖书"),
    "藏书楼": dict(group="文教", icon="library", zone="core", note="藏书"),
    "医馆":   dict(group="医药", icon="med",     zone="general", note="坐堂行医"),
    "药铺":   dict(group="医药", icon="med",     zone="general", note="卖药"),
    "惠民药局": dict(group="医药", icon="med",   zone="general", note="官办施药局"),
    "兽医铺": dict(group="医药", icon="vet",     zone="general", note="医牛马"),
    "算命摊": dict(group="百戏", icon="fortune", zone="core", note="卜卦看相"),

    # ---------- 信仰 / 礼 ----------
    "寺":     dict(group="信仰", icon="temple", zone="general", note="佛寺"),
    "观":     dict(group="信仰", icon="temple", zone="general", note="道观"),
    "祠":     dict(group="信仰", icon="shrine", zone="general", note="民间祠庙/名宦祠"),
    "土地庙": dict(group="信仰", icon="shrine", zone="general", note="社庙"),
    "城隍庙": dict(group="信仰", icon="shrine", zone="general", note="城隍"),
    "义冢":   dict(group="信仰", icon="grave",  zone="edge", note="乱葬/义葬地"),
    "坟地":   dict(group="信仰", icon="grave",  zone="edge", note="墓园"),

    # ---------- 门派 / 驻地 ----------
    "宫":     dict(group="门派", icon="palace",  zone="general", note="宫观/门派驻地（如洞庭锦香宫）"),
    "山庄":   dict(group="门派", icon="palace",  zone="general", note="山庄/别业"),

    # ---------- 山水 / 地标 ----------
    "湖":     dict(group="山水", icon="water",   zone="water", note="湖泊"),
    "洲":     dict(group="山水", icon="islet",   zone="water", note="河洲"),
    "山":     dict(group="山水", icon="mountain",zone="edge", note="山丘"),
    "林":     dict(group="山水", icon="forest",  zone="edge", note="林地"),
    "园":     dict(group="游乐", icon="garden",  zone="general", note="私家园林/花园"),
    "园苑":   dict(group="游乐", icon="garden",  zone="general", note="苑囿/大园林"),
    "高台":   dict(group="地标", icon="sight",   zone="general", note="台榭楼观"),
    "酒楼":   dict(group="饮食", icon="tavern",  zone="core", note="正店酒楼"),
    "酒肆":   dict(group="饮食", icon="tavern",  zone="core", note="小店沽酒"),
    "茶坊":   dict(group="饮食", icon="tea",     zone="general", note="茶馆，宋称茶坊/茶肆"),
    "食铺":   dict(group="饮食", icon="food",    zone="general", note="面食店/小店"),
    "饼铺":   dict(group="饮食", icon="food",    zone="general", note="胡饼/蒸饼等"),
}
