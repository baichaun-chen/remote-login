# -*- coding: utf-8 -*-
"""
桌面版豆包远程登录自动化模块（图像识别版）
使用 OpenCV 多尺度模板匹配精确定位每个按钮
"""

import os
import sys
import time
import logging

logger = logging.getLogger(__name__)

# 资源目录
if getattr(sys, 'frozen', False):
    ASSETS_DIR = os.path.join(sys._MEIPASS, 'assets')
else:
    ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')

try:
    import uiautomation as auto
    HAS_UIAUTO = True
except ImportError:
    HAS_UIAUTO = False

try:
    import pyautogui
    pyautogui.FAILSAFE = False
    HAS_PYAUTOGUI = True
except ImportError:
    HAS_PYAUTOGUI = False

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False
    logger.warning("OpenCV 未安装，图像识别不可用")


# ========== 窗口管理 ==========

def find_doubao_window():
    """查找桌面豆包主窗口"""
    if not HAS_UIAUTO:
        return None
    EXCLUDE_KEYWORDS = ["一键启动器", "DoubaoRemoteLogin", "图片查看器", "图片查看"]
    EXCLUDE_CLASSES = ["TkTopLevel"]
    root = auto.GetRootControl()

    for win in root.GetChildren():
        try:
            name = (win.Name or "").strip()
            cls = win.ClassName or ""
            if not name:
                continue
            if any(kw in name for kw in EXCLUDE_KEYWORDS):
                continue
            if cls in EXCLUDE_CLASSES:
                continue
            r = win.BoundingRectangle
            if r.width() < 200 or r.height() < 200:
                continue
            if name == "豆包" or name.endswith(" - 豆包") or name.endswith("-豆包"):
                logger.info(f"找到豆包窗口: name='{name}', class='{cls}', size={r.width()}x{r.height()}")
                return win
        except Exception:
            continue

    for win in root.GetChildren():
        try:
            name = (win.Name or "").strip()
            cls = win.ClassName or ""
            if any(kw in name for kw in EXCLUDE_KEYWORDS):
                continue
            if cls in EXCLUDE_CLASSES:
                continue
            r = win.BoundingRectangle
            if r.width() < 200 or r.height() < 200:
                continue
            if "豆包" in name and "Chrome_WidgetWin" in cls:
                logger.info(f"找到豆包窗口(宽松): name='{name}', class='{cls}'")
                return win
        except Exception:
            continue
    return None


def bring_doubao_to_foreground():
    """将豆包窗口置于前台"""
    win = find_doubao_window()
    if not win:
        logger.error("未找到豆包窗口")
        return False
    try:
        win.SetTopmost(True)
        time.sleep(0.3)
        win.SetTopmost(False)
        win.SetFocus()
        time.sleep(0.6)
        return True
    except Exception as e:
        logger.warning(f"SetTopmost 失败: {e}")
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        EnumWindows = user32.EnumWindows
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        GetWindowText = user32.GetWindowTextW
        GetWindowTextLength = user32.GetWindowTextLengthW
        IsWindowVisible = user32.IsWindowVisible
        SetForegroundWindow = user32.SetForegroundWindow
        ShowWindow = user32.ShowWindow
        found = []
        def cb(hwnd, lp):
            if IsWindowVisible(hwnd):
                length = GetWindowTextLength(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    GetWindowText(hwnd, buf, length + 1)
                    if buf.value.strip().endswith(" - 豆包") or buf.value.strip() == "豆包":
                        found.append(hwnd)
            return True
        EnumWindows(EnumWindowsProc(cb), 0)
        if found:
            ShowWindow(found[0], 9)
            SetForegroundWindow(found[0])
            time.sleep(0.8)
            return True
    except Exception as e:
        logger.warning(f"Win32 激活失败: {e}")
    return False


def get_window_rect():
    win = find_doubao_window()
    if win:
        r = win.BoundingRectangle
        return r.left, r.top, r.width(), r.height()
    return None


# ========== 多尺度图像识别 ==========

def find_template_on_screen(template_name, threshold=0.7, region=None):
    """
    在屏幕上多尺度查找模板图片
    返回 (center_x, center_y, scale) 或 None
    """
    if not HAS_CV2 or not HAS_PYAUTOGUI:
        return None

    template_path = os.path.join(ASSETS_DIR, template_name)
    if not os.path.exists(template_path):
        logger.warning(f"模板不存在: {template_path}")
        return None

    template = cv2.imread(template_path)
    if template is None:
        logger.warning(f"无法读取模板: {template_path}")
        return None

    # 截取屏幕
    if region:
        screen = pyautogui.screenshot(region=region)
    else:
        screen = pyautogui.screenshot()
    screen_cv = cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2BGR)

    best_val = 0
    best_loc = None
    best_scale = 1.0

    # 多尺度匹配（高DPI截图通常需要 0.4-0.6 缩放）
    for scale in [0.4, 0.45, 0.5, 0.55, 0.6, 0.67, 0.75, 0.8, 0.9, 1.0]:
        try:
            scaled = cv2.resize(template, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            if scaled.shape[0] > screen_cv.shape[0] or scaled.shape[1] > screen_cv.shape[1]:
                continue
            result = cv2.matchTemplate(screen_cv, scaled, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if max_val > best_val:
                best_val = max_val
                best_loc = max_loc
                best_scale = scale
        except Exception:
            continue

    logger.info(f"模板 '{template_name}': 最佳匹配 {best_val:.3f} (scale={best_scale})")

    if best_val >= threshold and best_loc:
        h, w = template.shape[:2]
        h = int(h * best_scale)
        w = int(w * best_scale)
        center_x = best_loc[0] + w // 2
        center_y = best_loc[1] + h // 2
        if region:
            center_x += region[0]
            center_y += region[1]
        return (center_x, center_y, best_scale)

    return None


def click_template(template_name, threshold=0.7, retries=3, interval=0.8, offset=(0, 0), region=None):
    """查找并点击模板图片"""
    for attempt in range(retries):
        result = find_template_on_screen(template_name, threshold, region)
        if result:
            x, y, scale = result
            x += offset[0]
            y += offset[1]
            logger.info(f"点击 '{template_name}' at ({x},{y})")
            pyautogui.click(x, y)
            time.sleep(0.6)
            return True
        time.sleep(interval)
    return False


def click_rel(rel_x, rel_y):
    """按窗口相对坐标点击（后备方案）"""
    rect = get_window_rect()
    if not rect:
        return False
    left, top, w, h = rect
    x = left + int(w * rel_x / 1000)
    y = top + int(h * rel_y / 1000)
    pyautogui.click(x, y)
    time.sleep(0.5)
    return True


# ========== 登录流程 ==========

def step1_click_bottom_left():
    """步骤1: 点击左下角头像/登录按钮"""
    logger.info("步骤1: 点击左下角")
    if not bring_doubao_to_foreground():
        return False, "无法激活豆包窗口"
    # 左下角用坐标点击（头像区域没有明显的文字模板）
    click_rel(50, 950)
    time.sleep(1.5)
    return True, "已点击左下角"


def step2_click_switch_account():
    """步骤2: 点击'切换账号'"""
    logger.info("步骤2: 点击切换账号")
    if click_template('btn_switch_account.png', threshold=0.6, retries=4):
        time.sleep(1.5)
        return True, "已点击切换账号"
    # 后备坐标
    click_rel(150, 700)
    time.sleep(1.5)
    return True, "已点击切换账号（坐标后备）"


def step3_click_add_account():
    """步骤3: 点击'添加账号'"""
    logger.info("步骤3: 点击添加账号")
    if click_template('btn_add_account.png', threshold=0.6, retries=4):
        time.sleep(2)
        return True, "已点击添加账号"
    # 后备坐标
    click_rel(250, 500)
    time.sleep(2)
    return True, "已点击添加账号（坐标后备）"


def step4_check_agree():
    """步骤4: 勾选'已阅读并同意'"""
    logger.info("步骤4: 勾选同意协议")
    # 复选框在模板图片最左侧，偏移 -120 像素
    if click_template('chk_agree.png', threshold=0.6, retries=3, offset=(-120, 0)):
        time.sleep(0.5)
        return True, "已勾选同意协议"
    # 后备坐标
    click_rel(300, 620)
    time.sleep(0.5)
    return True, "已勾选同意协议（坐标后备）"


def step5_click_phone_login():
    """步骤5: 点击'手机号登录'"""
    logger.info("步骤5: 点击手机号登录")
    if click_template('btn_phone_login.png', threshold=0.6, retries=4):
        time.sleep(1.5)
        return True, "已点击手机号登录"
    # 后备坐标
    click_rel(350, 350)
    time.sleep(1.5)
    return True, "已点击手机号登录（坐标后备）"


def step6_input_phone_and_next(phone):
    """步骤6: 输入手机号并点击下一步"""
    logger.info(f"步骤6: 输入手机号 {phone[:3]}****{phone[-4:]}")
    # 点击手机号输入框（偏移 +80 到输入区域）
    if not click_template('input_phone.png', threshold=0.6, retries=3, offset=(80, 0)):
        click_rel(500, 480)
    time.sleep(0.3)

    # 清空并输入
    pyautogui.hotkey('ctrl', 'a')
    time.sleep(0.1)
    pyautogui.press('delete')
    time.sleep(0.1)
    pyautogui.typewrite(phone, interval=0.03)
    time.sleep(0.5)

    # 点击下一步
    if click_template('btn_next.png', threshold=0.6, retries=4):
        time.sleep(2.5)
        return True, "已输入手机号并点击下一步，验证码已发送"
    # 后备坐标
    click_rel(500, 580)
    time.sleep(2.5)
    return True, "已输入手机号并点击下一步"


def step7_input_code(code):
    """步骤7: 输入6位验证码
    关键：验证码页面加载后第一个方框已自动聚焦（截图可见光标）。
    不要激活窗口、不要点击，直接输入数字即可。
    激活窗口或点击反而会破坏已有的焦点。
    """
    logger.info(f"步骤7: 输入验证码 {code}")

    # 不要调用 bring_doubao_to_foreground()！会破坏焦点
    # 不要点击任何位置！第一个方框已经聚焦了

    # 直接输入6位数字（多种方式兜底）
    input_success = False

    # 方式1: 逐个按数字键（最可靠，每个数字自动跳框）
    try:
        for digit in code:
            pyautogui.press(digit)
            time.sleep(0.12)
        input_success = True
        logger.info("验证码输入方式1(逐个press)成功")
    except Exception as e:
        logger.warning(f"方式1失败: {e}")

    # 方式2: typewrite 连续输入
    if not input_success:
        try:
            pyautogui.typewrite(code, interval=0.15)
            input_success = True
            logger.info("验证码输入方式2(typewrite)成功")
        except Exception as e:
            logger.warning(f"方式2失败: {e}")

    # 方式3: 剪贴板粘贴
    if not input_success:
        try:
            import subprocess
            subprocess.run(['clip'], input=code.encode('utf-16-le'), check=True)
            time.sleep(0.2)
            pyautogui.hotkey('ctrl', 'v')
            input_success = True
            logger.info("验证码输入方式3(剪贴板)成功")
        except Exception as e:
            logger.warning(f"方式3失败: {e}")

    time.sleep(3)  # 等待自动登录
    logger.info(f"验证码输入完成: {code}, 成功={input_success}")
    return input_success, "已输入验证码" if input_success else "验证码输入失败"


# ========== 对外接口 ==========

def pre_login_steps():
    """
    预备操作：执行登录前5步（不输入手机号）
    左下角 → 切换账号 → 添加账号 → 勾选同意 → 手机号登录
    用于客户打开链接时预先执行，提高速度
    返回: (success, message)
    """
    if not HAS_PYAUTOGUI:
        return False, "pyautogui 不可用"

    try:
        logger.info("=== 开始预备操作（前5步）===")
        steps = [
            ("左下角", step1_click_bottom_left),
            ("切换账号", step2_click_switch_account),
            ("添加账号", step3_click_add_account),
            ("勾选同意", step4_check_agree),
            ("手机号登录", step5_click_phone_login),
        ]

        for name, step_func in steps:
            success, msg = step_func()
            if not success:
                logger.warning(f"预备操作 {name} 失败: {msg}")
                return False, f"{name}失败: {msg}"
            logger.info(f"预备操作 {name}完成: {msg}")

        logger.info("=== 预备操作完成，等待输入手机号 ===")
        return True, "预备操作完成"
    except Exception as e:
        logger.error(f"预备操作异常: {e}", exc_info=True)
        return False, f"操作异常: {e}"


def send_code(phone, skip_pre_steps=False):
    """
    发送验证码完整流程：
    左下角 → 切换账号 → 添加账号 → 勾选同意 → 手机号登录 → 输手机号 → 下一步
    skip_pre_steps: 如果已经执行了预备操作，跳过前5步
    """
    if not phone or len(phone) != 11:
        return False, "手机号格式不正确"

    if not HAS_PYAUTOGUI:
        return False, "pyautogui 不可用"

    try:
        if not skip_pre_steps:
            steps = [
                ("左下角", step1_click_bottom_left),
                ("切换账号", step2_click_switch_account),
                ("添加账号", step3_click_add_account),
                ("勾选同意", step4_check_agree),
                ("手机号登录", step5_click_phone_login),
            ]

            for name, step_func in steps:
                success, msg = step_func()
                if not success:
                    return False, f"{name}失败: {msg}"
                logger.info(f"{name}完成: {msg}")

        # 输入手机号并下一步
        success, msg = step6_input_phone_and_next(phone)
        if not success:
            return False, msg

        return True, "验证码已发送，请注意查收短信"
    except Exception as e:
        logger.error(f"发送验证码异常: {e}", exc_info=True)
        return False, f"操作异常: {e}"


def do_login(phone, code):
    """
    登录：直接输入验证码
    调用此接口时，用户已经在验证码页面了（send_code已经执行过）
    不需要再检查页面状态，直接输入验证码即可
    """
    if not phone or len(phone) != 11:
        return False, "手机号格式不正确"
    if not code or len(code) < 4:
        return False, "验证码格式不正确"

    if not HAS_PYAUTOGUI:
        return False, "pyautogui 不可用"

    try:
        logger.info(f"=== 开始登录：直接输入验证码 {code} ===")

        # 直接输入验证码（不检查页面状态，不激活窗口，不点击）
        success, msg = step7_input_code(code)
        if not success:
            return False, msg

        return True, "登录操作已执行"
    except Exception as e:
        logger.error(f"登录异常: {e}", exc_info=True)
        return False, f"操作异常: {e}"


# ========== 测试 ==========

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    print("=== 豆包自动化模块测试（图像识别版）===")
    print(f"uiautomation: {'可用' if HAS_UIAUTO else '不可用'}")
    print(f"pyautogui: {'可用' if HAS_PYAUTOGUI else '不可用'}")
    print(f"OpenCV: {'可用' if HAS_CV2 else '不可用'}")
    print(f"资源目录: {ASSETS_DIR}")
    if os.path.exists(ASSETS_DIR):
        print(f"模板文件: {os.listdir(ASSETS_DIR)}")

    win = find_doubao_window()
    if win:
        print(f"\n豆包窗口: {win.Name}")
        rect = get_window_rect()
        print(f"窗口位置: {rect}")
    else:
        print("\n未找到豆包窗口")
