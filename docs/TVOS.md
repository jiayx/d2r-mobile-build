# Apple TV (experimental) / Apple TV（实验性）

This workflow follows upstream's `dm/tvos/build.sh` and `dm/tvos/gen_romfs_overlay.py`. It targets **Apple TV 4K (3rd generation, A15), tvOS 26 or later**, with an extended Xbox / PlayStation / compatible gamepad. Siri Remote cannot play the game. The workflow has not yet completed its first native build: the first Actions attempt was blocked by Google Drive download quota. No physical-device testing has been performed.

本工作流调用上游 `dm/tvos/build.sh` 和 `dm/tvos/gen_romfs_overlay.py`，面向 **第三代 Apple TV 4K（A15）、tvOS 26 及以上**，需要 Xbox / PlayStation 等扩展手柄；Siri 遥控器不能游玩。目前尚未完成首次原生构建：首次 Actions 尝试因 Google Drive 下载配额用尽而阻塞。未进行真机测试。

## Build / 构建

Run **Build Apple TV (experimental)** with three inputs:

- `prepared_input`: the iOS JSON from the main README (verified Legacy descriptor/index).
- `macos_input`: the macOS JSON from the main README (verified rewritten programs and original interface inputs).
- `data_input`: ordered Data archive parts and their checksums, as below. These are the existing files linked from the README, not new uploads.

运行 **Build Apple TV (experimental)**，填写三个输入：

- `prepared_input`：主 README 的 iOS JSON，用于已校验的 Legacy 描述和索引。
- `macos_input`：主 README 的 macOS JSON，用于已校验的改写程序和原始界面输入。
- `data_input`：按顺序排列的 Data 分卷及其校验值，见下方。这些是 README 已有链接中的文件，不需要重新上传。

Leave `source_ref` empty for the latest official upstream Release. The workflow downloads and verifies the parts on Actions, extracts original shader packs from Data, reuses verified Mac program images, translates shaders with upstream tools, compiles tvOS libraries, then builds upstream `DmTV` and the TV-specific Legacy overlay. Embedded shaders are read from the prepared main image; upstream checks their control-segment hashes against the shader map. No synthetic ExeFS or original-game checksum bypass is used. Neither the Mac nor iOS compiled libraries are used as tvOS libraries.

`source_ref` 留空跟随最新正式 Release。工作流在 Actions 下载和校验分卷，从 Data 提取原始着色器包，复用已校验的 Mac 程序映像，通过上游工具翻译并编译 tvOS 着色器，再构建上游 `DmTV` 和电视专用 Legacy 覆盖层。程序内嵌着色器从预处理 main 映像读取，上游仍逐个核对控制段哈希。不会伪造 ExeFS 或跳过原始游戏校验；不会将 Mac/iOS 编译库当作 tvOS 库。

Available matching input/generation caches are restored, with space checks before saving and no deletion of other caches. The first run downloads about 5.43 GB of Data on Actions; it does not download game files to your local computer. A successful run publishes an experimental prerelease containing an unsigned `*-tvos.ipa`, `*-tvos-overlay.zip`, checksums and a build report. It does not replace the latest stable iOS/Mac Release. TV embeds game program segments using upstream's build; the iOS Guest ad-hoc signing flow is unchanged.

复用匹配的输入和生成缓存，保存前检查空间，不删除其他缓存。首次运行在 Actions 下载约 5.43 GB Data，不下载游戏文件到本机。成功后发布实验性预发布，包含未签名 IPA、TV 覆盖层 ZIP、校验清单和构建报告，不替换最新稳定 iOS/Mac Release。TV 按上游方式内嵌程序段；iOS Guest ad-hoc 签名流程不变。

### Existing Data input / 现有 Data 输入

```json
{"parts": [{"url": "https://drive.google.com/file/d/1xcXQwIYCq1Lugqwj-P7B2x9X-cu3dDKy/view", "sha256": "e383d983b8f504b03b31858241ee219d3a229c1e11f8bbfabeeb14f7087d7870"}, {"url": "https://drive.google.com/file/d/1RtHduJ_ujrWnhFJiDTYfHCVQfJM2bWbs/view", "sha256": "d35bb84234ad5ea858504cddcb06150cb61b84aabf15127bf5e23dc45e0ad2ac"}, {"url": "https://drive.google.com/file/d/1oaGEP0cn0U6YRLaERV9kkSZHi5VWsjRf/view", "sha256": "135003ac568178ce47c9c4d8dba37c094ea828583825e6964b27e3bfa6444588"}], "sha256": "0f788dbf4019ea934949c0ba268a6649980faef99466fe188d5d0823654cf494"}
```

The checksums come from `Resources-Parts-SHA256SUMS.txt` and `resources-report.json` in the README's resource folder. If Google Drive reports a download quota error, wait for availability or supply an accessible mirror of the same files with matching checksums. Do not remove checksum validation.

校验值来自 README 资源目录中的分卷校验清单和 `resources-report.json`。若 Google Drive 返回下载配额错误，应等待恢复或改用同文件、同校验值的可用镜像，不关闭校验。

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
