# 数据库详细结构（当前实现）

本文档按当前代码实现整理数据库结构，重点覆盖近期新增的：
- 用户多地址与默认地址
- 订单收货地址快照（避免历史订单地址被覆盖）
- 订单项部分发货字段
- 聊天附件私有化访问相关字段

> 说明：项目使用 SQLite，部分新增列通过应用启动时自动补列兼容旧库。

---

## 1. 实体关系总览

- `user` 1:N `address`
- `user` 1:N `order`
- `order` 1:N `order_item`
- `order` 1:N `payment_attachment`
- `product` 1:N `product_variant`
- `product_variant` 1:N `order_item`（可空）
- `product_variant` 1:N `cart_item`（可空）
- `user` 1:N `chat_message`

---

## 2. 表结构明细

## `user`（用户）

| 列名 | 类型 | 约束/默认 | 说明 |
|---|---|---|---|
| id | Integer | PK | 用户主键 |
| email | String(120) | unique, not null | 登录邮箱 |
| username | String(50) | unique, null | 用户名（可选） |
| password_hash | String(128) | not null | 密码哈希 |
| notes | Text | null | 管理员备注 |
| created_at | DateTime | default now | 创建时间 |
| last_login_at | DateTime | null | 最后登录时间 |
| is_banned | Boolean | default false | 封禁状态 |

业务补充：
- 当前实现为**多地址**：`user.addresses`
- 为兼容旧代码仍保留 `user.address` 属性（优先默认地址，否则最新地址）

---

## `address`（收货地址）

| 列名 | 类型 | 约束/默认 | 说明 |
|---|---|---|---|
| id | Integer | PK | 地址主键 |
| user_id | Integer | FK -> user.id, not null | 所属用户 |
| name | String(30) | not null | 收货人 |
| phone | String(20) | not null | 手机号 |
| address_text | String(200) | not null | 详细地址 |
| postal_code | String(10) | null | 邮编 |
| is_default | Boolean | default false | 是否默认地址 |
| updated_at | DateTime | default now, onupdate now | 更新时间 |

---

## `product`（商品）

| 列名 | 类型 | 约束/默认 | 说明 |
|---|---|---|---|
| id | Integer | PK | 商品主键 |
| title | String(60) | not null | 商品名 |
| price_rmb | Numeric(10,2) | not null | 兼容字段：最低展示价 |
| cost_price_rmb | Numeric(10,2) | default 0 | 兼容字段：最低成本 |
| status | String(10) | default 'up' | 上下架状态 |
| images | Text | null | 商品主图 JSON 数组 |
| note | String(200) | null | 备注 |
| created_at | DateTime | default now | 创建时间 |
| updated_at | DateTime | default now/onupdate | 更新时间 |
| pinned | Boolean | default false | 是否置顶 |

---

## `product_variant`（商品规格）

| 列名 | 类型 | 约束/默认 | 说明 |
|---|---|---|---|
| id | Integer | PK | 全局规格 ID |
| product_id | Integer | FK -> product.id, not null | 所属商品 |
| local_id | Integer | not null, default 1 | 商品内逻辑规格编号 |
| name | String(100) | not null | 规格名 |
| price | Numeric(10,2) | not null, default 0 | 展示价 |
| cost | Numeric(10,2) | not null, default 0 | 成本价 |
| image | String(512) | null | 规格图路径 |
| sort_order | Integer | default 0 | 排序 |
| stock | Integer | default 0 | 库存 |

约束：
- Unique(`product_id`, `local_id`)

---

## `order`（订单）

| 列名 | 类型 | 约束/默认 | 说明 |
|---|---|---|---|
| id | Integer | PK | 订单主键 |
| order_no | String(24) | unique, not null | 订单号 |
| user_id | Integer | FK -> user.id, not null | 下单用户 |
| status | String(20) | default 'pending' | 状态（pending/processing/done/canceled） |
| amount_items | Numeric(10,2) | not null | 商品金额 |
| amount_shipping | Numeric(10,2) | not null | 运费 |
| amount_due | Numeric(10,2) | not null | 应付总额 |
| amount_paid | Numeric(10,2) | default 0 | 实收金额 |
| is_paid | Boolean | default false | 付款状态 |
| created_at | DateTime | default now | 创建时间 |
| paid_at | DateTime | null | 付款时间 |
| completed_at | DateTime | null | 完成时间 |
| canceled_at | DateTime | null | 取消时间 |
| cancel_reason | String(200) | null | 取消原因 |
| internal_notes | Text | null | 内部备注 |
| tracking_number | String(100) | null | 订单级快递单号（全发后） |
| shipped_at | DateTime | null | 订单级发货时间（全发后） |
| receiver_name | String(30) | null | 下单时收货人快照 |
| receiver_phone | String(20) | null | 下单时手机号快照 |
| receiver_address_text | String(200) | null | 下单时地址快照 |
| receiver_postal_code | String(10) | null | 下单时邮编快照 |

业务补充：
- 订单页应优先读取 `receiver_*` 快照，避免用户后续改地址影响历史订单。

---

## `order_item`（订单项）

| 列名 | 类型 | 约束/默认 | 说明 |
|---|---|---|---|
| id | Integer | PK | 订单项主键 |
| order_id | Integer | FK -> order.id, not null | 所属订单 |
| product_id | Integer | FK -> product.id, null | 商品 ID（可空） |
| variant_id | Integer | FK -> product_variant.id, null | 规格 ID（可空） |
| name | String(100) | not null | 商品名快照 |
| spec_note | String(200) | null | 规格备注 |
| qty | Integer | not null | 下单数量 |
| link | String(500) | null | 链接（可选） |
| images | Text | null | 图片 JSON（可选） |
| variant_name | String(100) | null | 规格名快照 |
| unit_price | Numeric(10,2) | null | 下单单价快照 |
| unit_cost | Numeric(10,2) | null | 下单成本快照 |
| shipped_qty | Integer | default 0 | 已发货数量（部分发货） |
| shipped_tracking_number | String(100) | null | 该项快递单号 |
| shipped_at | DateTime | null | 该项发货时间 |

---

## `cart_item`（购物车）

| 列名 | 类型 | 约束/默认 | 说明 |
|---|---|---|---|
| id | Integer | PK | 主键 |
| user_id | Integer | FK -> user.id, not null | 用户 |
| product_id | Integer | FK -> product.id, not null | 商品 |
| variant_id | Integer | FK -> product_variant.id, null | 规格 |
| qty | Integer | default 1 | 数量 |
| created_at | DateTime | default now | 加入时间 |
| variant_name | String(100) | null | 规格名展示 |

---

## `payment_attachment`（付款凭证）

| 列名 | 类型 | 约束/默认 | 说明 |
|---|---|---|---|
| id | Integer | PK | 主键 |
| order_id | Integer | FK -> order.id, not null | 所属订单 |
| user_note | String(200) | null | 用户备注 |
| image_urls | Text | null | 图片列表 JSON |
| uploaded_at | DateTime | default now | 上传时间 |

---

## `admin_user`（管理员）

| 列名 | 类型 | 约束/默认 | 说明 |
|---|---|---|---|
| id | Integer | PK | 主键 |
| username | String(80) | unique, not null | 管理员用户名 |
| password_hash | String(128) | not null | 密码哈希 |
| created_at | DateTime | default now | 创建时间 |

---

## `system_settings`（系统设置）

| 列名 | 类型 | 约束/默认 | 说明 |
|---|---|---|---|
| id | Integer | PK | 主键 |
| key | String(50) | unique, not null | 配置项 |
| value | Text | null | 配置值 |
| updated_at | DateTime | default now/onupdate | 更新时间 |

---

## `email_verification`（邮箱验证码）

| 列名 | 类型 | 约束/默认 | 说明 |
|---|---|---|---|
| id | Integer | PK | 主键 |
| email | String(120) | index, not null | 邮箱 |
| code | String(6) | not null | 验证码 |
| expire_at | DateTime | not null | 过期时间 |
| used | Boolean | default false | 是否已使用 |
| created_at | DateTime | default now | 创建时间 |

---

## `version`（版本）

| 列名 | 类型 | 约束/默认 | 说明 |
|---|---|---|---|
| id | Integer | PK | 主键 |
| version | String(20) | unique, not null | 版本号 |
| title | String(200) | not null | 标题 |
| description | Text | not null | 描述 |
| release_date | DateTime | default now | 发布日期 |
| is_current | Boolean | default false | 是否当前版本 |
| created_at | DateTime | default now | 创建时间 |

---

## `chat_message`（聊天消息）

| 列名 | 类型 | 约束/默认 | 说明 |
|---|---|---|---|
| id | Integer | PK | 主键 |
| user_id | Integer | FK -> user.id, not null | 关联用户 |
| sender | String(10) | not null | 发送方（user/admin） |
| text | Text | null | 文本 |
| image_path | String(512) | null | 图片存储键 |
| file_path | String(512) | null | 文件存储键 |
| file_name | String(255) | null | 原始文件名 |
| file_mime | String(100) | null | MIME |
| created_at | DateTime | default now | 创建时间 |
| is_read_by_user | Boolean | default false | 用户已读 |
| is_read_by_admin | Boolean | default false | 管理员已读 |

业务补充：
- 聊天附件现使用私有存储，并通过鉴权路由访问，不再推荐公开静态直链。

---

## 3. 兼容性说明（旧库升级）

以下字段可能由运行时自动补列：
- `order_item`: `shipped_qty`, `shipped_tracking_number`, `shipped_at`
- `order`: `receiver_name`, `receiver_phone`, `receiver_address_text`, `receiver_postal_code`
- `address`: `is_default`

历史数据兼容策略：
- 订单地址：若 `receiver_*` 为空，则回退读取用户当前默认地址（仅旧订单）。
- 默认地址：若用户存在地址但都非默认，会在启动时自动把最新地址设为默认。
