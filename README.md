# 抓取适配器 (非官方抓取)

本分支新增了基于 HTML 抓取的航班适配器（优先顺序：飞常准 -> 携程 -> 飞猪），用于在没有或不想使用官方 API Key 时作为临时数据源。请注意风险：此方法可能违反目标站点服务条款、易受页面结构/反爬机制影响，且需做好限速与代理策略以降低被封风险。

环境变量（可选）
- SCRAPE_TTL: 缓存 TTL（秒），默认 120
- REQUESTS_PROXY: 可选代理地址（例如 http://user:pwd@host:port）
- SCRAPE_UA_LIST: 自定义 User-Agent 列表，逗号分隔
- SCRAPE_RETRIES: 重试次数，默认 3

如何运行测试（CI 不联网，测试基于静态 HTML 片段）
1. 创建虚拟环境并安装依赖：
   pip install -r requirements.txt
2. 运行测试：
   pytest -q

后续建议：
- 生产环境推荐：代理池、IP 轮换、速率限制、增加官方 API 兜底。
- 定期维护解析规则（页面结构变化时需更新 selectors）。
