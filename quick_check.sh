#!/bin/bash
# 快速检查和修复脚本
# 用于快速诊断和修复常见问题

LOG_FILE="/opt/moly_daigou/logs/quick_check.log"
mkdir -p "$(dirname "$LOG_FILE")"

# 记录函数
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# 快速检查服务状态
quick_check() {
    log "=== 快速检查开始 ==="
    
    # 检查Gunicorn进程
    if ps aux | grep gunicorn | grep -v grep >/dev/null; then
        log "✅ Gunicorn进程运行正常"
    else
        log "❌ Gunicorn进程未运行"
        return 1
    fi
    
    # 检查端口
    if ss -tlnp | grep :8080 >/dev/null; then
        log "✅ 端口8080正常监听"
    else
        log "❌ 端口8080未监听"
        return 1
    fi
    
    # 检查HTTP响应
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/admin 2>/dev/null)
    if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "302" ]; then
        log "✅ HTTP服务正常 (状态码: $HTTP_CODE)"
    else
        log "❌ HTTP服务异常 (状态码: $HTTP_CODE)"
        return 1
    fi
    
    log "=== 快速检查完成 ==="
    return 0
}

# 快速修复
quick_fix() {
    log "=== 开始快速修复 ==="
    
    # 停止所有Gunicorn进程
    log "停止Gunicorn进程..."
    sudo pkill -9 -f gunicorn
    sleep 3
    
    # 进入项目目录
    cd /opt/moly_daigou
    
    # 激活虚拟环境
    source venv/bin/activate
    
    # 启动Gunicorn
    log "启动Gunicorn服务..."
    nohup gunicorn --workers 1 --threads 8 --worker-class gthread --timeout 60 --keep-alive 5 --bind 0.0.0.0:8080 app:app > app.log 2>&1 &
    
    # 等待启动
    sleep 10
    
    # 检查是否启动成功
    if ps aux | grep gunicorn | grep -v grep >/dev/null; then
        log "✅ Gunicorn重启成功"
    else
        log "❌ Gunicorn重启失败"
        return 1
    fi
    
    log "=== 快速修复完成 ==="
    return 0
}

# 显示状态
show_status() {
    echo "=== 服务状态 ==="
    ps aux | grep gunicorn | grep -v grep
    echo ""
    
    echo "=== 端口状态 ==="
    ss -tlnp | grep :8080
    echo ""
    
    echo "=== HTTP测试 ==="
    curl -I http://localhost:8080/admin
    echo ""
    
    echo "=== 最近日志 ==="
    if [ -f "/opt/moly_daigou/app.log" ]; then
        tail -20 /opt/moly_daigou/app.log
    else
        echo "日志文件不存在"
    fi
}

# 清理日志
clean_logs() {
    log "清理日志文件..."
    find /opt/moly_daigou/logs -name "*.log" -mtime +7 -delete 2>/dev/null
    log "日志清理完成"
}

# 主程序
case "$1" in
    "check")
        quick_check
        ;;
    "fix")
        quick_fix
        ;;
    "status")
        show_status
        ;;
    "clean")
        clean_logs
        ;;
    *)
        echo "用法: $0 {check|fix|status|clean}"
        echo ""
        echo "选项:"
        echo "  check  - 快速检查服务状态"
        echo "  fix  - 快速修复服务问题"
        echo "  status - 显示详细状态信息"
        echo "  clean - 清理旧日志文件"
        ;;
esac
