# Web 管理后台 / 值班工作台

## 本地运行

```bash
cd frontend_web
npm install
npm run dev
```

默认 API：`http://127.0.0.1:8000/api`。如后端地址不同，新建 `.env.local`：

```env
VITE_API_BASE_URL=https://your-domain.example/api
```

## 值班电脑绑定

值班电脑浏览器需要提前写入与后端 `DUTY_TERMINAL_TOKEN` 一致的永久 Token。只在值班工位执行一次：

```js
localStorage.setItem('duxue_duty_terminal_token', '这里填写值班终端Token')
```

之后学生从该浏览器登录时，每次请求都会自动携带 `X-Duty-Terminal-Token`，后端将其识别为 `duty` 模式并进入值班工作台。不要把真实 Token 写入仓库或提交到 Git。

## 页面

- `/admin/bookings`：预约审批、超级预约、清扫核验、用户冻结/解冻
- `/admin/schedule`：每周值班排班下发
- `/admin/export`：预约数据 Excel 导出
- `/admin/appeals`：学生解封申诉审核
- `/duty/rooms`：实时房间雷达与违规标记
- `/duty/handover`：值班签到、交接班日志
- `/duty/print`：本周值班表、今日预约清单、管理周报打印
