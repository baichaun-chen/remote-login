# -*- coding: utf-8 -*-
"""
豆包远程登录 - 一键启动器（双标签页：首页 + 看板）
"""

import os
import sys
import time
import threading
import queue
import logging
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

LOCAL_PORT = 58231
DARK_BG = '#0f172a'
CARD_BG = '#1e293b'
BORDER = '#334155'
TEXT_PRIMARY = '#f1f5f9'
TEXT_SECONDARY = '#94a3b8'
TEXT_MUTED = '#64748b'
ACCENT_BLUE = '#3b82f6'
ACCENT_GREEN = '#22c55e'
ACCENT_RED = '#ef4444'
ACCENT_YELLOW = '#eab308'
ACCENT_PURPLE = '#a855f7'
ACCENT_CYAN = '#06b6d4'


class QueueLogHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue
    def emit(self, record):
        try:
            self.log_queue.put(self.format(record))
        except Exception:
            pass


class RemoteLoginLauncher:
    def __init__(self, root):
        self.root = root
        self.service_running = False
        self.current_link = None
        self.tunnel_url = None
        self.log_queue = queue.Queue()
        self.qr_photo = None
        self._app_module = None
        self._start_time = None
        self._dashboard_refresh_id = None

        self._setup_logging()
        self._build_ui()
        self._process_log_queue()

        self.root.bind('<F5>', lambda e: self._start_service())
        self.root.bind('<F6>', lambda e: self._stop_service())

    def _setup_logging(self):
        handler = QueueLogHandler(self.log_queue)
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter('%(message)s'))
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)

    def _build_ui(self):
        # 主容器
        self.main_container = tk.Frame(self.root, bg=DARK_BG)
        self.main_container.pack(fill='both', expand=True)

        # 顶部标题栏
        header = tk.Frame(self.main_container, bg=DARK_BG)
        header.pack(fill='x', padx=16, pady=(12, 8))
        tk.Label(header, text="🤖 豆包远程登录", bg=DARK_BG, fg=TEXT_PRIMARY,
                 font=('Microsoft YaHei', 15, 'bold')).pack(side='left')
        self.status_frame = tk.Frame(header, bg=DARK_BG)
        self.status_frame.pack(side='right')
        self.status_dot = tk.Canvas(self.status_frame, width=12, height=12, bg=DARK_BG, highlightthickness=0)
        self.status_dot.pack(side='left', padx=(0, 5))
        self.status_dot.create_oval(1, 1, 11, 11, fill='#64748b', outline='')
        self.status_label = tk.Label(self.status_frame, text="未启动", bg=DARK_BG, fg=TEXT_SECONDARY,
                                     font=('Microsoft YaHei', 9))
        self.status_label.pack(side='left')

        # 标签页
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TNotebook', background=DARK_BG, borderwidth=0)
        style.configure('TNotebook.Tab', background=CARD_BG, foreground=TEXT_SECONDARY,
                        padding=[20, 8], font=('Microsoft YaHei', 10))
        style.map('TNotebook.Tab',
                  background=[('selected', ACCENT_BLUE)],
                  foreground=[('selected', 'white')])

        self.notebook = ttk.Notebook(self.main_container)
        self.notebook.pack(fill='both', expand=True, padx=16, pady=(0, 12))

        self._build_home_tab()
        self._build_dashboard_tab()

        # 底部提示
        tk.Label(self.main_container, text="F5 启动服务  |  F6 停止退出  |  确保豆包停留在登录页面",
                 bg=DARK_BG, fg=TEXT_MUTED, font=('Microsoft YaHei', 8)).pack(pady=(0, 8))

    # ============ 首页标签页 ============
    def _build_home_tab(self):
        home = tk.Frame(self.notebook, bg=DARK_BG)
        self.notebook.add(home, text="  🏠 远程登录  ")

        # 控制按钮
        ctrl = tk.Frame(home, bg=DARK_BG)
        ctrl.pack(fill='x', padx=12, pady=(12, 10))
        self.start_btn = tk.Button(ctrl, text="▶  启动服务", command=self._start_service,
                                   bg='#166534', fg='#4ade80', activebackground='#15803d',
                                   activeforeground='white', relief='flat', padx=24, pady=10,
                                   font=('Microsoft YaHei', 11, 'bold'), cursor='hand2')
        self.start_btn.pack(side='left', fill='x', expand=True, padx=(0, 6))
        self.stop_btn = tk.Button(ctrl, text="■  停止并退出", command=self._stop_service,
                                  bg='#7f1d1d', fg='#f87171', activebackground='#991b1b',
                                  activeforeground='white', relief='flat', padx=24, pady=10,
                                  font=('Microsoft YaHei', 11, 'bold'), cursor='hand2', state='disabled')
        self.stop_btn.pack(side='left', fill='x', expand=True, padx=(6, 0))

        # 链接卡片
        link_card = tk.Frame(home, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        link_card.pack(fill='x', padx=12, pady=(0, 10))
        tk.Label(link_card, text="🔗 远程登录链接", bg=CARD_BG, fg=TEXT_SECONDARY,
                 font=('Microsoft YaHei', 9)).pack(anchor='w', padx=14, pady=(10, 0))
        self.link_var = tk.StringVar(value="等待启动服务后生成...")
        link_entry = tk.Entry(link_card, textvariable=self.link_var, readonlybackground='#0f172a',
                              fg='#60a5fa', font=('Consolas', 9), relief='flat')
        link_entry.pack(fill='x', padx=14, pady=(6, 10))
        link_entry.configure(state='readonly')

        btn_row = tk.Frame(link_card, bg=CARD_BG)
        btn_row.pack(fill='x', padx=14, pady=(0, 12))
        self.copy_btn = tk.Button(btn_row, text="📋 复制链接", command=self._copy_link,
                                  bg='#1e3a5f', fg='#60a5fa', activebackground='#1e40af',
                                  activeforeground='white', relief='flat', padx=12, pady=5,
                                  font=('Microsoft YaHei', 9), cursor='hand2', state='disabled')
        self.copy_btn.pack(side='left')
        self.newlink_btn = tk.Button(btn_row, text="🔄 生成新链接", command=self._gen_new_link,
                                     bg='#1e3a5f', fg='#60a5fa', activebackground='#1e40af',
                                     activeforeground='white', relief='flat', padx=12, pady=5,
                                     font=('Microsoft YaHei', 9), cursor='hand2', state='disabled')
        self.newlink_btn.pack(side='left', padx=(8, 0))
        self.dashboard_btn = tk.Button(btn_row, text="📊 打开看板网页", command=self._open_dashboard,
                                       bg='#312e81', fg='#a5b4fc', activebackground='#3730a3',
                                       activeforeground='white', relief='flat', padx=12, pady=5,
                                       font=('Microsoft YaHei', 9), cursor='hand2', state='disabled')
        self.dashboard_btn.pack(side='right')

        # 二维码 + 服务信息
        info_row = tk.Frame(home, bg=DARK_BG)
        info_row.pack(fill='x', padx=12, pady=(0, 10))

        qr_card = tk.Frame(info_row, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        qr_card.pack(side='left', padx=(0, 8))
        qr_card.configure(padx=14, pady=10)
        tk.Label(qr_card, text="扫码访问", bg=CARD_BG, fg=TEXT_SECONDARY,
                 font=('Microsoft YaHei', 8)).pack()
        self.qr_label = tk.Label(qr_card, bg=CARD_BG, text="📱\n启动后显示",
                                 font=('Microsoft YaHei', 16), width=9, height=4)
        self.qr_label.pack(pady=(6, 0))

        info_card = tk.Frame(info_row, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        info_card.pack(side='left', fill='both', expand=True)
        info_card.configure(padx=14, pady=10)
        self.info_tunnel = self._info_row(info_card, "公网隧道", "未连接")
        self.info_port = self._info_row(info_card, "本地端口", str(LOCAL_PORT))
        self.info_uptime = self._info_row(info_card, "运行时长", "--:--:--")
        self.info_doubao = self._info_row(info_card, "豆包窗口", "未检测")

        # 日志
        log_card = tk.Frame(home, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        log_card.pack(fill='both', expand=True, padx=12, pady=(0, 12))
        tk.Label(log_card, text="📋 运行日志", bg=CARD_BG, fg=TEXT_SECONDARY,
                 font=('Microsoft YaHei', 9)).pack(anchor='w', padx=12, pady=(8, 0))
        self.log_text = tk.Text(log_card, bg='#0f172a', fg=TEXT_SECONDARY, font=('Consolas', 8),
                                relief='flat', height=6, wrap='word')
        self.log_text.pack(fill='both', expand=True, padx=12, pady=(6, 10))
        self.log_text.configure(state='disabled')

    def _info_row(self, parent, label, value):
        row = tk.Frame(parent, bg=CARD_BG)
        row.pack(fill='x', pady=2)
        tk.Label(row, text=label, bg=CARD_BG, fg=TEXT_MUTED,
                 font=('Microsoft YaHei', 9), width=8, anchor='w').pack(side='left')
        var = tk.StringVar(value=value)
        tk.Label(row, textvariable=var, bg=CARD_BG, fg=TEXT_PRIMARY,
                 font=('Consolas', 9), anchor='w').pack(side='left', fill='x', expand=True)
        return var

    # ============ 看板标签页 ============
    def _build_dashboard_tab(self):
        dash = tk.Frame(self.notebook, bg=DARK_BG)
        self.notebook.add(dash, text="  📊 数据看板  ")
        self.notebook.bind('<<NotebookTabChanged>>', self._on_tab_changed)

        # 统计卡片
        stats_frame = tk.Frame(dash, bg=DARK_BG)
        stats_frame.pack(fill='x', padx=12, pady=(12, 10))

        self.stat_cards = {}
        stats_config = [
            ('total', '总链接数', ACCENT_BLUE),
            ('success', '登录成功', ACCENT_GREEN),
            ('failed', '登录失败', ACCENT_RED),
            ('rate', '成功率', ACCENT_PURPLE),
        ]
        for i, (key, label, color) in enumerate(stats_config):
            card = tk.Frame(stats_frame, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
            card.pack(side='left', fill='x', expand=True, padx=(0 if i == 0 else 6, 0 if i == 3 else 6))
            card.configure(padx=10, pady=10)
            tk.Label(card, text=label, bg=CARD_BG, fg=TEXT_MUTED,
                     font=('Microsoft YaHei', 8)).pack(anchor='w')
            val_var = tk.StringVar(value='0')
            tk.Label(card, textvariable=val_var, bg=CARD_BG, fg=color,
                     font=('Microsoft YaHei', 18, 'bold')).pack(anchor='w', pady=(4, 0))
            self.stat_cards[key] = val_var

        # 最近记录
        record_card = tk.Frame(dash, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        record_card.pack(fill='both', expand=True, padx=12, pady=(0, 10))
        header = tk.Frame(record_card, bg=CARD_BG)
        header.pack(fill='x', padx=12, pady=(10, 0))
        tk.Label(header, text="📜 最近登录记录", bg=CARD_BG, fg=TEXT_SECONDARY,
                 font=('Microsoft YaHei', 10, 'bold')).pack(side='left')
        self.refresh_btn = tk.Button(header, text="🔄 刷新", command=self._refresh_dashboard,
                                     bg='#1e3a5f', fg='#60a5fa', activebackground='#1e40af',
                                     activeforeground='white', relief='flat', padx=10, pady=3,
                                     font=('Microsoft YaHei', 8), cursor='hand2')
        self.refresh_btn.pack(side='right')

        # 记录表头
        table_header = tk.Frame(record_card, bg='#0f172a')
        table_header.pack(fill='x', padx=12, pady=(8, 0))
        for text, w in [('时间', 18), ('手机号', 16), ('状态', 10), ('详情', 40)]:
            tk.Label(table_header, text=text, bg='#0f172a', fg=TEXT_MUTED,
                     font=('Microsoft YaHei', 8, 'bold'), width=w, anchor='w').pack(side='left', padx=(8, 0))

        # 记录列表
        self.record_frame = tk.Frame(record_card, bg=CARD_BG)
        self.record_frame.pack(fill='both', expand=True, padx=12, pady=(4, 10))
        self._show_empty_records()

        # 改进建议
        advice_card = tk.Frame(dash, bg='#1a1a2e', highlightbackground='#4c1d95', highlightthickness=1)
        advice_card.pack(fill='x', padx=12, pady=(0, 12))
        tk.Label(advice_card, text="💡 智能改进建议", bg='#1a1a2e', fg='#c4b5fd',
                 font=('Microsoft YaHei', 10, 'bold')).pack(anchor='w', padx=12, pady=(10, 0))
        self.advice_text = tk.Text(advice_card, bg='#1a1a2e', fg='#c4b5fd', font=('Microsoft YaHei', 9),
                                   relief='flat', height=4, wrap='word')
        self.advice_text.pack(fill='x', padx=12, pady=(6, 10))
        self.advice_text.configure(state='disabled')
        self._set_advice("启动服务后，这里会根据登录数据给出智能建议。")

    def _show_empty_records(self):
        for w in self.record_frame.winfo_children():
            w.destroy()
        tk.Label(self.record_frame, text="暂无登录记录\n启动服务后这里会显示最近的登录情况",
                 bg=CARD_BG, fg=TEXT_MUTED, font=('Microsoft YaHei', 9)).pack(pady=20)

    def _set_advice(self, text):
        self.advice_text.configure(state='normal')
        self.advice_text.delete('1.0', 'end')
        self.advice_text.insert('1.0', text)
        self.advice_text.configure(state='disabled')

    def _on_tab_changed(self, event):
        if self.notebook.index(self.notebook.select()) == 1:  # 看板页
            self._refresh_dashboard()

    def _refresh_dashboard(self):
        if not self._app_module:
            self.stat_cards['total'].set('0')
            self.stat_cards['success'].set('0')
            self.stat_cards['failed'].set('0')
            self.stat_cards['rate'].set('--')
            self._show_empty_records()
            self._set_advice("服务未启动。点击首页的「启动服务」按钮后，这里会显示统计数据。")
            return

        try:
            stats = self._app_module.store.get_stats()
            total = stats['total_links']
            success = stats['login_success']
            failed = stats['login_failed']
            attempts = stats['login_attempts']
            rate = f"{int(success/attempts*100)}%" if attempts > 0 else '--'

            self.stat_cards['total'].set(str(total))
            self.stat_cards['success'].set(str(success))
            self.stat_cards['failed'].set(str(failed))
            self.stat_cards['rate'].set(rate)

            # 渲染记录
            for w in self.record_frame.winfo_children():
                w.destroy()

            logs = stats.get('login_logs', [])
            if not logs:
                self._show_empty_records()
            else:
                for log in logs[:10]:
                    row = tk.Frame(self.record_frame, bg=CARD_BG)
                    row.pack(fill='x', pady=1)
                    level_colors = {'SUCCESS': ACCENT_GREEN, 'ERROR': ACCENT_RED,
                                    'WARN': ACCENT_YELLOW, 'INFO': TEXT_SECONDARY}
                    color = level_colors.get(log['level'], TEXT_SECONDARY)
                    tk.Label(row, text=log['time'], bg=CARD_BG, fg=TEXT_MUTED,
                             font=('Consolas', 8), width=18, anchor='w').pack(side='left', padx=(8, 0))
                    tk.Label(row, text=log['level'], bg=CARD_BG, fg=color,
                             font=('Microsoft YaHei', 8, 'bold'), width=10, anchor='w').pack(side='left')
                    msg = log['message']
                    if len(msg) > 45:
                        msg = msg[:45] + '...'
                    tk.Label(row, text=msg, bg=CARD_BG, fg=TEXT_PRIMARY,
                             font=('Microsoft YaHei', 8), anchor='w').pack(side='left', fill='x', expand=True)

            # 生成建议
            self._generate_advice(stats)

        except Exception as e:
            self._set_advice(f"获取数据时出错: {e}")

    def _generate_advice(self, stats):
        suggestions = []
        success = stats['login_success']
        failed = stats['login_failed']
        attempts = stats['login_attempts']
        active = stats['active_links']
        visits = stats['total_visits']

        if attempts == 0:
            suggestions.append("• 还没有登录尝试。分享链接给对方，让对方输入手机号和验证码完成登录。")
        else:
            rate = success / attempts * 100 if attempts > 0 else 0
            if rate < 50:
                suggestions.append(f"• 登录成功率仅 {int(rate)}%，建议检查：1)豆包是否停留在登录页面 2)是否有图形验证需要手动完成 3)手机号输入是否正确")
            elif rate >= 90:
                suggestions.append(f"• 登录成功率 {int(rate)}%，表现优秀！继续保持。")
            else:
                suggestions.append(f"• 登录成功率 {int(rate)}%，偶有失败属正常现象。失败时可查看下方日志了解原因。")

        if failed > 0:
            suggestions.append(f"• 共有 {failed} 次失败记录，常见原因：豆包不在登录页、验证码错误、网络波动。")

        if active > 0 and visits > 0 and attempts == 0:
            suggestions.append(f"• 有 {active} 个活跃链接被访问 {visits} 次但尚未登录，建议提醒对方完成登录操作。")

        if self.tunnel_url and 'serveo' in self.tunnel_url:
            suggestions.append("• 当前使用 serveo.net 隧道，国内网络偶尔不稳定。如频繁断开可重试启动。")

        if not suggestions:
            suggestions.append("• 一切运行正常，暂无特别建议。")

        self._set_advice('\n'.join(suggestions))

    # ============ 通用方法 ============
    def _safe_ui(self, callback):
        try:
            self.root.after(0, callback)
        except Exception:
            try:
                callback()
            except Exception:
                pass

    def _log(self, msg):
        timestamp = datetime.now().strftime('%H:%M:%S')
        self.log_queue.put(f"[{timestamp}] {msg}")

    def _process_log_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_text.configure(state='normal')
                self.log_text.insert('end', msg + '\n')
                self.log_text.see('end')
                self.log_text.configure(state='disabled')
        except queue.Empty:
            pass
        self.root.after(100, self._process_log_queue)

    def _set_status(self, color, text):
        self.status_dot.delete('all')
        self.status_dot.create_oval(1, 1, 11, 11, fill=color, outline='')
        self.status_label.configure(text=text)

    def _start_service(self):
        if self.service_running:
            return
        self._set_status(ACCENT_YELLOW, '启动中')
        self.start_btn.configure(state='disabled', text='⏳ 启动中...')
        self._log("正在启动服务...")
        threading.Thread(target=self._do_start, daemon=True).start()

    def _do_start(self):
        try:
            import app as app_module
            self._app_module = app_module

            self._log("正在建立公网隧道...")
            public_url = app_module.tunnel_mgr.start()

            if not public_url:
                self._log("⚠ 隧道启动失败，仅本地可用")
                public_url = f'http://localhost:{LOCAL_PORT}'
            else:
                self._log(f"✓ 隧道已建立: {public_url}")
                self.tunnel_url = public_url
                self._safe_ui(lambda: self.info_tunnel.set(public_url))

            token = app_module.store.create_token()
            link = f'{public_url}/login/{token}'
            self.current_link = link
            self._safe_ui(lambda: self.link_var.set(link))
            self._log("✓ 登录链接已生成")

            self._generate_qrcode(link)
            threading.Thread(target=app_module.cleanup_loop, daemon=True).start()
            self._safe_ui(self._on_service_started)

            self._log("服务已启动，等待远程连接...")
            app_module.app.run(host='0.0.0.0', port=LOCAL_PORT, debug=False, use_reloader=False)

        except Exception as e:
            import traceback
            self._log(f"✗ 服务启动失败: {e}")
            self._log(traceback.format_exc())
            self._safe_ui(lambda: self._set_status(ACCENT_RED, '启动失败'))
            self._safe_ui(lambda: self.start_btn.configure(state='normal', text='▶  启动服务'))

    def _on_service_started(self):
        self.service_running = True
        self._set_status(ACCENT_GREEN, '运行中')
        self.start_btn.configure(state='disabled')
        self.stop_btn.configure(state='normal')
        self.copy_btn.configure(state='normal')
        self.newlink_btn.configure(state='normal')
        self.dashboard_btn.configure(state='normal')
        self._start_time = time.time()
        self._start_uptime_timer()
        self._log("✓ 服务启动完成，可以分享链接了")
        self._refresh_dashboard()

    def _stop_service(self):
        if messagebox.askyesno("确认退出", "确定要停止服务并退出程序吗？"):
            self._log("正在退出...")
            try:
                if self._app_module:
                    self._app_module.tunnel_mgr.stop()
            except Exception:
                pass
            self.root.after(300, lambda: os._exit(0))

    def _copy_link(self):
        if not self.current_link:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self.current_link)
        self._log("链接已复制到剪贴板")
        old = self.copy_btn.cget('text')
        self.copy_btn.configure(text='✓ 已复制')
        self.root.after(1500, lambda: self.copy_btn.configure(text=old))

    def _gen_new_link(self):
        if not self.service_running or not self._app_module:
            return
        try:
            token = self._app_module.store.create_token()
            base = self.tunnel_url or f'http://localhost:{LOCAL_PORT}'
            link = f'{base}/login/{token}'
            self.current_link = link
            self.link_var.set(link)
            self._generate_qrcode(link)
            self._log("✓ 新链接已生成")
            self._refresh_dashboard()
        except Exception as e:
            self._log(f"生成新链接失败: {e}")

    def _open_dashboard(self):
        import webbrowser
        webbrowser.open(f'http://localhost:{LOCAL_PORT}/admin/dashboard')
        self._log("已打开管理看板")

    def _generate_qrcode(self, link):
        try:
            import qrcode
            from PIL import Image, ImageTk
            qr = qrcode.QRCode(version=1, box_size=4, border=2)
            qr.add_data(link)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            img = img.resize((120, 120), Image.NEAREST)
            self.qr_photo = ImageTk.PhotoImage(img)
            self._safe_ui(lambda: self.qr_label.configure(image=self.qr_photo, text=''))
        except Exception as e:
            self._log(f"二维码生成失败: {e}")

    def _start_uptime_timer(self):
        def update():
            if self.service_running and self._start_time:
                elapsed = int(time.time() - self._start_time)
                h = elapsed // 3600
                m = (elapsed % 3600) // 60
                s = elapsed % 60
                self.info_uptime.set(f"{h:02d}:{m:02d}:{s:02d}")
                self.root.after(1000, update)
        update()

        def check_doubao():
            if self.service_running:
                try:
                    from doubao_auto import find_doubao_window
                    win = find_doubao_window()
                    name = win.Name if win else '未检测到'
                    if len(name) > 16:
                        name = name[:16] + '..'
                    self.info_doubao.set(name)
                except Exception:
                    pass
                self.root.after(5000, check_doubao)
        check_doubao()

    def on_close(self):
        if self.service_running:
            if messagebox.askyesno("确认退出", "服务正在运行，确定要退出吗？"):
                try:
                    if self._app_module:
                        self._app_module.tunnel_mgr.stop()
                except Exception:
                    pass
                os._exit(0)
        else:
            self.root.destroy()


def main():
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    root = tk.Tk()
    root.title("豆包远程登录 · 一键启动器")
    root.geometry("720x680+100+80")
    root.minsize(720, 680)
    root.configure(bg=DARK_BG)
    root.update()

    app = RemoteLoginLauncher(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)

    root.deiconify()
    root.lift()
    root.focus_force()
    root.update()

    root.mainloop()


if __name__ == '__main__':
    main()
