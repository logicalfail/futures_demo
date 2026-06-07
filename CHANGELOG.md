# 开发进展

## 2026-06-07

### 数据层修复

- **时间戳 Bug 修复**：`pd.Timestamp.timestamp()` 将 naive datetime 当作 UTC 处理，导致所有 K 线时间偏移 +8h。改为 `dt.to_pydatetime().timestamp()`，Python 正确识别为本地时间（东八区）。数据已全量重刷。
- **交易时段检查**：在 `fetcher.py` 中统一实现 `is_trading_time()`，支持 `force=True` 参数绕过检查（手动刷新/数据修复用）。`server/data_service.py` 中的重复实现改为委托调用。
- **配置路径修复**：`StorageConfig` 路径解析从配置文件所在目录改为项目根目录，确保跨模块路径一致。

### API v1（外部策略模块接口）

- 新增 `server/routers/v1.py`：`/api/v1/bars/{symbol}` 支持多周期聚合（1m/5m/15m/1h/1d）和三模式数据源（auto/db/live）。
- 新增 `GET /api/v1/quotes`、`/api/v1/quotes/{symbol}`、`/api/v1/symbols`、`/api/v1/symbols/{code}` 端点。
- 新增 `server/aggregation.py`：内存中实时聚合 K 线，不落库。
- 在 `server/app.py` 中注册 v1 路由。

### 前端增强

- **时间范围选择器**：预设按钮（1日/3日/1周/1月）+ 自定义 datetime-local 范围输入。
- **多周期 K 线**：根据选择的时间范围自动切换聚合周期（1m/5m/15m/1h），K 线图顶部显示周期标记。
- **K 线图增强**：跨交易日日期标签、交易时段间隔虚线标记、鼠标滚轮缩放 + 拖拽平移、成交量柱状图优化、tooltip 显示持仓量。
- **新增 API 封装**：`getBarsV1()` 调用 v1 API 带时间范围和周期参数。
- 新增 `Period`、`TimeRangePreset` 等 TypeScript 类型。

### 文档与工具

- **AGENTS.md**：项目指南，包含架构、命令速查、关键陷阱（时间戳、PYTHONPATH、AKShare 限流等）。
- **docs/API.md**：完整 REST + WebSocket API 文档，含 curl/Python/JavaScript 调用示例。
- **docs/KNOWLEDGE.md**：中国期货市场知识（交易时段、集合竞价、数据源说明、时间戳规范）。
- **docs/architecture.md**：系统架构设计文档。
- **_refresh_data.py**：全量数据重刷脚本（清库 → 重新拉取 → 验证）。

### 启动脚本

- **start.bat 后台模式**：`start.bat --bg` 使用 `start /B` 后台启动，日志重定向到 `server.log`。
- **start_bg.bat**：专用后台启动脚本，自动杀掉同端口旧进程、构建前端、启动服务、打开浏览器。
- **start.ps1 增强**：读取 `server_config.yaml` 的端口/地址配置，支持 `-PortOverride` 和 `-HostOverride` 参数，新增 `devbg` 后台模式。
- **start.bat 增强**：从 `server_config.yaml` 读取配置，支持 CLI 参数覆盖端口和地址。

### 提交记录

```
304ec51 chore: update data snapshot - refreshed futures 1m bar data
075f3c9 fix: start_bg.bat - escape parens in echo, replace timeout with ping
f908648 fix: start_bg.bat log path display - remove stray %% prefix
4fa0808 feat: add start_bg.bat background launcher with auto-browser
4f59a76 feat: add --bg flag to start.bat for background server
37e8eb2 chore: add AGENTS.md, API/KNOWLEDGE/architecture docs, refresh script
2017d2a feat: enhance frontend with time range selector and multi-period K-line
346eb5f feat: add API v1 with multi-period K-line aggregation
26d1eac fix: correct timestamp handling and trading hours check
```
