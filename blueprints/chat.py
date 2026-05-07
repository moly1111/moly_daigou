# 聊天相关路由与 API（用户端 + 管理端），统一消息序列化
from datetime import datetime
import os
import random
import string
import mimetypes
from typing import Optional

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, abort, send_file
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from core.extensions import db
from core.models import ChatMessage, User, AdminUser
from core.utils import admin_required

chat_bp = Blueprint('chat', __name__)


def _private_chat_dir():
    base = current_app.config.get('PRIVATE_UPLOAD_FOLDER', os.path.join('instance', 'private_uploads'))
    return os.path.join(base, 'chat')


def _chat_media_key(filename: str) -> str:
    return f"/private/chat/{filename}"


def _secure_media_url(message_id: int, media_type: str) -> str:
    return url_for('chat.chat_media', message_id=message_id, media_type=media_type)


def _resolve_media_abs_path(stored_path: str) -> Optional[str]:
    if not stored_path:
        return None
    old_prefix = '/static/uploads/chat/'
    private_prefix = '/private/chat/'
    upload_chat_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'chat')
    private_chat_dir = _private_chat_dir()

    if stored_path.startswith(private_prefix):
        filename = os.path.basename(stored_path[len(private_prefix):])
        return os.path.join(private_chat_dir, filename)
    if stored_path.startswith(old_prefix):
        filename = os.path.basename(stored_path[len(old_prefix):])
        return os.path.join(upload_chat_dir, filename)
    filename = os.path.basename(stored_path)
    if not filename:
        return None
    private_candidate = os.path.join(private_chat_dir, filename)
    if os.path.isfile(private_candidate):
        return private_candidate
    return os.path.join(upload_chat_dir, filename)


def _save_chat_image(file_storage):
    if not file_storage or file_storage.filename == '':
        return None
    filename = secure_filename(file_storage.filename)
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    rnd = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    final_name = f"{ts}_{rnd}.{ext}"
    save_dir = _private_chat_dir()
    os.makedirs(save_dir, exist_ok=True)
    path = os.path.join(save_dir, final_name)
    file_storage.save(path)
    return _chat_media_key(final_name)


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
    save_dir = _private_chat_dir()
    os.makedirs(save_dir, exist_ok=True)
    path = os.path.join(save_dir, final_name)
    file_storage.save(path)
    return _chat_media_key(final_name), filename, file_storage.mimetype


def _message_to_dict(m):
    """统一聊天消息 API 返回结构（用户端与管理端一致）。"""
    return {
        'id': m.id,
        'sender': m.sender,
        'text': m.text,
        'image_path': _secure_media_url(m.id, 'image') if m.image_path else None,
        'file_path': _secure_media_url(m.id, 'file') if m.file_path else None,
        'file_name': m.file_name,
        'file_mime': m.file_mime,
        'created_at': m.created_at.isoformat(),
    }


def _attach_secure_urls(messages):
    for m in messages:
        m.image_url = _secure_media_url(m.id, 'image') if m.image_path else None
        m.file_url = _secure_media_url(m.id, 'file') if m.file_path else None
    return messages


@chat_bp.get('/chat/media/<int:message_id>/<media_type>')
@login_required
def chat_media(message_id: int, media_type: str):
    if media_type not in ('image', 'file'):
        abort(404)
    msg = ChatMessage.query.get_or_404(message_id)
    if not isinstance(current_user, AdminUser) and msg.user_id != current_user.id:
        abort(403)
    stored_path = msg.image_path if media_type == 'image' else msg.file_path
    if not stored_path:
        abort(404)
    abs_path = _resolve_media_abs_path(stored_path)
    if not abs_path or not os.path.isfile(abs_path):
        abort(404)
    mimetype = msg.file_mime if media_type == 'file' else (mimetypes.guess_type(abs_path)[0] or 'application/octet-stream')
    as_attachment = media_type == 'file'
    download_name = msg.file_name if media_type == 'file' else os.path.basename(abs_path)
    return send_file(abs_path, mimetype=mimetype, as_attachment=as_attachment, download_name=download_name)


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
    _attach_secure_urls(messages)
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
    _attach_secure_urls(messages)
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
