# 拾光投资

一个本地优先的中文个人管理工具，同时管理基金持仓、纪念币收藏与日常健康趋势。

## 现有功能

- 基金持仓总览、占比和集中度提示
- 基金持仓手动维护
- 纪念币藏品、数量、成本与估值统计
- 每日步数、睡眠、静息心率、活动能量和体重
- 健康CSV导入，支持中英文列名
- 财务与健康数据的JSON完整备份
- 从私有 GitHub Releases 自动检查、校验并安装桌面更新
- 手机、Mac和Windows的响应式界面与PWA安装

## 安全设计

- 不读取支付宝账号、Cookie、密码或支付信息。
- 不包含视觉模型，不上传持仓截图。
- 数据库目录已加入 `.gitignore`。

## 本地运行

只需 Python 3.8+，无第三方依赖：

```bash
python3 server.py
```

浏览器打开 <http://127.0.0.1:8787>。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

## 健康CSV格式

```csv
日期,步数,睡眠分钟,静息心率,活动能量,体重,来源
2026-08-24,8231,472,61,385,63.2,Apple Health
2026-08-25,6910,438,63,320,63.0,手动
```

Apple HealthKit 和 Android Health Connect 的自动同步必须由原生手机伴侣应用在用户授权后执行，普通网页不能绕过系统权限读取。当前版本先提供CSV和手动导入，不伪装“自动同步”。

## 多设备使用

将服务运行在一台长期开机的电脑、NAS或私人服务器上，手机、Mac和Windows通过Tailscale访问同一个服务，即可共用同一份数据。服务默认只绑定 `127.0.0.1`，请勿直接暴露到公网。

## Windows / macOS 加密同步

1. 创建一个与源代码分开的私有仓库，例如 `owner/shiguang-vault`。
2. 创建 fine-grained GitHub token，仅授予该仓库 Contents 读写权限。
3. 在应用的“同步”页保存仓库与令牌。令牌进入系统凭据库，不进入SQLite或Git。
4. 设定至少10个字符的同步密码，并在两台电脑上使用相同密码。

保险库使用 PBKDF2-SHA256（600,000次）派生密钥，再以 AES-256-GCM 认证加密。每次上传都生成新的随机盐和 nonce。GitHub上只存在 `vault.enc`，同步密码不会保存。

### 桌面调试

```bash
python3 -m pip install -r requirements-desktop.txt
python3 desktop.py
```

### 构建安装包

Windows需要在Windows上执行：

```bat
build_windows.bat
```

macOS需要在macOS上执行：

```bash
bash build_macos.sh
```

PyInstaller不支持在Linux上交叉构建真正的Windows `.exe` 或macOS `.app`，因此两种成品需分别在对应系统上打包。

仓库已提供 `Desktop builds` GitHub Actions。在 Actions 页手动运行，即可于Windows和macOS托管机分别生成可下载构建产物。当前产物未进行Apple Developer ID或Windows Authenticode签名，仅适合个人测试。

桌面数据目录：

- macOS: `~/Library/Application Support/Shiguang`
- Windows: `%LOCALAPPDATA%\Shiguang`

### 自动更新

应用启动后会检查私有源码仓库的最新 Release。macOS 已通过 `gh auth login` 登录时会自动复用 GitHub CLI 凭据；否则可在“数据同步 → 软件更新”中保存一个仅授予源码仓库 Contents 读取权限的 fine-grained Token。Token 只进入系统凭据库。更新包必须同时通过 Release 中的 SHA-256 校验，确认后才会替换程序并重启；个人数据库不会被修改。

## 与参考项目的关系

界面设计参考了 [LuoDi-Nate/financial-management](https://github.com/LuoDi-Nate/financial-management) 的公开设计语言，但本项目的名称、界面代码、业务代码和数据模型均为独立实现。

## 免责声明

本项目用于个人数据管理和学习，不构成投资建议、基金销售或收益承诺。
