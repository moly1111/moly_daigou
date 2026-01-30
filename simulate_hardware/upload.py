#!/usr/bin/env python3
"""
模拟硬件上传：从本目录 device_config.txt 读取 API Key 和服务器地址，
向 /api/rfid/ingest 发送【商品id;规格id;数量】格式数据。

配置：在本目录（simulate_hardware/）下创建 device_config.txt：
  第1行：API Key（与服务器 .env 的 RFID_API_KEY 一致）
  第2行：服务器地址（可选），如 http://192.168.1.100:5000

用法：
  python3 upload.py [商品id] [规格编号] [数量]
  第二个参数默认为「逻辑规格编号」（该商品下第 1、2、3… 个规格），如 2 1 3 = 商品2的规格1 入库3。
  传 G 前缀表示全局规格 id，如 1 G5 3 = 商品1 的全局规格 id=5 入库3。
  不传数量时默认 1。
"""
import json
import os
import sys
import urllib.error
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "device_config.txt")


def load_device_config():
    """从设备本地配置文件读取 API Key 和服务器地址（模拟硬件从 flash/配置文件 读取）"""
    if not os.path.isfile(CONFIG_FILE):
        print(f"错误：未找到设备配置文件 {CONFIG_FILE}")
        print("请复制 device_config.example.txt 为 device_config.txt，填入 API Key 和服务器地址")
        sys.exit(1)
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f.readlines() if ln.strip() and not ln.strip().startswith("#")]
    api_key = (lines[0] if lines else "").strip()
    base_url = (lines[1] if len(lines) > 1 else "http://127.0.0.1:5000").strip().rstrip("/")
    if not api_key:
        print("错误：device_config.txt 第一行须为 API Key")
        sys.exit(1)
    return api_key, base_url


def main():
    product_id = sys.argv[1] if len(sys.argv) > 1 else "1"
    variant_arg = sys.argv[2] if len(sys.argv) > 2 else "1"
    quantity = sys.argv[3] if len(sys.argv) > 3 else "1"
    # 默认按逻辑规格编号（该商品下 1、2、3…）；G5 表示全局规格 id=5
    if variant_arg.upper().startswith("G") and len(variant_arg) > 1 and variant_arg[1:].isdigit():
        variant_part = variant_arg[1:]
    elif variant_arg.isdigit():
        variant_part = f"L:{variant_arg}"
    elif variant_arg.upper().startswith("L") and len(variant_arg) > 1 and variant_arg[1:].isdigit():
        variant_part = f"L:{variant_arg[1:]}"
    else:
        variant_part = variant_arg

    api_key, base_url = load_device_config()

    payload = f"{product_id};{variant_part};{quantity}"
    url = f"{base_url}/api/rfid/ingest"
    data = json.dumps({"data": payload}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
        },
        method="POST",
    )

    print("[模拟硬件] 从 device_config.txt 读取 Key 与服务器地址")
    print(f"请求: POST {url}")
    print(f"数据: {payload} (商品id={product_id}, 规格={variant_arg}, 数量={quantity})")
    print()

    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            print(f"状态码: {r.status}")
            body = json.loads(r.read().decode("utf-8"))
            for k, v in body.items():
                print(f"  {k}: {v}")
    except urllib.error.HTTPError as e:
        print(f"状态码: {e.code}")
        try:
            body = json.loads(e.read().decode("utf-8"))
            for k, v in body.items():
                print(f"  {k}: {v}")
        except Exception:
            print(e.read().decode("utf-8"))
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"连接失败: {e.reason}")
        print("请检查 device_config.txt 中服务器地址是否正确、服务是否已启动")
        sys.exit(1)
    except Exception as e:
        print(f"请求异常: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
