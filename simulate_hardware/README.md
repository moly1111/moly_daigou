# 硬件模拟（RFID 入库）

本目录用于模拟 RFID 硬件向服务器 `/api/rfid/ingest` 上传入库数据。硬件无法读取服务器 `.env`，因此 API Key 存放在**设备侧**（本模拟用 `device_config.txt` 表示）。

## 文件

| 文件 | 说明 |
|------|------|
| **device_config.example.txt** | 配置示例。复制为 `device_config.txt` 后填写。 |
| **device_config.txt** | 设备本地配置（不提交 Git）。第 1 行：API Key；第 2 行：服务器地址。 |
| **upload.py** | 模拟上传脚本：读取本目录 `device_config.txt`，向服务器发送一次入库请求。 |

## 配置

1. 复制配置示例并填写：
   ```bash
   cp device_config.example.txt device_config.txt
   ```
2. 编辑 `device_config.txt`：
   - **第 1 行**：与服务器 `.env` 中 `RFID_API_KEY` 相同的密钥
   - **第 2 行**：服务器地址（如 `http://127.0.0.1:5000`）

## 用法

```bash
python3 simulate_hardware/upload.py [商品id] [规格编号] [数量]
```

- **第二个参数（规格）** 默认为**逻辑规格编号**（该商品下第 1、2、3… 个规格）：
  - `2 1 3` → 商品 2 的规格 1，入库 3 件
  - `1 2 5` → 商品 1 的规格 2，入库 5 件
- 使用 **`G` 前缀** 表示全局规格 id：`1 G5 3` → 商品 1 的全局规格 id=5，入库 3 件。
- **数量** 不传时默认为 1。

示例（在项目根目录执行）：

```bash
python3 simulate_hardware/upload.py 2 1 3
python3 simulate_hardware/upload.py 1 G5 1
```

或先进入本目录再执行：

```bash
cd simulate_hardware
python3 upload.py 2 1 3
```

## 真实硬件

API Key 存放在设备 flash / 配置文件 / 网关环境变量中，请求时在 Header `X-API-Key` 中带上即可。数据格式为：`商品id;规格编号;数量`，其中规格编号可为数字（逻辑编号，API 内为 `L:数字`）或全局规格 id。
