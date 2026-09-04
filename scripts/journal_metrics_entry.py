"""PyInstaller 入口（打包用）：以包方式调用 CLI。"""

import sys

from journal_metrics.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
