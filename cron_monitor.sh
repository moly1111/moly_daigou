#!/bin/bash
# 定时监控脚本 - 用于cron任务
# 每5分钟检查一次服务状态，异常时自动修复

LOG_FILE="/opt/moly_daigou/logs/cron_monitor.log"
ERROR_FILE="/opt/moly_daigou/logs/cron_errors.log"
ALERT_FILE="/opt/moly_daigou/logs/alerts.log"

# 创建日志目录
mkdir -p "$(dirname "$LOG_FILE")"

# 记录函数
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

log_error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $1" >> "$ERROR_FILE"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ALERT: $1" >> "$ALERT_FILE"
}

# 检查服务状态
check_service() {
    # 检查Gunicorn进程
    if ! ps aux | grep gunicorn | grep -v grep >/dev/null; then
        log_error "Gunicorn进程未运行"
        return 1
    fi
    
    # 检查端口
    if ! ss -tlnp | grep :8080 >/dev/null; then
        log_error "端口8080未监听"
        return 1
    fi
    
    # 检查HTTP响应
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/admin 2>/dev/null)
    if [ "$HTTP_CODE" != "200" ] && [ "$HTTP_CODE" != "302" ]; then
        log_error "HTTP服务异常，状态码: $HTTP_CODE"
        return 1
    fi
    
    return 0
}

# 自动修复
auto_fix() {
    log "开始自动修复..."
    
    # 停止Gunicorn
    sudo pkill -9 -f gunicorn
    sleep 3
    
    # 进入项目目录
    cd /opt/moly_daigou
    
    # 激活虚拟环境
    source venv/bin/activate
    
    # 启动Gunicorn
    nohup gunicorn --workers 1 --threads 8 --worker-class gthread --timeout 60 --keep-alive 5 --bind 0.0.0.0:8080 app:app > app.log 2>&1 &
    
    # 等待启动
    sleep 10
    
    # 验证修复结果
    if check_service; then
        log "自动修复成功"
        return 0
    else
        log_error "自动修复失败"
        return 1
    fi
}

# 主监控逻辑
main() {
    log "开始定时监控检查..."
    
    if check_service; then
        log "服务状态正常"
    else
        log_error "检测到服务异常，开始自动修复..."
        if auto_fix; then
            log "服务已修复"
        else
            log_error "服务修复失败，需要人工干预"
        fi
    fi
}

# 执行监控
main
