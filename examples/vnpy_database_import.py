"""futures_demo/examples/vnpy_database_import.py
将 akshare 数据导入 vnpy 数据库的完整示例

前提：
    1. 已安装 vnpy：pip install vnpy
    2. 已运行 python demo.py 采集过数据
    3. 在 vnpy 环境中运行此脚本
"""

import sys
from pathlib import Path

# 加入 futures_demo 路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import akshare as ak
from loguru import logger

from futures_demo.fetcher import fetch_minute_bars
from futures_demo.vnpy_adapter import to_vnpy_bar, bars_to_vnpy_csv


def import_to_vnpy_database():
    """vnpy 数据库导入流程"""
    # 第一步：用 akshare 获取数据
    bars = fetch_minute_bars("RB2410", lookback_days=5)
    print(f"Fetched {len(bars)} bars for RB2410")

    # 第二步：导出为 vnpy CSV
    csv_path = Path(__file__).parent / "data" / "RB2410_1m.csv"
    csv_path.parent.mkdir(exist_ok=True)
    bars_to_vnpy_csv(bars, str(csv_path))

    # 第三步：导入 vnpy 数据库管理器
    try:
        from vnpy.trader.database import get_database_manager
        db = get_database_manager()

        vnpy_bars = []
        for b in bars:
            vb = to_vnpy_bar(b)
            if vb:
                vnpy_bars.append(vb)

        if vnpy_bars:
            db.save_bar_data(vnpy_bars)
            print(f"✅ Imported {len(vnpy_bars)} bars to vnpy database")
        else:
            print("⚠️  No valid vnpy bars to import")

    except ImportError:
        print("⚠️  vnpy not installed, saving CSV only")
        print(f"   CSV saved to: {csv_path}")
        print("   在 vnpy 中通过 DataManager → 本地CSV导入")


def ctp_subscription_example():
    """
    vnpy CTP 行情订阅参考
    实际 CTPSubscriber 示例参见 vnpy_ctp 示例
    """
    print("""
    ═══════════════════════════════════════════════════
    vnpy CTP 行情订阅（需要 CTP 账号）

    from vnpy_ctp import CtpGateway
    from vnpy.trader.constant import Exchange

    gateway = CtpGateway("CTP")
    gateway.connect({
        "用户名": "YOUR_ACCOUNT",
        "密码": "YOUR_PASSWORD",
        "经纪商代码": "YOUR_BROKER",
        "交易服务器": "tcp://YOUR_TRADING_ADDRESS",
        "行情服务器": "tcp://YOUR_MD_ADDRESS",
        "产品名称": "YOUR_APP_NAME",
        "授权编码": "YOUR_AUTH_CODE",
        "产品信息": "",
    })

    # 订阅合约
    from vnpy.trader.constant import Exchange
    contract = ("rb2410", Exchange.SHFE)
    gateway.subscribe(contract)

    # 在 on_bar 回调中接收分钟K线
    # 在 on_tick 回调中接收 Tick
    ═══════════════════════════════════════════════════
    """)


if __name__ == "__main__":
    print("=" * 60)
    print("  vnpy 数据接入示例")
    print("=" * 60)

    import_to_vnpy_database()
    ctp_subscription_example()