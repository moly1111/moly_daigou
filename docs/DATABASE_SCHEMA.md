# 数据库表结构说明

本文档描述 Moly 代购系统各表及列的含义，以及与新表结构的适配情况。

---

## 1. user（用户表）

| 列名 | 类型 | 含义 |
|------|------|------|
| id | Integer | 主键 |
| email | String(120) | 邮箱，唯一，必填 |
| username | String(50) | 用户名，唯一，可为空 |
| password_hash | String(128) | 密码哈希，必填 |
| notes | Text | 管理员备注 |
| created_at | DateTime | 创建时间 |
| last_login_at | DateTime | 最后登录时间 |
| is_banned | Boolean | 是否封禁 |

---

## 2. address（收货地址表）

| 列名 | 类型 | 含义 |
|------|------|------|
| id | Integer | 主键 |
| user_id | Integer | 外键 → user.id |
| name | String(30) | 收货人姓名 |
| phone | String(20) | 手机号 |
| address_text | String(200) | 详细地址 |
| postal_code | String(10) | 邮编 |
| updated_at | DateTime | 更新时间 |

---

## 3. product（商品表）

| 列名 | 类型 | 含义 |
|------|------|------|
| id | Integer | 主键 |
| title | String(60) | 商品名称 |
| price_rmb | Numeric(10,2) | **兼容字段**：无规格时为商品价；有规格时为各规格最低价（供展示「¥xx 元起」） |
| cost_price_rmb | Numeric(10,2) | **兼容字段**：无规格时为成本；有规格时为各规格最低成本 |
| status | String(10) | 状态：up=上架，down=下架 |
| images | Text | 商品主图 JSON 数组 |
| note | String(200) | 商品备注 |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |
| pinned | Boolean | 是否置顶 |

**说明**：价格与成本现已以 `product_variant` 的 `price`/`cost` 为准。`price_rmb`/`cost_price_rmb` 作为兼容字段，用于无规格商品或展示最低价。

---

## 4. product_variant（商品规格表）★ 新表结构

| 列名 | 类型 | 含义 |
|------|------|------|
| id | Integer | 主键（全局规格 ID） |
| product_id | Integer | 外键 → product.id，级联删除 |
| local_id | Integer | 该商品下的逻辑规格编号：1, 2, 3... |
| name | String(100) | 规格名称（如 30ml、礼盒装） |
| price | Numeric(10,2) | **对外展示价**（直接存储） |
| cost | Numeric(10,2) | **采购/购入价**（直接存储） |
| image | String(512) | 规格图片路径 |
| sort_order | Integer | 排序权重 |
| stock | Integer | 库存数量 |

**唯一约束**：`(product_id, local_id)`

---

## 5. order（订单表）

| 列名 | 类型 | 含义 |
|------|------|------|
| id | Integer | 主键 |
| order_no | String(24) | 订单号，唯一 |
| user_id | Integer | 外键 → user.id |
| status | String(20) | pending/processing/done/canceled |
| amount_items | Numeric(10,2) | 商品金额 |
| amount_shipping | Numeric(10,2) | 运费 |
| amount_due | Numeric(10,2) | 应付总额 |
| amount_paid | Numeric(10,2) | 已付金额 |
| is_paid | Boolean | 是否已付款 |
| created_at | DateTime | 创建时间 |
| paid_at | DateTime | 付款时间 |
| completed_at | DateTime | 完成时间 |
| canceled_at | DateTime | 取消时间 |
| cancel_reason | String(200) | 取消原因 |
| internal_notes | Text | 内部备注 |
| tracking_number | String(100) | 快递单号 |
| shipped_at | DateTime | 发货时间 |

---

## 6. order_item（订单明细表）

| 列名 | 类型 | 含义 |
|------|------|------|
| id | Integer | 主键 |
| order_id | Integer | 外键 → order.id |
| product_id | Integer | 外键 → product.id，可为空（手动创建订单时） |
| variant_id | Integer | 外键 → product_variant.id，可为空 |
| name | String(100) | 商品名称快照 |
| spec_note | String(200) | 规格备注 |
| qty | Integer | 数量 |
| link | String(500) | 商品链接（可选） |
| images | Text | 图片 JSON |
| variant_name | String(100) | 规格名称快照 |
| unit_price | Numeric(10,2) | 单价（下单时快照） |
| unit_cost | Numeric(10,2) | 单位成本（用于利润计算） |

---

## 7. cart_item（购物车表）

| 列名 | 类型 | 含义 |
|------|------|------|
| id | Integer | 主键 |
| user_id | Integer | 外键 → user.id |
| product_id | Integer | 外键 → product.id |
| variant_id | Integer | 外键 → product_variant.id，可为空 |
| qty | Integer | 数量 |
| created_at | DateTime | 加入时间 |
| variant_name | String(100) | 规格名称（展示用） |

---

## 8. payment_attachment（支付凭证表）

| 列名 | 类型 | 含义 |
|------|------|------|
| id | Integer | 主键 |
| order_id | Integer | 外键 → order.id |
| user_note | String(200) | 用户备注 |
| image_urls | Text | 图片 URL JSON 数组 |
| uploaded_at | DateTime | 上传时间 |

---

## 9. admin_user（管理员表）

| 列名 | 类型 | 含义 |
|------|------|------|
| id | Integer | 主键 |
| username | String(80) | 用户名，唯一 |
| password_hash | String(128) | 密码哈希 |
| created_at | DateTime | 创建时间 |

---

## 10. system_settings（系统设置表）

| 列名 | 类型 | 含义 |
|------|------|------|
| id | Integer | 主键 |
| key | String(50) | 配置键，唯一 |
| value | Text | 配置值 |
| updated_at | DateTime | 更新时间 |

---

## 11. email_verification（邮箱验证码表）

| 列名 | 类型 | 含义 |
|------|------|------|
| id | Integer | 主键 |
| email | String(120) | 邮箱 |
| code | String(6) | 验证码 |
| expire_at | DateTime | 过期时间 |
| used | Boolean | 是否已使用 |
| created_at | DateTime | 创建时间 |

---

## 12. version（版本表）

| 列名 | 类型 | 含义 |
|------|------|------|
| id | Integer | 主键 |
| version | String(20) | 版本号，唯一 |
| title | String(200) | 标题 |
| description | Text | 描述 |
| release_date | DateTime | 发布日期 |
| is_current | Boolean | 是否当前版本 |
| created_at | DateTime | 创建时间 |

---

## 13. chat_message（聊天消息表）

| 列名 | 类型 | 含义 |
|------|------|------|
| id | Integer | 主键 |
| user_id | Integer | 外键 → user.id |
| sender | String(10) | user/admin |
| text | Text | 文本内容 |
| image_path | String(512) | 图片路径 |
| file_path | String(512) | 文件路径 |
| file_name | String(255) | 文件名 |
| file_mime | String(100) | 文件 MIME |
| created_at | DateTime | 创建时间 |
| is_read_by_user | Boolean | 用户是否已读 |
| is_read_by_admin | Boolean | 管理员是否已读 |

---

## 新表结构适配检查

| 模块 | 适配情况 |
|------|----------|
| Product.variants_list | ✅ 使用 ProductVariant.price/cost |
| Product.get_min_display_price | ✅ 有规格取 min(price)，无规格取 price_rmb |
| Product.get_variant_price/cost | ✅ 使用 variant.price/cost |
| 购物车/下单 | ✅ 使用 variant.get_display_price()、get_cost() |
| 订单利润统计 | ✅ 使用 OrderItem.unit_price、unit_cost |
| fill_order_items_unit_price | ✅ 从 variant 取 price/cost |
| RFID 入库 API | ✅ 支持 variant_id 与 L:local_id |
| 管理员商品表单 | ✅ 保存 price/cost 到 ProductVariant |
| 仓储可视化 | ✅ 使用 product_variants |
| 订单创建（前台） | ✅ 写入 unit_price、unit_cost |

---

## 已知问题与建议

1. **无规格商品**：已修复。创建/编辑商品时若未添加任何规格，后端会校验并提示「请至少添加一个规格」。
2. **手动创建订单**：admin 手动创建订单时 OrderItem 无 product_id/variant_id，unit_price/unit_cost=0，不参与利润统计，属预期行为。
3. **order_form 商品参考**：添加商品时显示的 price_rmb 为各规格最低价，仅作参考；实际金额由管理员手动填写。

4. **数据库编辑模式**：管理员后台「数据库」页面右上角可输入 `DATABASE_PASSWORD`（配置于 .env），验证通过后进入编辑模式，可双击单元格修改数据。不可编辑：主键(id)、password_hash。
