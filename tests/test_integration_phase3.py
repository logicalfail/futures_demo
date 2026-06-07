"""
Phase 3 Integration & E2E Test: Frontend + Backend
===================================================
1. 前端静态文件服务 (index.html, JS, CSS)
2. SPA 回退路由 / API 前缀保护
3. WebSocket 订阅全链路
4. 多品种订阅 / 取消订阅
5. 手动刷新触发
6. REST API 全覆盖
"""

import sys
import json
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from server.app import create_app
from server.config import AppConfig

# ── 配置 ──────────────────────────────────────────────────
cfg = AppConfig()
cfg.server.host = "127.0.0.1"
cfg.server.port = 8002
cfg.scheduler.enabled = False
cfg.storage.path = "./data/futures_1m_test.db"

app = create_app(cfg)
client = TestClient(app)

# ── 工具函数 ──────────────────────────────────────────────

import threading
import queue


def ws_recv(ws, timeout: float = 3.0):
    """非阻塞 WS receive_text，超时返回 None"""
    q: queue.Queue = queue.Queue()

    def _recv():
        try:
            msg = ws.receive_text()
            q.put(msg)
        except Exception as e:
            q.put(e)

    t = threading.Thread(target=_recv, daemon=True)
    t.start()
    t.join(timeout=timeout)
    if t.is_alive():
        # thread still running = no data yet
        return None
    result = q.get()
    if isinstance(result, Exception):
        raise result
    return result


# ===================== 前端静态文件服务 =====================

def test_01_frontend_index():
    """GET / 返回前端 index.html"""
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text
    assert "root" in html
    assert "zh-CN" in html or "zh" in html
    print(f"[PASS] GET /: {len(html)} bytes")


def test_02_frontend_assets():
    """前端 JS/CSS 资源可访问"""
    resp = client.get("/")
    html = resp.text
    js_assets = re.findall(r'src="(/assets/[^"]+\.js)"', html)
    css_assets = re.findall(r'href="(/assets/[^"]+\.css)"', html)

    for asset in js_assets + css_assets:
        aresp = client.get(asset)
        assert aresp.status_code == 200, f"Asset {asset} returned {aresp.status_code}"
        print(f"     {asset}: {len(aresp.content)} bytes OK")

    print(f"[PASS] Frontend assets: {len(js_assets)} JS + {len(css_assets)} CSS")


def test_03_spa_fallback():
    """未匹配路径回到 index.html"""
    resp = client.get("/some/random/path")
    assert resp.status_code == 200
    assert "root" in resp.text
    print(f"[PASS] SPA fallback: /some/random/path -> index.html")


def test_04_api_prefix_not_fallback():
    """API 前缀不应被 SPA fallback 捕获"""
    resp = client.get("/api/nonexistent")
    data = resp.json()
    assert "error" in data or "detail" in data
    print(f"[PASS] API prefix bypass: /api/nonexistent -> {data}")


# ===================== WebSocket 集成 =====================

def _ensure_data_populated():
    """触发一次数据拉取，确保 WS 测试时有数据可收"""
    resp = client.post("/api/refresh")
    assert resp.status_code == 200
    print("     Data refresh triggered for WS tests")


def test_05_ws_subscribe_receives_kline():
    """WS: 订阅品种后立即收到 kline_update"""
    _ensure_data_populated()
    resp = client.get("/api/symbols")
    symbols = resp.json()["symbols"]
    assert len(symbols) > 0
    test_symbol = symbols[0]["full_symbol"]

    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({
            "type": "subscribe",
            "symbols": [test_symbol],
        }))

        kline_msgs = []
        for _ in range(5):
            raw = ws_recv(ws, timeout=2)
            if raw is None:
                break
            msg = json.loads(raw)
            if msg.get("type") == "kline_update":
                kline_msgs.append(msg)

        assert len(kline_msgs) >= 1, f"Expected kline_update, got {len(kline_msgs)}"
        first = kline_msgs[0]
        assert first["symbol"] == test_symbol
        assert "bars" in first
        assert len(first["bars"]) > 0

        bar = first["bars"][0]
        print(f"[PASS] WS subscribe {test_symbol}: {len(first['bars'])} bars")
        print(f"       Latest: {bar['ts']} O={bar['open']} H={bar['high']} "
              f"L={bar['low']} C={bar['close']} V={bar['volume']}")


def test_06_ws_multiple_symbols():
    """WS: 多品种订阅 / 取消订阅"""
    resp = client.get("/api/symbols")
    symbols = resp.json()["symbols"]
    assert len(symbols) >= 2

    syms = [s["full_symbol"] for s in symbols[:3]]

    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "subscribe", "symbols": syms}))

        received = set()
        for _ in range(10):
            raw = ws_recv(ws, timeout=2)
            if raw is None:
                break
            msg = json.loads(raw)
            if msg.get("type") == "kline_update":
                received.add(msg["symbol"])

        print(f"     Multi-subscribe: received {len(received)}/{len(syms)} symbols")
        assert len(received) > 0

        ws.send_text(json.dumps({"type": "unsubscribe", "symbols": syms}))
        print(f"     Unsubscribed from {syms}")
        print(f"[PASS] WS multiple symbols subscribe/unsubscribe")


def test_07_ws_manual_refresh():
    """WS: 手动刷新不报错"""
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "subscribe", "symbols": ["AU2608.SHFE"]}))
        for _ in range(3):
            if ws_recv(ws, timeout=1) is None:
                break

        # 手动刷新
        ws.send_text(json.dumps({"type": "manual_refresh"}))

        # 等待一段时间收取消息，不强制要求 status（定时器可能未启动）
        got_error = False
        for _ in range(15):
            raw = ws_recv(ws, timeout=3)
            if raw is None:
                continue
            msg = json.loads(raw)
            if msg.get("type") == "error":
                got_error = True
                print(f"     ERROR: {msg.get('message')}")
            elif msg.get("type") == "status":
                print(f"     Status: {msg.get('status')} - {msg.get('message')}")
            elif msg.get("type") == "kline_update":
                print(f"     KLine update: {msg.get('symbol')} ({len(msg.get('bars', []))} bars)")

        assert not got_error, "Should not receive error after manual_refresh"
        print(f"[PASS] WS manual refresh (no errors)")


def test_08_ws_kline_structure():
    """WS: K线数据结构完整"""
    resp = client.get("/api/symbols")
    symbols = resp.json()["symbols"]

    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({
            "type": "subscribe",
            "symbols": [symbols[0]["full_symbol"]],
        }))

        bar = None
        for _ in range(5):
            raw = ws_recv(ws, timeout=2)
            if raw is None:
                break
            msg = json.loads(raw)
            if msg.get("type") == "kline_update" and msg.get("bars"):
                bar = msg["bars"][0]
                break

        assert bar is not None, "No kline bar received"
        required = ["ts_ns", "ts", "open", "high", "low", "close", "volume", "turnover", "source"]
        for field in required:
            assert field in bar, f"Missing field: {field}"
        assert bar["high"] >= bar["low"], f"High {bar['high']} < Low {bar['low']}"
        assert bar["high"] >= bar["close"]
        assert bar["high"] >= bar["open"]
        assert bar["low"] <= bar["close"]
        assert bar["low"] <= bar["open"]

        print(f"[PASS] KLine structure: {bar['ts']} O={bar['open']} H={bar['high']} "
              f"L={bar['low']} C={bar['close']} V={bar['volume']}")


def test_09_ws_unknown_type():
    """WS: 未知消息类型返回 error"""
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "unknown_command"}))
        raw = ws_recv(ws, timeout=2)
        if raw is None:
            print(f"[FAIL] No response for unknown command type (timeout)")
            raise AssertionError("No response for unknown command type")
        msg = json.loads(raw)
        assert msg.get("type") == "error"
        print(f"[PASS] Unknown type -> error: {msg.get('message')}")


def test_10_ws_ping_pong():
    """WS: ping/pong 心跳"""
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "ping"}))
        raw = ws_recv(ws, timeout=2)
        if raw is None:
            print(f"[FAIL] No pong response (timeout)")
            raise AssertionError("No pong response")
        msg = json.loads(raw)
        assert msg.get("type") == "pong"
        print(f"[PASS] Ping -> Pong")


# ===================== REST API =====================

def test_11_rest_api_coverage():
    """REST: 全部可用端点正常返回"""
    # /api/status
    resp = client.get("/api/status")
    assert resp.status_code == 200
    status = resp.json()
    assert status["status"] == "running"
    print(f"     /api/status: {status['status']}, {status['symbols_count']} symbols")

    # /api/quotes
    resp = client.get("/api/quotes")
    assert resp.status_code == 200
    quotes = resp.json()
    print(f"     /api/quotes: {quotes['count']} quotes")

    # /api/quality
    resp = client.get("/api/quality")
    assert resp.status_code == 200

    # /api/kline/{symbol}
    resp = client.get("/api/kline/AU2608.SHFE?limit=50&days_back=3")
    assert resp.status_code == 200

    # /api/quote/{symbol}
    resp = client.get("/api/quote/AU2608.SHFE")
    assert resp.status_code == 200
    assert resp.json()["symbol"] == "AU2608.SHFE"

    # /api/symbols
    resp = client.get("/api/symbols")
    assert resp.status_code == 200

    # /api/refresh (POST)
    resp = client.post("/api/refresh")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    print(f"[PASS] All REST endpoints responding")


# ===================== 主入口 =====================

if __name__ == "__main__":
    print("=" * 70)
    print("  Phase 3 Integration & E2E Test")
    print("=" * 70)
    print()

    tests = [
        ("Frontend: Index", test_01_frontend_index),
        ("Frontend: Assets", test_02_frontend_assets),
        ("SPA Fallback", test_03_spa_fallback),
        ("API Prefix Bypass", test_04_api_prefix_not_fallback),
        ("WS Subscribe & KLine", test_05_ws_subscribe_receives_kline),
        ("WS Multiple Symbols", test_06_ws_multiple_symbols),
        ("WS Manual Refresh", test_07_ws_manual_refresh),
        ("WS KLine Structure", test_08_ws_kline_structure),
        ("WS Unknown Type", test_09_ws_unknown_type),
        ("WS Ping Pong", test_10_ws_ping_pong),
        ("REST API Coverage", test_11_rest_api_coverage),
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

    print("=" * 70)
    print(f"  Results: {passed} passed, {failed} failed, {len(tests)} total")
    print("=" * 70)

    sys.exit(0 if failed == 0 else 1)
