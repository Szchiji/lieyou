2025-09-05 18:56:59,527 - __main__ - INFO - 程序开始启动...
2025-09-05 18:56:59,527 - __main__ - INFO - .env 文件已加载 (如果存在)。
2025-09-05 18:56:59,527 - __main__ - INFO - TELEGRAM_BOT_TOKEN 已加载。
2025-09-05 18:56:59,527 - __main__ - INFO - RENDER_EXTERNAL_URL 已加载: https://lieyou.onrender.com
2025-09-05 18:56:59,820 - __main__ - CRITICAL - 模块导入失败: cannot import name 'db_fetchval' from 'database' (/opt/render/project/src/database.py)
Traceback (most recent call last):
  File "/opt/render/project/src/main.py", line 49, in <module>
    from handlers.admin import (
  File "/opt/render/project/src/handlers/admin.py", line 10, in <module>
    from database import (
ImportError: cannot import name 'db_fetchval' from 'database' (/opt/render/project/src/database.py)
==> Application exited early
==> Common ways to troubleshoot your deploy: https://render.com/docs/troubleshooting-deploys
==> Running 'python main.py'
2025-09-05 18:57:07,405 - __main__ - INFO - 程序开始启动...
2025-09-05 18:57:07,405 - __main__ - INFO - .env 文件已加载 (如果存在)。
2025-09-05 18:57:07,405 - __main__ - INFO - TELEGRAM_BOT_TOKEN 已加载。
2025-09-05 18:57:07,405 - __main__ - INFO - RENDER_EXTERNAL_URL 已加载: https://lieyou.onrender.com
2025-09-05 18:57:07,557 - __main__ - CRITICAL - 模块导入失败: cannot import name 'db_fetchval' from 'database' (/opt/render/project/src/database.py)
Traceback (most recent call last):
  File "/opt/render/project/src/main.py", line 49, in <module>
    from handlers.admin import (
  File "/opt/render/project/src/handlers/admin.py", line 10, in <module>
    from database import (
ImportError: cannot import name 'db_fetchval' from 'database' (/opt/render/project/src/database.py)
