# 这个文件告诉 Python，'handlers' 目录是一个包。
# 我们在这里明确地导入所有子模块，以便在 main.py 中可以轻松地
# 使用 'from handlers import start, admin' 这样的语句。

from . import start
from . import admin
from . import favorites
from . import leaderboard
from . import reputation
from . import statistics
from . import utils

# 这是一种可选的、更明确的写法，用于控制 'from handlers import *' 的行为，
# 但对于我们当前的需求来说，上面的导入已经足够。
# __all__ = [
#     "start",
#     "admin",
#     "favorites",
#     "leaderboard",
#     "reputation",
#     "statistics",
#     "utils",
# ]
