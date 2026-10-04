# v0.4.0 部署说明

本版本改为纯预约签到：签到窗口为预约开始时间前 1 小时至开始后 1 小时。

升级现有服务器时请保留现有 `backend_fastapi/.env`、`backend_fastapi/duxue_appointment.db` 和 `backend_fastapi/uploads/`，不要用源码包覆盖运行数据。

升级后应删除旧文件/目录：

- `backend_fastapi/api/door_proxy.py`
- `backend_fastapi/ok.py`（若仍是之前的旧测试脚本）
- `frontend_miniapp/pages/door_access/`

新的学生签到接口为：`POST /api/checkin/{booking_id}`。
