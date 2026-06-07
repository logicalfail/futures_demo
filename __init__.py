# futures_demo - 模拟交易员数据获取与存储演示
"""
Akshare-based futures market data pipeline demo.
Provides: fetch → normalize → store → verify

Usage:
    pip install -r requirements.txt
    python -m futures_demo.pipeline fetch     # 单次拉取
    python -m futures_demo.pipeline verify    # 质量检查
    python -m futures_demo.pipeline loop      # 持续采集

See: README.md
"""

__version__ = "0.1.0"
