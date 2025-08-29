# 声望值配置
REP_HUNT_SUCCESS = 2      # 成功 /hunt 一次，自己获得的声望
REP_TRAP_SUCCESS = 1      # 成功 /trap 一次，自己获得的声望
REP_BEING_HUNTED = 10     # 分享被 /hunt，分享者获得的声望
REP_BEING_TRAPPED = -20   # 分享被 /trap，分享者获得的声望

# 狼群地位等级 (声望阈值, 等级名称)
PACK_RANKS = [
    (-float('inf'), "孤狼 (Omega)"),
    (0, "幼狼 (Cub)"),
    (51, "侦察狼 (Scout)"),
    (201, "精英猎手 (Hunter)"),
    (501, "头狼 (Alpha)"),
]

# 猎物列表回调
CALLBACK_LIST_PREFIX = "list_page_"

# 数据库中用于标识反馈类型的字符串
TYPE_HUNT = "hunt"
TYPE_TRAP = "trap"
