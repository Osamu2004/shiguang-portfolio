# 拾光健康（iPhone 伴侣）

原生 SwiftUI + HealthKit 应用，只读取用户明确授权的步数、睡眠、静息心率、活动能量和体重。不会写入 Apple 健康，不会上传到第三方服务器。

## 在 Mac 上生成工程

```bash
brew install xcodegen
cd /path/to/shiguang-portfolio/ios/ShiguangHealth
xcodegen generate
open ShiguangHealth.xcodeproj
```

在 Xcode 的 `Signing & Capabilities` 中选择你的 Apple ID Team，连接 iPhone 后点击 Run。免费 Apple ID 签名通常需要定期重新安装；正式长期分发需要 Apple Developer Program。

## 导入拾光桌面端

1. iPhone 中选择 7/30/90 天并授权读取。
2. 点击“导出到桌面拾光”，通过 AirDrop、iCloud Drive 或文件 App 保存 CSV。
3. 桌面拾光打开“健康记录”，选择“导入 CSV”。

同一天重新导入会覆盖该天的健康汇总，不会生成重复日期。
