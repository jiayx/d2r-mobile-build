# Apple TV (experimental) / Apple TV（实验性）

This workflow follows upstream's `dm/tvos/build.sh` and `dm/tvos/gen_romfs_overlay.py`. It targets **Apple TV 4K (3rd generation, A15), tvOS 26 or later**, with an extended Xbox / PlayStation / compatible gamepad. Siri Remote cannot play the game. The workflow has not yet completed its first native build: the current repository inputs lack original game files and translated MSL shader sources. No physical-device testing has been performed.

本工作流调用上游 `dm/tvos/build.sh` 和 `dm/tvos/gen_romfs_overlay.py`，面向 **第三代 Apple TV 4K（A15）、tvOS 26 及以上**，需要 Xbox / PlayStation 等扩展手柄；Siri 遥控器不能游玩。目前尚未完成首次原生构建：仓库现有输入缺少原始游戏文件和已翻译的 MSL 着色器源码。未进行真机测试。

## Build / 构建

1. Configure repository Secret **`GAME_ARCHIVE`** with a JSON object containing the HTTPS `url` and `sha256` of your original archive containing one `ExeFS`/`RomFS` pair. It uses the same format as the existing prepared-input generation workflows. Do not paste private URLs into Issues.
2. Run **Build Apple TV (experimental)**. Paste the iOS `prepared_input` JSON from the main README. Only the verified Legacy pack descriptor/index is reused from it; its compiled iOS shaders are not used for tvOS.
3. Leave `source_ref` empty for the latest official upstream Release. The workflow runs upstream setup on the Actions Mac, compiles tvOS shaders, builds `DmTV`, and generates the TV-specific Legacy overlay. Available matching caches are restored; cache space is checked before saving, without deleting other caches.
4. A successful run publishes an **experimental pre-release**, with an unsigned `*-tvos.ipa`, `*-tvos-overlay.zip`, `TV-SHA256SUMS.txt`, and `tvos-build-report.json`. It does not replace the latest stable iOS/Mac Release.

1. 在仓库 Secret **`GAME_ARCHIVE`** 中配置含 HTTPS `url` 和 `sha256` 的 JSON，指向含一组 `ExeFS`/`RomFS` 的原始游戏压缩包；格式与已有预处理生成工作流相同。不要将私有链接贴到 Issue。
2. 运行 **Build Apple TV (experimental)**，填写主 README 的 iOS `prepared_input` JSON。这里只复用已校验的 Legacy 描述和索引，不将 iOS 着色器用于 tvOS。
3. `source_ref` 留空跟随最新正式 Release。工作流在 Actions Mac 上运行上游 setup，编译 tvOS 着色器、构建 `DmTV` 并生成电视专用 Legacy 覆盖层。复用匹配缓存，保存前检查空间，不删除其他缓存。
4. 成功后发布为**实验性预发布**，包含未签名 `*-tvos.ipa`、`*-tvos-overlay.zip`、校验清单和构建报告，不替换最新稳定 iOS/Mac Release。

Current iOS/Mac prepared ZIPs alone cannot build this target: they contain compiled libraries but not the translated MSL sources required by upstream's tvOS compiler. The TV target embeds game program segments using upstream's build; the iOS Guest ad-hoc signing flow remains unchanged.

现有 iOS/Mac 预处理 ZIP 只有已编译库，缺少上游 tvOS 编译器所需的 MSL 源码，不能单独构建 TV 版。TV 按上游方式内嵌游戏程序段；iOS 的 Guest ad-hoc 签名流程保持不变。

## Install and import / 安装和资源导入

Re-sign the app for your own Apple TV using a tvOS-capable signing/provisioning account and deploy with Xcode's device tools. An unsigned IPA is not directly installable. This project's iPhone installation instructions do not establish Apple TV compatibility for those installers. Follow [upstream's TV instructions](https://github.com/jhaizhou-ops/d2r-mobile/blob/main/dm/tvos/README.md); device deployment has not been verified here.

使用可为 tvOS 签名和配置设备的账号自行重签，通过 Xcode 设备工具部署。未签名 IPA 不能直接安装；本项目列出的 iPhone 安装工具不代表已验证支持 Apple TV。参考[上游 TV 说明](https://github.com/jhaizhou-ops/d2r-mobile/blob/main/dm/tvos/README.md)，本项目尚未验证设备部署。

Copy into the app data container / 将下列文件放入 App 数据容器：

| Relative path / 相对路径 | Content / 内容 |
|---|---|
| `Library/Caches/D2R/RomFS/data/` | Existing matching Data: `build_manifest.psv` and all 18 `.data` files / 现有配套 Data 的清单及全部 18 个 `.data` |
| `Library/Caches/D2R/astc/data/` | Matching Legacy Device Pack `.data` file / 配套 Legacy 补充包的 `.data` |
| `Library/Caches/D2R/romfs_overlay_astc/` | Extracted TV overlay from this build, including `pack.json` and `data/` / 本次 TV 构建生成的覆盖层，含 `pack.json` 和 `data/` |
| `Library/Caches/D2R/save/` | Saves / 存档 |

Use the existing community Data and Legacy links in the main README. The overlay ZIP is a small additional generated resource, not a replacement for Data or Legacy. Match the Legacy file to the build report's size and SHA-256. The TV app has no resource download/import UI.

Data 和 Legacy 使用主 README 中现有的社区资源链接。覆盖层 ZIP 是额外生成的小型资源，不能代替 Data 或 Legacy。Legacy 文件应与构建报告记录的大小及 SHA-256 一致。TV App 没有资源下载或导入界面。

**Caches may be purged by tvOS, including saves. Back up saves; reliable cloud saving is not implemented.** Long sessions, all controller buttons, background saving, audio interruptions and controller reconnection still require physical-device verification. Build success is not gameplay validation.

**tvOS 可能清理 Caches，包括存档。请备份存档；尚无可靠云存档功能。** 长时间运行、全部手柄按键、切后台存盘、音频打断及手柄重连均待实机验证。构建成功不代表游戏验证通过。
