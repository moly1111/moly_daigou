# 聊天相关路由与 API（用户端 + 管理端），统一消息序列化
from datetime import datetime
import os
import random
import string

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from core.extensions import db
from core.models import ChatMessage, User, AdminUser
from core.utils import admin_required

chat_bp = Blueprint('chat', __name__)


def _save_chat_image(file_storage):
    if not file_storage or file_storage.filename == '':
        return None
    filename = secure_filename(file_storage.filename)
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    rnd = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    final_name = f"{ts}_{rnd}.{ext}"
    save_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'chat')
    os.makedirs(save_dir, exist_ok=True)
    path = os.path.join(save_dir, final_name)
    file_storage.save(path)
    return f"/static/uploads/chat/{final_name}"


def _save_chat_file(file_storage):
    if not file_storage or file_storage.filename == '':
        return None, None, None
    filename = secure_filename(file_storage.filename)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    rnd = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    mime = file_storage.mimetype or ''
    has_ext = ('.' in filename and not filename.endswith('.'))
    if not has_ext:
        ext_map = {
            'application/pdf': 'pdf',
            'text/plain': 'txt',
            'text/csv': 'csv',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
            'application/msword': 'doc',
            'application/vnd.ms-excel': 'xls',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
        }
        guessed = ext_map.get(mime)
        if guessed:
            filename = f"{filename}.{guessed}"
    final_name = f"{ts}_{rnd}_{filename}"
    save_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'chat')
    os.makedirs(save_dir, exist_ok=True)
    path = os.path.join(save_dir, final_name)
    file_storage.save(path)
    return f"/static/uploads/chat/{final_name}", filename, file_storage.mimetype


def _message_to_dict(m):
    """统一聊天消息 API 返回结构（用户端与管理端一致）。"""
    return {
        'id': m.id,
        'sender': m.sender,
        'text': m.text,
        'image_path': m.image_path,
        'file_path': m.file_path,
        'file_name': m.file_name,
        'file_mime': m.file_mime,
        'created_at': m.created_at.isoformat(),
    }


# ---------- 用户端 ----------
@chat_bp.route('/chat', methods=['GET', 'POST'])
@login_required
def chat_page():
    if isinstance(current_user, AdminUser):
        return redirect(url_for('admin.admin_chats'))
    if request.method == 'POST':
        text = request.form.get('text', '').strip()
        image = request.files.get('image')
        file_any = request.files.get('file')
        image_path = _save_chat_image(image) if image else None
        file_url, file_name, file_mime = _save_chat_file(file_any) if file_any else (None, None, None)
        if not text and not image_path and not file_url:
            flash('请输入消息或选择图片', 'warning')
        else:
            msg = ChatMessage(
                user_id=current_user.id, sender='user',
                text=text or None, image_path=image_path,
                file_path=file_url, file_name=file_name, file_mime=file_mime
            )
            db.session.add(msg)
            db.session.commit()
        return redirect(url_for('chat.chat_page'))
    messages = ChatMessage.query.filter_by(user_id=current_user.id).order_by(ChatMessage.created_at.asc()).limit(100).all()
    ChatMessage.query.filter_by(user_id=current_user.id, sender='admin', is_read_by_user=False).update({ChatMessage.is_read_by_user: True})
    db.session.commit()
    return render_template('frontend/chat.html', messages=messages)


@chat_bp.post('/api/chat/send')
@login_required
def api_chat_send_user():
    if isinstance(current_user, AdminUser):
        return jsonify({'error': 'forbidden'}), 403
    text = request.form.get('text', '').strip()
    image = request.files.get('image')
    file_any = request.files.get('file')
    image_path = _save_chat_image(image) if image else None
    file_url, file_name, file_mime = _save_chat_file(file_any) if file_any else (None, None, None)
    if not text and not image_path and not file_url:
        return jsonify({'error': 'empty'}), 400
    msg = ChatMessage(
        user_id=current_user.id, sender='user',
        text=text or None, image_path=image_path,
        file_path=file_url, file_name=file_name, file_mime=file_mime
    )
    db.session.add(msg)
    db.session.commit()
    return jsonify(_message_to_dict(msg))


@chat_bp.get('/api/chat/messages')
@login_required
def api_chat_messages_user():
    if isinstance(current_user, AdminUser):
        return jsonify({'error': 'forbidden'}), 403
    try:
        since_id = request.args.get('since_id', type=int)
        q = ChatMessage.query.filter_by(user_id=current_user.id).order_by(ChatMessage.id.asc())
        if since_id:
            q = q.filter(ChatMessage.id > since_id)
        msgs = q.all()
        ChatMessage.query.filter_by(user_id=current_user.id, sender='admin', is_read_by_user=False).update({ChatMessage.is_read_by_user: True})
        db.session.commit()
        return jsonify([_message_to_dict(m) for m in msgs])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ---------- 管理端 ----------
@chat_bp.route('/admin/chats')
@login_required
@admin_required
def admin_chats():
    users = User.query.all()
    data = []
    for u in users:
        last_msg = ChatMessage.query.filter_by(user_id=u.id).order_by(ChatMessage.created_at.desc()).first()
        unread = ChatMessage.query.filter_by(user_id=u.id, sender='user', is_read_by_admin=False).count()
        if last_msg or unread:
            data.append({'user': u, 'last_msg': last_msg, 'unread': unread})
    data.sort(key=lambda x: (x['last_msg'].created_at if x['last_msg'] else datetime.min), reverse=True)
    return render_template('admin/chats.html', items=data)


@chat_bp.route('/admin/chats/<int:user_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_chat_detail(user_id: int):
    user = User.query.get_or_404(user_id)
    if request.method == 'POST':
        text = request.form.get('text', '').strip()
        image = request.files.get('image')
        file_any = request.files.get('file')
        image_path = _save_chat_image(image) if image else None
        file_url, file_name, file_mime = _save_chat_file(file_any) if file_any else (None, None, None)
        if not text and not image_path and not file_url:
            flash('请输入消息或选择图片', 'warning')
        else:
            msg = ChatMessage(
                user_id=user.id, sender='admin',
                text=text or None, image_path=image_path,
                file_path=file_url, file_name=file_name, file_mime=file_mime
            )
            db.session.add(msg)
            db.session.commit()
        return redirect(url_for('chat.admin_chat_detail', user_id=user.id))
    messages = ChatMessage.query.filter_by(user_id=user.id).order_by(ChatMessage.created_at.asc()).all()
    ChatMessage.query.filter_by(user_id=user.id, sender='user', is_read_by_admin=False).update({ChatMessage.is_read_by_admin: True})
    db.session.commit()
    return render_template('admin/chat_detail.html', user=user, messages=messages)


@chat_bp.post('/api/admin/chats/<int:user_id>/send')
@login_required
@admin_required
def api_chat_send_admin(user_id: int):
    user = User.query.get_or_404(user_id)
    text = request.form.get('text', '').strip()
    image = request.files.get('image')
    file_any = request.files.get('file')
    image_path = _save_chat_image(image) if image else None
    file_url, file_name, file_mime = _save_chat_file(file_any) if file_any else (None, None, None)
    if not text and not image_path and not file_url:
        return jsonify({'error': 'empty'}), 400
    msg = ChatMessage(
        user_id=user.id, sender='admin',
        text=text or None, image_path=image_path,
        file_path=file_url, file_name=file_name, file_mime=file_mime
    )
    db.session.add(msg)
    db.session.commit()
    return jsonify(_message_to_dict(msg))


@chat_bp.get('/api/admin/chats/<int:user_id>/messages')
@login_required
@admin_required
def api_chat_messages_admin(user_id: int):
    try:
        since_id = request.args.get('since_id', type=int)
        q = ChatMessage.query.filter_by(user_id=user_id).order_by(ChatMessage.id.asc())
        if since_id:
            q = q.filter(ChatMessage.id > since_id)
        msgs = q.all()
        ChatMessage.query.filter_by(user_id=user_id, sender='user', is_read_by_admin=False).update({ChatMessage.is_read_by_admin: True})
        db.session.commit()
        return jsonify([_message_to_dict(m) for m in msgs])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@chat_bp.get('/api/chat/unread')
@login_required
def api_chat_unread():
    if isinstance(current_user, AdminUser):
        count = ChatMessage.query.filter_by(sender='user', is_read_by_admin=False).count()
        return jsonify({'role': 'admin', 'unread': count})
    count = ChatMessage.query.filter_by(user_id=current_user.id, sender='admin', is_read_by_user=False).count()
    return jsonify({'role': 'user', 'unread': count})
