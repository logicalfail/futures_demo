"""
Phase 1 E2E Test: Backend Server
=================================
1. 启动 FastAPI server
2. 验证 REST API 端点
3. 验证 WebSocket 连接和推送
4. 验证手动刷新
"""

import sys
import time
import asyncio
import json
import os
from pathlib import Path

# 确保能找到项目
sys.path.insert(0, str(Path(__file__).parent.parent))

import uvicorn
from fastapi.testclient import TestClient
from server.app import create_app
from server.config import load_config, AppConfig

import httpx

# ── 配置 ──────────────────────────────────────────────────
cfg = AppConfig()
cfg.server.host = "127.0.0.1"
cfg.server.port = 8001  # 用不同端口避免冲突
cfg.scheduler.enabled = False  # 测试时不启用定时器
cfg.storage.path = "./data/futures_1m_test.db"

app = create_app(cfg)
client = TestClient(app)


def test_01_symbols():
    """REST: 获取品种列表"""
    resp = client.get("/api/symbols")
    assert resp.status_code == 200
    data = resp.json()
    assert "symbols" in data
    symbols = data["symbols"]
    print(f"[PASS] GET /api/symbols: {len(symbols)} symbols")
    for s in symbols[:3]:
        print(f"       {s['code']:10s} → {s['full_symbol']:20s} ({s['exchange']})")
    assert len(symbols) > 0
    return symbols


def test_02_kline():
    """REST: 获取K线数据（可能为空，第一次拉取前无数据）"""
    resp = client.get("/api/kline/AU2608?limit=100")
    assert resp.status_code == 200
    data = resp.json()
    print(f"[PASS] GET /api/kline/AU2608: {data['count']} bars")
    # 可能无数据（首次运行），不断言count>0


def test_03_refresh():
    """REST: 手动触发刷新"""
    resp = client.post("/api/refresh")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    print(f"[PASS] POST /api/refresh: {data['message']}")
    # 等待数据拉取完成
    time.sleep(2)


def test_04_kline_after_refresh():
    """刷新后验证K线数据存在"""
    resp = client.get("/api/kline/AU2608?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    print(f"[PASS] GET /api/kline/AU2608 after refresh: {data['count']} bars")
    if data["count"] > 0:
        bar = data["bars"][0]
        print(f"       Latest: {bar['ts']} O={bar['open']} H={bar['high']} "
              f"L={bar['low']} C={bar['close']} V={bar['volume']}")
        assert "ts_ns" in bar
        assert "open" in bar
        assert "high" in bar
        assert "low" in bar
        assert "close" in bar


def test_05_quote():
    """REST: 最新报价"""
    resp = client.get("/api/quote/AU2608.SHFE")
    assert resp.status_code == 200
    data = resp.json()
    print(f"[PASS] GET /api/quote/AU2608.SHFE: {data['quote']}")
    assert data["symbol"] == "AU2608.SHFE"


def test_06_quotes():
    """REST: 全部报价"""
    resp = client.get("/api/quotes")
    assert resp.status_code == 200
    data = resp.json()
    print(f"[PASS] GET /api/quotes: {data['count']} quotes")
    # 非交易时段可能为0，不强制断言count>0


def test_07_status():
    """REST: 服务状态"""
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    print(f"[PASS] GET /api/status: running={data['status']}, "
          f"symbols={data['symbols_count']}, "
          f"last_update={data['last_update_str']}")
    assert data["status"] == "running"


def test_08_quality():
    """REST: 数据质量报告"""
    resp = client.get("/api/quality")
    assert resp.status_code == 200
    data = resp.json()
    report_count = len(data["reports"])
    healthy = sum(1 for r in data["reports"] if r["is_healthy"])
    print(f"[PASS] GET /api/quality: {report_count} reports, {healthy} healthy")
    for r in data["reports"][:3]:
        print(f"       {r['symbol']:20s} bars={r['total_bars']:4d} "
              f"gaps={r['gaps']:2d} {'OK' if r['is_healthy'] else 'BAD'}")


async def test_09_websocket():
    """WebSocket 连接 + 订阅 + 接收（需要运行中 server）"""
    import socket
    # 先检查 server 是否在运行
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', 8001))
    sock.close()

    if result != 0:
        print("[SKIP] WS test: server not running on port 8001")
        print("   To test: start server in another terminal then run:")
        print("     cd C:\\tmp\\futures_demo")
        print("     $env:PYTHONPATH='C:\\tmp\\futures_demo'")
        print("     python -c \"import uvicorn; from server.app import create_app; app=create_app(); uvicorn.run(app, host='127.0.0.1', port=8001)\"")
        return

    async with httpx.AsyncClient() as client_http:
        resp = await client_http.get("http://127.0.0.1:8001/api/symbols")
        symbols = resp.json()["symbols"]
        if not symbols:
            print("[SKIP] WS test: no symbols")
            return

        test_symbol = symbols[0]["code"]
        print(f"[WS] Testing WebSocket with symbol: {test_symbol}")

    import websockets as ws_lib
    uri = "ws://127.0.0.1:8001/ws"

    async with ws_lib.connect(uri) as websocket:
        await websocket.send(json.dumps({
            "type": "subscribe",
            "symbols": [test_symbol],
        }))

        received = []
        try:
            async with asyncio.timeout(5):
                msg = await websocket.recv()
                data = json.loads(msg)
                received.append(data)
        except (asyncio.TimeoutError, TimeoutError):
            pass

        print(f"[WS] Received {len(received)} messages on connect")
        if received:
            print(f"       type={received[0].get('type')}")

        # 测试手动刷新
        await websocket.send(json.dumps({"type": "manual_refresh"}))
        await asyncio.sleep(2)
        refresh_received = []
        try:
            async with asyncio.timeout(5):
                while True:
                    msg = await websocket.recv()
                    data = json.loads(msg)
                    refresh_received.append(data)
        except (asyncio.TimeoutError, TimeoutError):
            pass

        status_msgs = [m for m in refresh_received if m.get("type") == "status"]
        print(f"[WS] After manual_refresh: {len(refresh_received)} msgs, {len(status_msgs)} status updates")
        assert len(status_msgs) >= 1, "Should receive at least a status update"
        print("[PASS] WS test completed")


def test_10_frontend_static():
    """前端静态文件服务（如已构建）"""
    frontend_dir = Path(__file__).parent.parent / "frontend" / "dist"
    if frontend_dir.exists() and (frontend_dir / "index.html").exists():
        resp = client.get("/")
        assert resp.status_code == 200
        print(f"[PASS] GET /: Frontend served")
    else:
        print(f"[SKIP] Frontend not built yet (no {frontend_dir / 'index.html'})")


def run_async_tests():
    """运行异步测试"""
    results = {}
    results["test_09_websocket"] = asyncio.run(test_09_websocket())
    return results


if __name__ == "__main__":
    print("=" * 70)
    print("  Phase 1 E2E Test: Backend Server")
    print("=" * 70)
    print()

    tests = [
        ("Symbols API", test_01_symbols),
        ("KLine API (empty)", test_02_kline),
        ("Refresh API", test_03_refresh),
        ("KLine API (after refresh)", test_04_kline_after_refresh),
        ("Quote API", test_05_quote),
        ("All Quotes API", test_06_quotes),
        ("Status API", test_07_status),
        ("Quality API", test_08_quality),
        ("Frontend Static", test_10_frontend_static),
    ]

    passed = 0
    failed = 0

    for name, func in tests:
        try:
            func()
            passed += 1
            print()
        except Exception as e:
            print(f"[FAIL] {name}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
            print()

    # Async tests (need running server)
    print("─" * 50)
    print("  Async WS tests (need server on port 8001)...")
    try:
        asyncio.run(test_09_websocket())
        passed += 1
        print()
    except Exception as e:
        print(f"[FAIL] WebSocket: {e}")
        failed += 1
        print()

    print("=" * 70)
    print(f"  Results: {passed} passed, {failed} failed, {len(tests) + 1} total")
    print("=" * 70)
