# 白云机场航班延误监控

广州白云国际机场（CAN）国内航班延误监控系统第一版。

- 24小时持续监控，默认每5分钟轮询
- 仅关注 CAN 国内航班
- 严重延误阈值默认 >= 120 分钟
- 同一航班每天只触发一次严重延误告警
- 每日运行简报
- Mock 数据源：无需 API Key 即可测试
- 可插拔真实航班数据 Provider
- 邮件告警、企业微信机器人接口
- FastAPI 健康检查、状态和航班接口
- SQLite 持久化
- Docker Compose 一键运行

> Mock Provider 仅用于开发/测试，不代表真实航班状态。正式24小时运行前，需要接入有授权的实时航班数据服务。

## 启动
```bash
cp .env.example .env
docker compose up -d --build
```

健康检查：`http://服务器IP:8000/health`
