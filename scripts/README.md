# 脚本说明

- **deploy.sh**：拉取代码、安装依赖、执行 Flask-Migrate 迁移。需在项目根目录执行：`bash scripts/deploy.sh`。重启服务请使用 systemd（见 DEPLOYMENT.md）。

- **simulate_rfid_upload.py**：本机自测用，从项目根目录的 `.env` 读取 `RFID_API_KEY` 和 `RFID_API_BASE_URL`，向 `/api/rfid/ingest` 发送一次数据。在项目根执行：`python3 scripts/simulate_rfid_upload.py [商品id] [规格id]`。

硬件模拟（从设备侧读 Key、模拟硬件上传）已移至 **simulate_hardware/** 目录，见该目录下 README.md。
