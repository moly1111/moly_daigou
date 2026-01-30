# RFID 入库 API：接收【商品id;规格id;数量】格式，校验归属后对对应规格库存加上数量
import logging
import os

from flask import Blueprint, request, jsonify

from core.extensions import db
from core.models import Product, ProductVariant

logger = logging.getLogger(__name__)

api_rfid = Blueprint('api_rfid', __name__, url_prefix='/api/rfid')


def _check_api_key():
    """校验 API Key（Header X-API-Key 或 query api_key），未配置则拒绝所有请求。"""
    key = os.getenv('RFID_API_KEY', '').strip()
    if not key:
        return False, '未配置 RFID_API_KEY，接口不可用'
    provided = request.headers.get('X-API-Key') or request.args.get('api_key')
    if not provided or provided != key:
        return False, 'API Key 无效'
    return True, None


@api_rfid.route('/ingest', methods=['POST'])
def rfid_ingest():
    """
    接收 RFID 数据。格式一：商品id;规格id;数量（规格 id 为全局主键）。
    格式二：商品id;L:逻辑规格编号;数量（按商品从 1 开始的编号，如 2;L:1;3 表示商品2的规格1入库3）。
    请求体 JSON：{ "data": "5;12;3" } 或 { "rfid": "2;L:1;3" }
    """
    ok, err = _check_api_key()
    if not ok:
        return jsonify({'ok': False, 'error': err}), 401

    raw = None
    if request.is_json:
        raw = request.json.get('data') or request.json.get('rfid')
    if raw is None and request.form:
        raw = request.form.get('data') or request.form.get('rfid')
    if raw is None:
        return jsonify({'ok': False, 'error': '缺少 data 或 rfid 字段'}), 400

    s = (raw if isinstance(raw, str) else str(raw)).strip()
    parts = [p.strip() for p in s.split(';')]
    if len(parts) != 3:
        return jsonify({'ok': False, 'error': f'格式应为 商品id;规格id;数量 或 商品id;L:逻辑规格编号;数量，当前得到 {len(parts)} 段'}), 400

    try:
        product_id = int(parts[0])
        quantity = int(parts[2])
    except ValueError:
        return jsonify({'ok': False, 'error': '商品id、数量须为整数'}), 400
    if quantity < 0:
        return jsonify({'ok': False, 'error': '数量不能为负数'}), 400

    # 规格：支持全局 id 或 逻辑编号 L:1（该商品下第 1 个规格）
    use_local_id = parts[1].upper().startswith('L:')
    if use_local_id:
        try:
            local_id = int(parts[1][2:].strip())
        except ValueError:
            return jsonify({'ok': False, 'error': '逻辑规格编号须为整数（如 L:1）'}), 400
    else:
        try:
            variant_id = int(parts[1])
        except ValueError:
            return jsonify({'ok': False, 'error': '规格id须为整数'}), 400

    product = Product.query.get(product_id)
    if not product:
        return jsonify({'ok': False, 'error': f'商品 id={product_id} 不存在'}), 404

    if use_local_id:
        variant = product.get_variant_by_local_id(local_id)
        if not variant:
            return jsonify({'ok': False, 'error': f'商品 id={product_id} 下不存在逻辑规格编号 {local_id}'}), 404
    else:
        variant = ProductVariant.query.get(variant_id)
        if not variant:
            return jsonify({'ok': False, 'error': f'规格 id={variant_id} 不存在'}), 404
        if variant.product_id != product_id:
            return jsonify({
                'ok': False,
                'error': f'规格 id={variant_id} 不属于商品 id={product_id}，归属校验失败'
            }), 400

    try:
        variant.stock = (variant.stock or 0) + quantity
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.exception('RFID 入库写库失败: %s', e)
        return jsonify({'ok': False, 'error': '库存更新失败'}), 500

    logger.info('RFID 入库: product_id=%s variant_id=%s quantity=%s stock_after=%s', product_id, variant.id, quantity, variant.stock)
    return jsonify({
        'ok': True,
        'product_id': product_id,
        'variant_id': variant.id,
        'variant_local_id': getattr(variant, 'local_id', None),
        'quantity': quantity,
        'product_title': product.title,
        'variant_name': variant.name,
        'stock_after': variant.stock,
    }), 200
