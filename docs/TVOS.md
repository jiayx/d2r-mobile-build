# Apple TV (experimental) / Apple TV（实验性）

This workflow follows upstream's `dm/tvos/build.sh` and `dm/tvos/gen_romfs_overlay.py`. It targets **Apple TV 4K (3rd generation, A15), tvOS 26 or later**, with an extended Xbox / PlayStation / compatible gamepad. Siri Remote cannot play the game. The [experimental v2.2.0 package](https://github.com/jiayx/d2r-mobile-build/releases/tag/v2.2.0-build.7.1-tvos) has passed native compilation and package checks. No physical-device testing has been performed.

本工作流调用上游 `dm/tvos/build.sh` 和 `dm/tvos/gen_romfs_overlay.py`，面向 **第三代 Apple TV 4K（A15）、tvOS 26 及以上**，需要 Xbox / PlayStation 等扩展手柄；Siri 遥控器不能游玩。[v2.2.0 实验版](https://github.com/jiayx/d2r-mobile-build/releases/tag/v2.2.0-build.7.1-tvos) 已通过原生编译及打包校验。未进行真机测试。

## Build / 构建

Run **Build Apple TV (experimental)** with one `prepared_input` JSON containing an HTTPS `url` and `sha256` or `sha256_url`. Leave `source_ref` empty to follow the latest official upstream Release.

运行 **Build Apple TV (experimental)**，仅填写一份 `prepared_input` JSON，包含 HTTPS `url` 和 `sha256` 或 `sha256_url`。`source_ref` 留空跟随最新正式 Release。

```json
{
  "url": "https://github.com/jiayx/d2r-mobile-build/releases/download/tvos-prepared-v1-ef88cf20fa3fec561f5caf26dad069b106e48386e2dcc3e786e43d7003891c48/D2RMobile-TVPrepared.zip",
  "sha256_url": "https://github.com/jiayx/d2r-mobile-build/releases/download/tvos-prepared-v1-ef88cf20fa3fec561f5caf26dad069b106e48386e2dcc3e786e43d7003891c48/TVPrepared-SHA256SUMS.txt"
}
```

The standalone TV package contains only the rewritten main/sdk programs and tables, sparse original interface inputs, Legacy descriptor/index, original shader packs and checksums. It contains no iOS/Mac compiled Metal libraries. The builder verifies all files and source compatibility, checks original shader content hashes, then builds TV libraries, DmTV and the TV Legacy overlay using upstream tools.

独立 TV 包仅包含改写后的 main/sdk 程序及表、界面生成所需的原始数据、Legacy 描述及索引、原始着色器包和校验清单，不包含 iOS/Mac 已编译 Metal 库。构建时验证全部文件和源码兼容性、原始着色器内容哈希，再使用上游工具生成 TV 库、DmTV 和电视专用 Legacy 覆盖层。

The input is stored in a separate immutable Release rather than an expiring Actions artifact. Existing iOS/Mac input packages are unchanged. Matching caches are reused when available; the capacity guard never deletes other caches to make room.

输入存放在独立、内容哈希命名的 Release，不依赖会过期的 Actions artifact。现有 iOS/Mac 预处理包保持不变。有匹配缓存时复用；空间保护不会通过删除其他缓存腾出空间。

To refresh the TV package, run **Prepare TV input** with the existing iOS/Mac prepared JSON and `data_input` containing a successful original recovery run, for example `{"recovery_run_id":"41077361816"}`. Preparation verifies all three inputs, keeps only the required files, and publishes a new package, checksum list and size report. The recovery artifact must still be available when refreshing; normal TV builds do not need it.

更新 TV 包时运行 **Prepare TV input**：填写现有 iOS/Mac 预处理 JSON，以及含成功原始恢复任务编号的 `data_input`（例如 `{"recovery_run_id":"41077361816"}`）。制作流程完整校验三份输入，仅保留必需文件，并发布新包、校验清单和体积报告。更新输入时恢复 artifact 须仍可用；日常 TV 构建不再依赖它。

A successful app build publishes an experimental prerelease with unsigned IPA, TV overlay, checksums and a build report. It does not replace the stable iOS/Mac Release. Installation and gameplay still require physical-device testing.

App 构建成功后发布实验性预发布，包含未签名 IPA、TV 覆盖层、校验清单和构建报告，不替换稳定 iOS/Mac Release。安装和实际游玩仍需真机验证。

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
