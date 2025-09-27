#!/bin/bash
# 服务器监控和故障排除脚本
# 自动记录系统状态到日志文件

# 设置日志文件路径
LOG_DIR="/opt/moly_daigou/logs"
MONITOR_LOG="$LOG_DIR/monitor.log"
ERROR_LOG="$LOG_DIR/error.log"
SYSTEM_LOG="$LOG_DIR/system.log"

# 创建日志目录
mkdir -p "$LOG_DIR"

# 时间戳函数
timestamp() {
    date '+%Y-%m-%d %H:%M:%S'
}

# 记录函数
log_info() {
    echo "[$(timestamp)] INFO: $1" | tee -a "$MONITOR_LOG"
}

log_error() {
    echo "[$(timestamp)] ERROR: $1" | tee -a "$ERROR_LOG"
}

log_system() {
    echo "[$(timestamp)] SYSTEM: $1" | tee -a "$SYSTEM_LOG"
}

# 检查服务状态
check_service() {
    log_info "=== 服务状态检查 ==="
    
    # 检查Gunicorn进程
    GUNICORN_PIDS=$(ps aux | grep gunicorn | grep -v grep | awk '{print $2}')
    if [ -n "$GUNICORN_PIDS" ]; then
        log_info "Gunicorn进程运行中: $GUNICORN_PIDS"
        ps aux | grep gunicorn | grep -v grep | tee -a "$MONITOR_LOG"
    else
        log_error "Gunicorn进程未运行！"
        return 1
    fi
    
    # 检查端口占用
    PORT_STATUS=$(ss -tlnp | grep :8080)
    if [ -n "$PORT_STATUS" ]; then
        log_info "端口8080被占用: $PORT_STATUS"
    else
        log_error "端口8080未被占用！"
        return 1
    fi
    
    # 检查HTTP响应
    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/admin 2>/dev/null)
    if [ "$HTTP_STATUS" = "200" ] || [ "$HTTP_STATUS" = "302" ]; then
        log_info "HTTP服务正常，状态码: $HTTP_STATUS"
    else
        log_error "HTTP服务异常，状态码: $HTTP_STATUS"
        return 1
    fi
}

# 检查数据库连接
check_database() {
    log_info "=== 数据库连接检查 ==="
    
    cd /opt/moly_daigou
    source venv/bin/activate
    
    # 检查数据库连接
    python3 -c "
from app import app, db
try:
    with app.app_context():
        db.session.execute(db.text('SELECT 1'))
        print('数据库连接正常')
except Exception as e:
    print(f'数据库连接失败: {e}')
    exit(1)
" 2>&1 | tee -a "$MONITOR_LOG"
    
    if [ ${PIPESTATUS[0]} -eq 0 ]; then
        log_info "数据库连接正常"
    else
        log_error "数据库连接失败"
        return 1
    fi
}

# 检查系统资源
check_system_resources() {
    log_info "=== 系统资源检查 ==="
    
    # CPU使用率
    CPU_USAGE=$(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d'%' -f1)
    log_system "CPU使用率: ${CPU_USAGE}%"
    
    # 内存使用率
    MEMORY_USAGE=$(free | grep Mem | awk '{printf "%.2f", $3/$2 * 100.0}')
    log_system "内存使用率: ${MEMORY_USAGE}%"
    
    # 磁盘使用率
    DISK_USAGE=$(df -h /opt | tail -1 | awk '{print $5}')
    log_system "磁盘使用率: $DISK_USAGE"
    
    # 检查磁盘空间是否不足
    DISK_PERCENT=$(df /opt | tail -1 | awk '{print $5}' | sed 's/%//')
    if [ "$DISK_PERCENT" -gt 90 ]; then
        log_error "磁盘空间不足！使用率: ${DISK_PERCENT}%"
    fi
}

# 检查应用日志
check_application_logs() {
    log_info "=== 应用日志检查 ==="
    
    # 检查应用日志文件
    if [ -f "/opt/moly_daigou/app.log" ]; then
        log_info "应用日志文件存在"
        
        # 检查最近的错误
        RECENT_ERRORS=$(tail -50 /opt/moly_daigou/app.log | grep -i error | wc -l)
        if [ "$RECENT_ERRORS" -gt 0 ]; then
            log_error "发现 $RECENT_ERRORS 个最近的错误"
            tail -50 /opt/moly_daigou/app.log | grep -i error | tee -a "$ERROR_LOG"
        else
            log_info "最近50行日志中无错误"
        fi
        
        # 检查最近的警告
        RECENT_WARNINGS=$(tail -50 /opt/moly_daigou/app.log | grep -i warning | wc -l)
        if [ "$RECENT_WARNINGS" -gt 0 ]; then
            log_info "发现 $RECENT_WARNINGS 个最近的警告"
            tail -50 /opt/moly_daigou/app.log | grep -i warning | tee -a "$MONITOR_LOG"
        fi
    else
        log_error "应用日志文件不存在！"
    fi
}

# 检查网络连接
check_network() {
    log_info "=== 网络连接检查 ==="
    
    # 检查网络连接
    if ping -c 1 8.8.8.8 >/dev/null 2>&1; then
        log_info "网络连接正常"
    else
        log_error "网络连接异常"
    fi
    
    # 检查DNS解析
    if nslookup google.com >/dev/null 2>&1; then
        log_info "DNS解析正常"
    else
        log_error "DNS解析异常"
    fi
}

# 自动修复常见问题
auto_fix() {
    log_info "=== 自动修复检查 ==="
    
    # 检查并重启Gunicorn
    if ! ps aux | grep gunicorn | grep -v grep >/dev/null; then
        log_info "尝试重启Gunicorn服务..."
        cd /opt/moly_daigou
        source venv/bin/activate
        nohup gunicorn --workers 1 --threads 8 --worker-class gthread --timeout 60 --keep-alive 5 --bind 0.0.0.0:8080 app:app > app.log 2>&1 &
        sleep 5
        
        if ps aux | grep gunicorn | grep -v grep >/dev/null; then
            log_info "Gunicorn重启成功"
        else
            log_error "Gunicorn重启失败"
        fi
    fi
    
    # 检查并清理僵尸进程
    ZOMBIE_COUNT=$(ps aux | awk '$8 ~ /^Z/ { print $2 }' | wc -l)
    if [ "$ZOMBIE_COUNT" -gt 0 ]; then
        log_info "发现 $ZOMBIE_COUNT 个僵尸进程"
        ps aux | awk '$8 ~ /^Z/ { print $2 }' | xargs -r kill -9 2>/dev/null
        log_info "已清理僵尸进程"
    fi
}

# 生成健康报告
generate_health_report() {
    log_info "=== 生成健康报告 ==="
    
    REPORT_FILE="$LOG_DIR/health_report_$(date +%Y%m%d_%H%M%S).txt"
    
    {
        echo "=== 系统健康报告 ==="
        echo "生成时间: $(timestamp)"
        echo ""
        
        echo "=== 服务状态 ==="
        ps aux | grep gunicorn | grep -v grep
        echo ""
        
        echo "=== 端口状态 ==="
        ss -tlnp | grep :8080
        echo ""
        
        echo "=== 系统资源 ==="
        echo "CPU使用率: $(top -bn1 | grep "Cpu(s)" | awk '{print $2}')"
        echo "内存使用率: $(free | grep Mem | awk '{printf "%.2f%%", $3/$2 * 100.0}')"
        echo "磁盘使用率: $(df -h /opt | tail -1 | awk '{print $5}')"
        echo ""
        
        echo "=== 最近错误 ==="
        if [ -f "/opt/moly_daigou/app.log" ]; then
            tail -20 /opt/moly_daigou/app.log | grep -i error
        fi
        echo ""
        
        echo "=== 网络状态 ==="
        ping -c 1 8.8.8.8
        echo ""
        
    } > "$REPORT_FILE"
    
    log_info "健康报告已生成: $REPORT_FILE"
}

# 清理旧日志
cleanup_old_logs() {
    log_info "=== 清理旧日志 ==="
    
    # 删除7天前的日志文件
    find "$LOG_DIR" -name "*.log" -mtime +7 -delete 2>/dev/null
    find "$LOG_DIR" -name "health_report_*.txt" -mtime +7 -delete 2>/dev/null
    
    log_info "已清理7天前的日志文件"
}

# 主监控函数
main_monitor() {
    log_info "开始系统监控检查..."
    
    # 执行各项检查
    check_service
    SERVICE_STATUS=$?
    
    check_database
    DB_STATUS=$?
    
    check_system_resources
    
    check_application_logs
    
    check_network
    
    # 如果服务异常，尝试自动修复
    if [ $SERVICE_STATUS -ne 0 ] || [ $DB_STATUS -ne 0 ]; then
        log_error "检测到服务异常，尝试自动修复..."
        auto_fix
    fi
    
    # 生成健康报告
    generate_health_report
    
    # 清理旧日志
    cleanup_old_logs
    
    log_info "监控检查完成"
}

# 实时监控模式
realtime_monitor() {
    log_info "启动实时监控模式..."
    
    while true; do
        main_monitor
        sleep 300  # 每5分钟检查一次
    done
}

# 显示帮助信息
show_help() {
    echo "服务器监控和故障排除脚本"
    echo ""
    echo "用法: $0 [选项]"
    echo ""
    echo "选项:"
    echo "  check      - 执行一次完整检查"
    echo "  monitor    - 启动实时监控模式（每5分钟检查一次）"
    echo "  report     - 生成健康报告"
    echo "  logs       - 查看最近的监控日志"
    echo "  errors     - 查看错误日志"
    echo "  system     - 查看系统日志"
    echo "  help       - 显示此帮助信息"
    echo ""
    echo "日志文件位置:"
    echo "  监控日志: $MONITOR_LOG"
    echo "  错误日志: $ERROR_LOG"
    echo "  系统日志: $SYSTEM_LOG"
}

# 查看日志
view_logs() {
    case "$1" in
        "logs")
            echo "=== 监控日志 ==="
            tail -50 "$MONITOR_LOG"
            ;;
        "errors")
            echo "=== 错误日志 ==="
            tail -50 "$ERROR_LOG"
            ;;
        "system")
            echo "=== 系统日志 ==="
            tail -50 "$SYSTEM_LOG"
            ;;
        *)
            echo "可用选项: logs, errors, system"
            ;;
    esac
}

# 主程序
case "$1" in
    "check")
        main_monitor
        ;;
    "monitor")
        realtime_monitor
        ;;
    "report")
        generate_health_report
        ;;
    "logs"|"errors"|"system")
        view_logs "$1"
        ;;
    "help"|"-h"|"--help")
        show_help
        ;;
    *)
        echo "用法: $0 {check|monitor|report|logs|errors|system|help}"
        echo "运行 '$0 help' 查看详细帮助"
        ;;
esac
