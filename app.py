# -*- coding: utf-8 -*-
"""
豆包远程登录 - 本地 Web 服务（含管理看板）
运行后自动启动隧道，生成一次性动态链接，
远程用户通过链接输入手机号和验证码，自动操作本地桌面豆包完成登录。
后台看板可统计链接情况、访问记录、登录结果。
"""

import os
import sys
import time
import json
import secrets
import logging
import threading
import subprocess
import re
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, abort, send_file

# 配置
LOCAL_PORT = 58231
TOKEN_EXPIRE_MINUTES = 10
MAX_USES_PER_TOKEN = 1
MAX_LOG_ENTRIES = 200

# 兼容 PyInstaller 打包后的路径
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
    TEMPLATE_DIR = os.path.join(sys._MEIPASS, 'templates')
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')

LOG_FILE = os.path.join(BASE_DIR, 'remote_login.log')
QRCODE_FILE = os.path.join(BASE_DIR, 'qrcode.png')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder=TEMPLATE_DIR)
START_TIME = datetime.now()


# ============ CORS 支持（允许 file:// 页面直接访问本地服务） ============
@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response


@app.route('/', defaults={'path': ''}, methods=['OPTIONS'])
@app.route('/<path:path>', methods=['OPTIONS'])
def handle_options(path):
    return ('', 204)

# ============ 全局数据存储 ============
class DataStore:
    def __init__(self):
        self._lock = threading.Lock()
        self.tokens = {}           # 活跃 token -> info
        self.token_history = []    # 所有 token 历史记录（用于统计）
        self.visit_logs = []       # 页面访问日志
        self.login_logs = []       # 登录操作日志

    def create_token(self):
        token = secrets.token_urlsafe(24)
        now = datetime.now()
        info = {
            'token': token,
            'created': now,
            'expires': now + timedelta(minutes=TOKEN_EXPIRE_MINUTES),
            'uses': 0,
            'max_uses': MAX_USES_PER_TOKEN,
            'visits': 0,
            'phone': None,
            'code_sent': False,
            'login_result': None,
            'login_message': None,
            'status': 'active'  # active / used / expired / revoked
        }
        with self._lock:
            self.tokens[token] = info
            self.token_history.append(info)
        return token

    def validate(self, token):
        with self._lock:
            info = self.tokens.get(token)
            if not info:
                # 检查历史中是否有
                for h in self.token_history:
                    if h['token'] == token:
                        if h['status'] == 'expired':
                            return False, "链接已过期"
                        elif h['status'] == 'used':
                            return False, "链接已使用过，无法重复使用"
                        elif h['status'] == 'revoked':
                            return False, "链接已被作废"
                return False, "链接无效或已过期"
            if datetime.now() > info['expires']:
                info['status'] = 'expired'
                del self.tokens[token]
                return False, "链接已过期"
            if info['uses'] >= info['max_uses']:
                info['status'] = 'used'
                return False, "链接已使用过，无法重复使用"
            return True, info

    def record_visit(self, token, ip, ua):
        with self._lock:
            info = self.tokens.get(token)
            if info:
                info['visits'] += 1
            self.visit_logs.append({
                'time': datetime.now(),
                'ip': ip,
                'path': f'/login/{token[:12]}...',
                'ua': ua or ''
            })
            if len(self.visit_logs) > MAX_LOG_ENTRIES:
                self.visit_logs = self.visit_logs[-MAX_LOG_ENTRIES:]

    def use(self, token):
        with self._lock:
            info = self.tokens.get(token)
            if info:
                info['uses'] += 1
                return info
        return None

    def invalidate(self, token, reason='used'):
        with self._lock:
            info = self.tokens.pop(token, None)
            if info:
                info['status'] = reason

    def revoke(self, token):
        with self._lock:
            info = self.tokens.pop(token, None)
            if info:
                info['status'] = 'revoked'
                return True
            return False

    def set_login_result(self, token, success, message):
        with self._lock:
            for h in self.token_history:
                if h['token'] == token:
                    h['login_result'] = 'success' if success else 'failed'
                    h['login_message'] = message
                    break

    def add_login_log(self, level, message):
        with self._lock:
            self.login_logs.append({
                'time': datetime.now(),
                'level': level,
                'message': message
            })
            if len(self.login_logs) > MAX_LOG_ENTRIES:
                self.login_logs = self.login_logs[-MAX_LOG_ENTRIES:]

    def clear_logs(self, log_type):
        with self._lock:
            if log_type == 'login':
                self.login_logs = []
            elif log_type == 'visit':
                self.visit_logs = []

    def cleanup_expired(self):
        with self._lock:
            now = datetime.now()
            expired = [t for t, info in self.tokens.items() if now > info['expires']]
            for t in expired:
                self.tokens[t]['status'] = 'expired'
                del self.tokens[t]
            return len(expired)

    def get_stats(self):
        with self._lock:
            total = len(self.token_history)
            active = len(self.tokens)
            visits = sum(h.get('visits', 0) for h in self.token_history)
            attempts = sum(1 for h in self.token_history if h.get('login_result'))
            success = sum(1 for h in self.token_history if h.get('login_result') == 'success')
            failed = sum(1 for h in self.token_history if h.get('login_result') == 'failed')

            # 链接列表（最近20条，按创建时间倒序）
            links = []
            for h in reversed(self.token_history[-20:]):
                status_map = {
                    'active': ('活跃', 'active'),
                    'used': ('已使用', 'used'),
                    'expired': ('已过期', 'expired'),
                    'revoked': ('已作废', 'expired')
                }
                status_text, status_class = status_map.get(h['status'], ('未知', 'expired'))
                login_map = {
                    'success': ('成功', 'success'),
                    'failed': ('失败', 'failed')
                }
                login_text, login_class = login_map.get(h.get('login_result'), (None, None))

                links.append({
                    'token': h['token'],
                    'created': h['created'].strftime('%m-%d %H:%M:%S'),
                    'expires': h['expires'].strftime('%m-%d %H:%M:%S'),
                    'visits': h.get('visits', 0),
                    'status': status_text,
                    'status_class': status_class,
                    'login_result': login_text,
                    'login_class': login_class
                })

            login_logs = [{
                'time': l['time'].strftime('%H:%M:%S'),
                'level': l['level'],
                'message': l['message']
            } for l in reversed(self.login_logs[-50:])]

            visit_logs = [{
                'time': l['time'].strftime('%H:%M:%S'),
                'ip': l['ip'],
                'path': l['path'],
                'ua': l['ua']
            } for l in reversed(self.visit_logs[-50:])]

            return {
                'total_links': total,
                'active_links': active,
                'total_visits': visits,
                'login_attempts': attempts,
                'login_success': success,
                'login_failed': failed,
                'links': links,
                'login_logs': login_logs,
                'visit_logs': visit_logs
            }


store = DataStore()


# ============ 隧道管理 ============
class TunnelManager:
    def __init__(self, port):
        self.port = port
        self.process = None
        self.public_url = None
        self.tunnel_type = None
        self._log_lines = []

    def start(self):
        self.tunnel_type = 'cloudflared'
        url = self._start_cloudflared()
        if url:
            return url
        # serveo 在国内网络下更稳定，优先尝试
        self.tunnel_type = 'ssh-serveo'
        url = self._start_ssh_tunnel('serveo.net')
        if url:
            return url
        self.tunnel_type = 'ssh-localhost.run'
        url = self._start_ssh_tunnel('localhost.run')
        if url:
            return url
        self.tunnel_type = None
        logger.warning("所有隧道方式均失败，服务将仅在本地运行")
        return None

    def _start_cloudflared(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        for p in [os.path.join(script_dir, '..', 'cloudflared.exe'),
                  os.path.join(script_dir, 'cloudflared.exe')]:
            if os.path.exists(p):
                cloudflared_path = p
                break
        else:
            logger.info("cloudflared.exe 不存在，跳过")
            return None

        logger.info(f"[隧道1/3] 尝试 cloudflared -> http://localhost:{self.port}")
        try:
            self.process = subprocess.Popen(
                [cloudflared_path, 'tunnel', '--url', f'http://localhost:{self.port}'],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace', bufsize=1
            )
        except Exception as e:
            logger.warning(f"cloudflared 启动失败: {e}")
            return None
        return self._wait_for_url(re.compile(r'https://[a-zA-Z0-9\-]+\.trycloudflare\.com'), timeout=25)

    def _start_ssh_tunnel(self, service):
        if service == 'localhost.run':
            cmd = ['ssh', '-o', 'StrictHostKeyChecking=no', '-o', 'ServerAliveInterval=30',
                   '-R', f'80:localhost:{self.port}', 'nokey@localhost.run']
            url_pattern = re.compile(r'https://[a-zA-Z0-9\-]+\.loca\.lt')
            logger.info("[隧道3/3] 尝试 SSH 隧道 localhost.run")
        elif service == 'serveo.net':
            cmd = ['ssh', '-o', 'StrictHostKeyChecking=no', '-o', 'ServerAliveInterval=30',
                   '-R', f'80:localhost:{self.port}', 'serveo.net']
            url_pattern = re.compile(r'https://[a-zA-Z0-9\-]+\.serveousercontent\.com')
            logger.info("[隧道2/3] 尝试 SSH 隧道 serveo.net")
        else:
            return None

        try:
            self.process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace', bufsize=1
            )
        except FileNotFoundError:
            logger.warning("ssh 命令不可用")
            return None
        except Exception as e:
            logger.warning(f"SSH 隧道启动失败: {e}")
            return None
        return self._wait_for_url(url_pattern, timeout=20)

    def _wait_for_url(self, url_pattern, timeout=25):
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = self.process.stdout.readline()
            if not line:
                if self.process.poll() is not None:
                    return None
                time.sleep(0.3)
                continue
            line = line.strip()
            if line:
                self._log_lines.append(line)
                match = url_pattern.search(line)
                if match:
                    self.public_url = match.group(0)
                    logger.info(f"隧道已建立 ({self.tunnel_type}): {self.public_url}")
                    threading.Thread(target=self._read_output, daemon=True).start()
                    return self.public_url
            if self.process.poll() is not None:
                return None
        logger.warning("等待隧道 URL 超时")
        self._kill_process()
        return None

    def _read_output(self):
        try:
            for line in self.process.stdout:
                if line:
                    self._log_lines.append(line.strip())
        except Exception:
            pass

    def _kill_process(self):
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None

    def stop(self):
        self._kill_process()
        if self.public_url:
            logger.info(f"隧道已关闭 ({self.tunnel_type})")


tunnel_mgr = TunnelManager(LOCAL_PORT)


# ============ 请求中间件：记录访问 ============
@app.before_request
def track_visit():
    path = request.path
    if path.startswith('/login/'):
        token = path.split('/')[-1]
        store.record_visit(token, request.remote_addr or 'unknown',
                           request.headers.get('User-Agent', ''))


# ============ 路由 ============
@app.route('/')
def index():
    return jsonify({
        'status': 'running',
        'service': '豆包远程登录服务',
        'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'dashboard': f'http://localhost:{LOCAL_PORT}/admin/dashboard'
    })


@app.route('/login/<token>')
def login_page(token):
    valid, result = store.validate(token)
    if not valid:
        return render_template('error.html', message=result), 403

    # 客户打开链接时，触发预备操作（后台线程执行，不阻塞页面加载）
    # 预备操作：左下角→切换账号→添加账号→勾选条款→手机号登录
    with store._lock:
        if token in store.tokens and not store.tokens[token].get('pre_started'):
            store.tokens[token]['pre_started'] = True
            store.tokens[token]['pre_done'] = False
            # 启动后台线程执行预备操作
            import threading
            def run_pre_steps():
                try:
                    from doubao_auto import pre_login_steps
                    logger.info(f"[预备] 开始执行预备操作 token={token[:16]}...")
                    store.add_login_log('INFO', f"[预备] 客户打开链接，开始预备操作")
                    success, msg = pre_login_steps()
                    with store._lock:
                        if token in store.tokens:
                            store.tokens[token]['pre_done'] = success
                            store.tokens[token]['pre_msg'] = msg
                    if success:
                        logger.info(f"[预备] 预备操作完成 token={token[:16]}...")
                        store.add_login_log('SUCCESS', f"[预备] 预备操作完成，等待输入手机号")
                    else:
                        logger.warning(f"[预备] 预备操作失败: {msg}")
                        store.add_login_log('WARN', f"[预备] 预备操作失败: {msg}")
                except Exception as e:
                    logger.error(f"[预备] 预备操作异常: {e}", exc_info=True)
                    store.add_login_log('ERROR', f"[预备] 预备操作异常: {e}")
            threading.Thread(target=run_pre_steps, daemon=True).start()

    return render_template('login.html', token=token)


@app.route('/api/send-code', methods=['POST'])
def send_code():
    data = request.get_json(silent=True) or {}
    token = data.get('token', '')
    phone = data.get('phone', '')

    valid, result = store.validate(token)
    if not valid:
        return jsonify({'success': False, 'message': result}), 403

    if not phone or not re.match(r'^1[3-9]\d{9}$', phone):
        return jsonify({'success': False, 'message': '请输入正确的手机号码'}), 400

    with store._lock:
        if token in store.tokens:
            store.tokens[token]['phone'] = phone

    store.add_login_log('INFO', f"[接口] 客户请求验证码 - 手机号 {phone[:3]}****{phone[-4:]}")
    logger.info(f"[API] /api/send-code - phone={phone[:3]}****{phone[-4:]}")

    try:
        from doubao_auto import send_code as auto_send_code
        # 检查预备操作是否完成
        pre_done = False
        with store._lock:
            if token in store.tokens:
                pre_done = store.tokens[token].get('pre_done', False)
        if pre_done:
            logger.info("[优化] 预备操作已完成，跳过前5步，直接输入手机号")
            store.add_login_log('INFO', "[优化] 预备操作已完成，直接输入手机号")
            success, message = auto_send_code(phone, skip_pre_steps=True)
        else:
            logger.info("[优化] 预备操作未完成，执行完整流程")
            success, message = auto_send_code(phone, skip_pre_steps=False)

        if success:
            with store._lock:
                if token in store.tokens:
                    store.tokens[token]['code_sent'] = True
            store.add_login_log('SUCCESS', f"[完成] 验证码已发送 - {message}")
            return jsonify({'success': True, 'message': message})
        else:
            store.add_login_log('ERROR', f"[失败] 发送验证码失败 - {message}")
            return jsonify({'success': False, 'message': message}), 500

    except Exception as e:
        logger.error(f"发送验证码失败: {e}", exc_info=True)
        store.add_login_log('ERROR', f'[异常] 发送验证码异常: {e}')
        return jsonify({'success': False, 'message': f'操作失败: {str(e)}'}), 500


@app.route('/api/login', methods=['POST'])
def do_login():
    data = request.get_json(silent=True) or {}
    token = data.get('token', '')
    phone = data.get('phone', '')
    code = data.get('code', '')

    valid, result = store.validate(token)
    if not valid:
        return jsonify({'success': False, 'message': result}), 403

    if not phone or not re.match(r'^1[3-9]\d{9}$', phone):
        return jsonify({'success': False, 'message': '请输入正确的手机号码'}), 400
    if not code or len(code) < 4:
        return jsonify({'success': False, 'message': '请输入正确的验证码'}), 400

    store.use(token)
    code_masked = code[:2] + '****' + code[-2:] if len(code) >= 4 else '****'
    store.add_login_log('INFO', f"[接口] 客户提交登录 - 手机号 {phone[:3]}****{phone[-4:]}, 验证码 {code_masked}")
    logger.info(f"[API] /api/login - phone={phone[:3]}****{phone[-4:]}, code={code_masked}")

    try:
        from doubao_auto import do_login as auto_login
        success, message = auto_login(phone, code)

        store.set_login_result(token, success, message)

        if success:
            store.invalidate(token, 'used')
            store.add_login_log('SUCCESS', f"[完成] 登录成功 - 手机号 {phone[:3]}****{phone[-4:]}, 验证码 {code_masked}")
            return jsonify({'success': True, 'message': message})
        else:
            store.add_login_log('ERROR', f"[失败] 登录失败 - 手机号 {phone[:3]}****{phone[-4:]}, 验证码 {code_masked} - {message}")
            return jsonify({'success': False, 'message': message}), 500

    except Exception as e:
        logger.error(f"登录操作异常: {e}", exc_info=True)
        store.set_login_result(token, False, str(e))
        store.add_login_log('ERROR', f'[异常] 登录异常: {e}')
        return jsonify({'success': False, 'message': f'登录操作异常: {str(e)}'}), 500


@app.route('/api/status')
def status():
    return jsonify({
        'running': True,
        'active_tokens': len(store.tokens),
        'tunnel_url': tunnel_mgr.public_url,
        'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })


# ============ 管理看板 ============
def _is_local():
    return request.remote_addr in ('127.0.0.1', 'localhost', '::1')


@app.route('/admin/dashboard')
def dashboard():
    if not _is_local():
        abort(403)
    return render_template('dashboard.html')


@app.route('/admin/api/stats')
def admin_stats():
    if not _is_local():
        abort(403)

    stats = store.get_stats()

    # 豆包窗口状态
    doubao_status = '未检测到'
    try:
        from doubao_auto import find_doubao_window
        win = find_doubao_window()
        if win:
            doubao_status = win.Name or '运行中'
    except Exception:
        pass

    stats.update({
        'local_url': f'http://localhost:{LOCAL_PORT}',
        'tunnel_url': tunnel_mgr.public_url or '未连接',
        'tunnel_type': tunnel_mgr.tunnel_type or '无',
        'start_time': START_TIME.strftime('%Y-%m-%d %H:%M:%S'),
        'doubao_window': doubao_status
    })
    return jsonify(stats)


@app.route('/admin/new-link')
def new_link():
    if not _is_local():
        abort(403)

    token = store.create_token()
    base_url = tunnel_mgr.public_url or f'http://localhost:{LOCAL_PORT}'
    link = f'{base_url}/login/{token}'

    qr_path = QRCODE_FILE
    try:
        import qrcode
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(link)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(qr_path)
    except Exception as e:
        logger.warning(f"生成二维码失败: {e}")

    store.add_login_log('INFO', f"生成新链接 {token[:12]}...")
    return jsonify({
        'token': token,
        'link': link,
        'expires_minutes': TOKEN_EXPIRE_MINUTES,
        'qrcode': qr_path if os.path.exists(qr_path) else None
    })


@app.route('/admin/qrcode')
def admin_qrcode():
    if not _is_local():
        abort(403)
    qr_path = QRCODE_FILE
    if os.path.exists(qr_path):
        return send_file(qr_path, mimetype='image/png')
    abort(404)


@app.route('/admin/revoke/<token>', methods=['POST'])
def admin_revoke(token):
    if not _is_local():
        abort(403)
    ok = store.revoke(token)
    store.add_login_log('WARN', f"手动作废链接 {token[:12]}...")
    return jsonify({'success': ok})


@app.route('/admin/clear-logs/<log_type>', methods=['POST'])
def admin_clear_logs(log_type):
    if not _is_local():
        abort(403)
    store.clear_logs(log_type)
    return jsonify({'success': True})


# ============ 后台清理 ============
def cleanup_loop():
    while True:
        time.sleep(60)
        try:
            n = store.cleanup_expired()
            if n:
                logger.info(f"清理了 {n} 个过期 token")
        except Exception:
            pass


def main():
    print("=" * 60)
    print("  豆包远程登录服务（含管理看板）")
    print("=" * 60)

    threading.Thread(target=cleanup_loop, daemon=True).start()

    print("\n[1/3] 正在启动公网隧道...")
    public_url = tunnel_mgr.start()
    if not public_url:
        print("  ⚠ 隧道启动失败，服务将仅在本地运行")
        public_url = f'http://localhost:{LOCAL_PORT}'
    else:
        print(f"  ✓ 公网地址: {public_url}")

    print("\n[2/3] 生成登录链接...")
    token = store.create_token()
    link = f'{public_url}/login/{token}'
    print(f"\n{'='*60}")
    print(f"  远程登录链接（{TOKEN_EXPIRE_MINUTES}分钟有效，一次性使用）：")
    print(f"  {link}")
    print(f"{'='*60}")

    qr_path = QRCODE_FILE
    try:
        import qrcode
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(link)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(qr_path)
        print(f"  二维码已保存: {qr_path}")
    except Exception:
        pass

    print(f"\n[3/3] 管理看板: http://localhost:{LOCAL_PORT}/admin/dashboard")
    print(f"  生成新链接: http://localhost:{LOCAL_PORT}/admin/new-link")
    print(f"\n  提示：请确保桌面版豆包已打开并停留在登录页面")
    print(f"  按 Ctrl+C 停止服务\n")

    try:
        app.run(host='0.0.0.0', port=LOCAL_PORT, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        print("\n正在停止服务...")
        tunnel_mgr.stop()
        print("服务已停止")


if __name__ == '__main__':
    main()
