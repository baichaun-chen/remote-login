# 豆包远程登录工具

通过生成一次性动态链接，远程用户在页面输入手机号和验证码，自动操作你电脑上的桌面版豆包完成登录。

## 功能特性

- 🔗 **一次性动态链接**：每个链接使用后立即失效，10分钟有效期
- 📱 **远程登录页面**：简洁的手机号+验证码输入界面
- 🖥️ **GUI 自动化**：图像识别定位，自动操作桌面版豆包完成登录
- ⚡ **预备操作优化**：客户打开链接时自动执行前5步，提高速度
- 📊 **数据看板**：统计链接使用情况、登录成功/失败记录
- 🎛️ **图形启动器**：双标签页界面（首页+数据看板），一键启动/停止
- 📦 **独立 EXE**：打包为单文件可执行程序，无需安装 Python

## 工作原理

```
远程用户手机/电脑          你的电脑
     │                      │
     │  访问动态链接         │
     │ ──────────────────►  │ 本地 Web 服务 (Flask)
     │                      │
     │  输入手机号+验证码    │
     │ ──────────────────►  │ 接收数据
     │                      │
     │                      │ GUI 自动化 (pyautogui + OpenCV)
     │                      │ ──────────────────► 桌面版豆包
     │                      │                      自动填入并登录
```

## 快速开始

### 方式一：使用 EXE（推荐）

1. 双击运行 `dist/DoubaoRemoteLogin.exe`
2. 在启动器首页点击「启动服务」
3. 等待公网链接生成，复制链接或扫码发给客户
4. 客户打开链接 → 输手机号 → 点获取验证码 → 输验证码 → 点登录
5. 你的电脑上的豆包会自动完成登录

### 方式二：源码运行

```bash
# 安装依赖
pip install -r requirements.txt

# 启动图形启动器
python launcher.py

# 或直接启动服务
python app.py
```

## 完整登录流程

1. **生成链接**：在启动器首页点击「生成新链接」
2. **客户打开链接**：后台自动执行预备操作（左下角→切换账号→添加账号→勾选条款→手机号登录）
3. **客户输入手机号**：点击「获取验证码」，后台输入手机号并点下一步
4. **客户收到验证码**：输入6位验证码，点击「登录」
5. **后台输入验证码**：自动填入验证码并完成登录
6. **登录成功**：页面弹出提示，1秒后自动关闭

## 项目结构

```
remote-login/
├── app.py                  # Web 服务主程序（Flask）
├── doubao_auto.py          # 桌面豆包 GUI 自动化模块
├── launcher.py             # 图形启动器（tkinter，双标签页）
├── requirements.txt        # Python 依赖
├── start.bat               # 命令行启动脚本
├── assets/                 # 图像识别模板
│   ├── btn_add_account.png
│   ├── btn_next.png
│   ├── btn_phone_login.png
│   ├── btn_switch_account.png
│   ├── chk_agree.png
│   ├── code_input_area.png
│   └── input_phone.png
├── templates/              # HTML 模板
│   ├── login.html          # 远程登录页面
│   ├── dashboard.html      # 管理看板
│   └── error.html          # 链接失效页面
└── dist/                   # 打包后的 EXE（git 忽略）
```

## 打包为 EXE

```bash
pip install pyinstaller

python -m PyInstaller --onefile --windowed --name "DoubaoRemoteLogin" \
  --add-data "templates;templates" \
  --add-data "assets;assets" \
  --hidden-import cv2 \
  --hidden-import numpy \
  --hidden-import comtypes \
  --hidden-import comtypes.client \
  --collect-submodules uiautomation \
  --clean launcher.py
```

打包后的文件在 `dist/DoubaoRemoteLogin.exe`。

## 安全特性

- **一次性链接**：每个链接使用后立即失效
- **有效期限制**：链接 10 分钟内有效，过期自动作废
- **随机 Token**：链接包含 24 位随机字符串，无法被猜测
- **本地执行**：所有自动化操作只在你电脑上执行
- **详细日志**：所有接口调用和操作步骤都有日志记录

## 管理看板

访问 `http://localhost:58231/admin/dashboard` 查看：
- 链接生成/使用统计
- 登录成功/失败记录
- 实时运行日志
- 链接管理（作废、清理）

## 常见问题

**Q: 自动化操作位置不对？**
A: 本工具使用 OpenCV 图像识别定位按钮。如果豆包版本更新导致识别失败，可以替换 `assets/` 目录下的模板图片为当前版本的截图。

**Q: 验证码输入失败？**
A: 验证码页面加载后第一个方框已自动聚焦，程序会直接输入数字。如果失败，检查日志中显示的输入方式。

**Q: 公网链接生成失败？**
A: 程序会尝试多种隧道方式（cloudflared、serveo.net、localhost.run）。如果都失败，服务仍可本地运行，可手动使用其他内网穿透工具。

**Q: 可以给别人使用吗？**
A: EXE 是通用的，可以在任何 Windows 电脑上运行。但需要目标电脑已安装桌面版豆包。

## 注意事项

- 本工具仅用于你自己的账号登录，请勿用于非法用途
- 链接包含登录权限，请勿公开分享给不信任的人
- 豆包客户端更新可能导致图像识别模板失效，届时需要更新 `assets/` 目录下的图片
- 运行时请勿操作鼠标键盘，避免干扰自动化流程
