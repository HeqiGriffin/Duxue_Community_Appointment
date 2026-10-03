# 笃学书院社区空间预约管理系统

当前工程已包含三部分：

- `backend_fastapi/`：FastAPI 后端，预约 AI 审核、数据库级 30 分钟占房锁、门禁代理、离场 OCR、冻结/申诉、值班与打印接口。
- `frontend_miniapp/`：微信小程序学生端，登录、自然语言预约、签到二维码、离场实时相机、线上申诉。
- `frontend_web/`：Vue 3 Web 管理端与值班工作台，预约审核、超级预约、违规/清扫核验、排班、申诉、Excel 导出、房间雷达、交接班、打印中心。

## 1. 后端

```bash
cd backend_fastapi
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
# 按 .env.example 配置环境变量
uvicorn main:app --host 0.0.0.0 --port 8000
```

健康检查：`GET /health`，当前版本 `0.3.0`。

## 2. Web 管理端

```bash
cd frontend_web
npm install
npm run dev
```

默认访问 `http://127.0.0.1:5173`。生产环境修改 `VITE_API_BASE_URL`。

值班工位必须按 `frontend_web/README_WEB.md` 写入专属终端 Token；普通电脑上的学生账号不会进入值班工作台。

## 3. 微信小程序

使用微信开发者工具导入 `frontend_miniapp/`。本地联调 API 默认写在 `app.js`，真机上线前需改为备案 HTTPS 域名并配置微信业务域名。

## 4. 仍需部署方提供的外部凭据

代码不会内置真实敏感信息。正式上线前需配置：AI API、i大工管理员 Cookie 与动态二维码 URL、可选 OCR 服务、生产 JWT Secret、值班终端 Token。

## 5. 当前技术边界

后端仍按当前接口规则禁止单笔预约跨自然日，因此 23:30–00:00 需要以后统一修改后端时间窗口后再开放。离场“只能实时拍摄”的主要强制点位于微信小程序 `camera.js`；后端同时验证上传来源参数和图片文件，但无法仅凭 JPG 文件证明其物理拍摄时刻。
