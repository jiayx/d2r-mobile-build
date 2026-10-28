# d2r-mobile 构建工作流

[English](README.md) | [简体中文](README.zh-CN.md)

在 GitHub Actions 中从 [d2r-mobile](https://github.com/jhaizhou-ops/d2r-mobile) 源码构建 iOS 和 macOS 应用。默认选择上游最新正式 Release，发布到自己的私有仓库。

## 配置和构建

1. 点击 [Use this template](https://github.com/jiayx/d2r-mobile-build/generate)，创建 **Private** 仓库。
2. 在 **Actions** 中选择 **Build IPA**（iOS）或 **Build macOS**，点击 **Run workflow**，将对应平台的 JSON 粘贴到 **`prepared_input`**：

   **Build IPA（iOS）**

   ```json
   {
     "url": "https://ipfs.filebase.io/ipns/k51qzi5uqu5dkbfnqcjbd6jlgbckojtl4gu7m1kgu8esex1zg4oo485o5cjop2/D2RMobile-Prepared.zip",
     "sha256_url": "https://ipfs.filebase.io/ipns/k51qzi5uqu5dkbfnqcjbd6jlgbckojtl4gu7m1kgu8esex1zg4oo485o5cjop2/Prepared-SHA256SUMS.txt"
   }
   ```

   **Build macOS**

   ```json
   {
     "url": "https://ipfs.filebase.io/ipfs/bafybeihkvz24tivc4hqtlruqlagtrtgcanuzj3o4fgrfjgolxui4hzvni4/D2RMobile-MacPrepared.zip",
     "sha256_url": "https://ipfs.filebase.io/ipfs/bafybeihkvz24tivc4hqtlruqlagtrtgcanuzj3o4fgrfjgolxui4hzvni4/MacPrepared-SHA256SUMS.txt"
   }
   ```

   配置中的预处理包由热心网友提供，iOS 约 **290 MB**，macOS 约 **299 MB**。

3. 点击 **Run workflow** 开始构建。从下载预处理包到编译、打包并发布，iOS 预计约 **6 分钟**，macOS 约 **7 分钟**。

- 默认直接运行，自动编译上游最新正式 Release。
- 测试开发代码：`source_ref` 填 `main`、其他分支、标签或提交。
- 测试自己的修改：`source_repository` 填自己的 Fork，`source_ref` 填对应分支。私有源码仓库另配置 **`SOURCE_TOKEN`** Secret，授予该源码仓库 Contents 只读权限。

构建入口自动使用本项目维护的最新构建逻辑。同一上游版本支持多次构建及重跑，每次使用独立的 Release 和文件名。

需要自行准备输入时，见[生成 iOS 预处理包](docs/PREPARED_INPUT.zh-CN.md#生成-ios-预处理包)或 [生成 macOS 预处理包](docs/MACOS_PREPARED_INPUT.zh-CN.md#生成-macos-预处理包)。

## iOS 下载和使用

构建完成后，在自己仓库的 **Releases** 下载：

| 文件 | 用途 |
|---|---|
| `D2RMobile-<版本>-build.<运行编号>.<尝试次数>.ipa` | iOS 26 及以上 |
| `D2RMobile-<版本>-build.<运行编号>.<尝试次数>-ios18.ipa` | iOS 18–25 |
| `SHA256SUMS.txt`、`build-report.json` | 校验值与构建详情 |

下载热心网友提供的[配套游戏资源（Data 和 Legacy）](https://drive.google.com/drive/folders/1lfjUghi54ohyDxYEtNuEjtGUZyGovaIA)：

| 压缩包 | 下载大小 | 用途 |
|---|---|---|
| `D2R-Mobile-Resources.zip.001`、`.002`、`.003` | 合计 5.42 GB | 所有支持设备均需导入的 Data，解压后为包含 18 个 `.data` 文件的 `D2R Mobile Resources` 文件夹 |
| `Legacy-Device-Pack.zip` | 1.02 GB | A14–A16 设备需要的补充贴图，解压后为 `Legacy Device Pack` 文件夹 |

1. 使用 [Sideloadly](https://sideloadly.io/)、[iloader](https://iloader.app/)、[AltStore Classic](https://faq.altstore.io/altstore-classic/your-altstore) 或 [SideStore](https://sidestore.io/) 签名安装 IPA，安装后先打开一次应用。
2. 从上方链接下载配套 Data。分卷形式需下载全部 `.001`、`.002`、`.003`，用支持分卷的解压工具打开 `.001`，将解压得到的整个 `D2R Mobile Resources` 文件夹拷到“文件”App →“我的 iPhone”→“D2R Mobile”；也可连接 Mac，在 Finder → 手机 →“文件”中拖入该应用。
3. A14–A16 设备另从同一链接下载 `Legacy-Device-Pack.zip`，解压后将整个 `Legacy Device Pack` 文件夹与资源文件夹并排导入。A17 Pro 及更新芯片、M 系列 iPad 使用标准 Data。

   在“文件”App →“我的 iPhone”→“D2R Mobile”中，两个文件夹应处于同一级：

   ```text
   D2R Mobile/
   ├── D2R Mobile Resources/
   └── Legacy Device Pack/
   ```

4. 拷贝完成后回到应用，若停在资源提示页，点击“重试”，应用会自动检测并加载资源。IPA 已包含预编译 Metal 着色器。

设备要求：A14 / M1 及更新芯片，至少 6 GB 内存。

在 M1 iPad 的 LiveContainer 中运行时，若弹出角色起名键盘导致崩溃，可尝试 `-ios18.ipa` 兼容版；它也能在 iPadOS 26 及以上运行。

## 更新 IPA

再次运行 **Build IPA** 即可构建上游最新正式 Release。更新 IPA 时备份存档，保持应用标识一致并覆盖安装，已导入的相同 Data 和 Legacy 可继续使用。

更新时可继续使用原来的预处理包配置；若工作流提示需要新版预处理包，更新 `prepared_input` 后重新运行。

## macOS 下载和使用

使用上方 macOS 的 JSON 配置运行 **Build macOS**。构建完成后，在自己仓库的 **Releases** 下载适合当前 Mac 的 ZIP：

| 文件 | 用途 |
|---|---|
| `D2RMobile-<版本>-build.<运行编号>.<尝试次数>-macos26.zip` | macOS 26 及以上的 Apple 芯片 Mac，内含 `D2R Mobile.app` |
| `D2RMobile-<版本>-build.<运行编号>.<尝试次数>-macos15.zip` | macOS 15–25 的 Apple 芯片 Mac，内含 `D2R Mobile M3.app` |
| `Mac-SHA256SUMS.txt`、`macos-build-report.json` | 校验值与构建详情 |

1. 解压 ZIP，将 `.app` 拖入“应用程序”。
2. 从[游戏资源目录](https://drive.google.com/drive/folders/1lfjUghi54ohyDxYEtNuEjtGUZyGovaIA)下载全部三个 `D2R-Mobile-Resources.zip` 分卷，打开 `.001` 解压，将整个 `D2R Mobile Resources` 文件夹放在固定位置，例如自己的“游戏”文件夹。保留 `data` 内的 `build_manifest.psv` 和 18 个 `.data` 文件。已有的 iOS 资源文件夹符合下方结构时，也可直接复用：

   ```text
   D2R Mobile Resources/
   └── data/
       ├── build_manifest.psv
       ├── 00-00000000.data
       └── …（其余 17 个 .data 文件）
   ```

   若已有资源目录缺少 `build_manifest.psv`，请重新解压上方链接中的完整资源包。
3. 从“应用程序”打开 App。若系统提示无法验证开发者，进入 **系统设置 → 隐私与安全性 → 仍要打开**，再确认“打开”。详见 Apple 的[打开可信应用说明](https://support.apple.com/zh-cn/102445)。
4. 应用提示选择资源时，选择包含 `data` 的整个 **`D2R Mobile Resources`** 文件夹。应用会记住这个位置，包内已包含预编译 Metal 着色器。

## 更新 macOS 应用

再次运行 **Build macOS**，填写 macOS 的 JSON 配置，即可构建上游最新正式 Release。退出应用并备份存档。按原先使用的 macOS 26 版或 macOS 15 版下载对应 ZIP，解压后用新 `.app` 替换“应用程序”中的原应用。

保持资源文件夹的位置不变，游戏资源版本未变时可继续复用已有 Data。macOS 15 版使用独立存档目录，可与 macOS 26 版并存。

更新时可继续使用原来的 Mac 预处理包配置；若工作流提示需要新版 Mac 预处理包，更新 `prepared_input` 后重新运行。

## Apple TV（实验性）

已加入基于上游的 tvOS 构建工作流，首次原生构建仍待补齐原始输入。详见[要求、构建和安装说明](docs/TVOS.md)。面向第三代 Apple TV 4K（A15）、tvOS 26+，需要扩展手柄。未进行真机测试；存档位于系统可清理的 Caches。
