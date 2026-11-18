# Apple TV (experimental) / Apple TV（实验性）

Requires **Apple TV 4K (3rd generation, A15), tvOS 26+**, and an Xbox / PlayStation / compatible gamepad. Siri Remote is not supported. Download the [Apple TV package](https://github.com/jiayx/d2r-mobile-build/releases/tag/v2.3.3-build.1.2-tvos). No physical-device testing.

需要 **第三代 Apple TV 4K（A15）、tvOS 26+** 和 Xbox / PlayStation 等兼容手柄，不支持 Siri 遥控器。下载 [Apple TV 安装包](https://github.com/jiayx/d2r-mobile-build/releases/tag/v2.3.3-build.1.2-tvos)。未做真机测试。

## Build / 构建

Run **Build Apple TV (experimental)** with the following `prepared_input`. Leave `source_ref` empty to build the latest official upstream Release.

运行 **Build Apple TV (experimental)**，填写以下 `prepared_input`。`source_ref` 留空构建上游最新正式 Release。

```json
{
  "url": "https://github.com/jiayx/d2r-mobile-build/releases/download/tvos-prepared-v1-fe1fc6715bc34ce20ef9475811faf016362a459705758e9e486d454e70fb5dca/D2RMobile-TVPrepared.zip",
  "sha256_url": "https://github.com/jiayx/d2r-mobile-build/releases/download/tvos-prepared-v1-fe1fc6715bc34ce20ef9475811faf016362a459705758e9e486d454e70fb5dca/TVPrepared-SHA256SUMS.txt"
}
```

For an official upstream release, the Apple TV download contains an unsigned IPA, TV overlay, checksums and a build report.

上游正式版对应的 Apple TV 下载包含未签名 IPA、TV 覆盖层、校验文件和构建报告。

To generate a new prepared package, run **Prepare TV input** with iOS/Mac prepared input JSON and a `data_input` recovery run ID, for example `{"recovery_run_id":"41077361816"}`. The recovery run must contain an available `tvos-shader-input` artifact.

需要生成新的预处理包时，运行 **Prepare TV input**，填写 iOS/Mac 预处理 JSON 和 `data_input` 恢复任务编号，例如 `{"recovery_run_id":"41077361816"}`。该任务须有可下载的 `tvos-shader-input` artifact。

## Install and import / 安装和资源导入

Sign the IPA for your Apple TV with a tvOS-capable signing account, then deploy using Xcode's device tools. See [upstream's TV instructions](https://github.com/jhaizhou-ops/d2r-mobile/blob/main/dm/tvos/README.md).

使用支持 tvOS 的签名账号为 Apple TV 签名，再通过 Xcode 设备工具安装。详见[上游 TV 说明](https://github.com/jhaizhou-ops/d2r-mobile/blob/main/dm/tvos/README.md)。

Download Data and Legacy from the [resource links](../README.md), then copy these files into the app data container. The TV app has no resource import UI.

从[资源入口](../README.zh-CN.md)下载 Data 和 Legacy，再将下列文件放入 App 数据容器。TV App 没有资源导入界面。

| Relative path / 相对路径 | Content / 内容 |
|---|---|
| `Library/Caches/D2R/RomFS/data/` | Data: `build_manifest.psv` and all 18 `.data` files / Data 的清单及全部 18 个 `.data` 文件 |
| `Library/Caches/D2R/astc/data/` | Legacy Device Pack `.data` file / Legacy 补充包的 `.data` 文件 |
| `Library/Caches/D2R/romfs_overlay_astc/` | Extracted TV overlay from the app Release, including `pack.json` and `data/` / 应用 Release 中的 TV 覆盖层，含 `pack.json` 和 `data/` |
| `Library/Caches/D2R/save/` | Saves / 存档 |

Match the Legacy file's size and SHA-256 to the build report. Import Data, Legacy and the TV overlay.

Legacy 文件的大小及 SHA-256 应与构建报告一致。Data、Legacy 和 TV 覆盖层均需导入。

With Xcode, you can transfer the three directories separately. Install the signed app, open it once, then quit it. On the Mac, place the extracted directories in the layout above under a local `D2R/` folder. Run this from its parent directory using the paired Apple TV identifier and the bundle ID used when signing.

可以用 Xcode 分三次传输。先安装已签名的 App，打开一次并退出。在 Mac 上按上表整理本地 `D2R/` 文件夹，在它的上一级目录执行以下命令。设备标识填写已配对的 Apple TV，包名填写重签后的实际值。

```bash
xcrun devicectl list devices
DEVICE='your-device-identifier'
BUNDLE='your-signed-bundle-id'
for dir in RomFS astc romfs_overlay_astc; do
  xcrun devicectl device copy to --device "$DEVICE" \
    --domain-type appDataContainer --domain-identifier "$BUNDLE" \
    --source "D2R/$dir" --destination "Library/Caches/D2R/$dir" || break
done
```

After all three transfers succeed, launch the app again. If one fails, retry that directory. The commands only target the resource directories.

三次传输均成功后重新启动 App。若某一步失败，可单独重传对应目录。这些命令只写入资源目录。

**tvOS may purge Caches, including saves. Back up saves; cloud saving is not supported.**

**tvOS 可能清理 Caches，包括存档。请备份存档；暂不支持云存档。**

If a transfer stalls, record the tool, the step (signing, installation, container transfer or launch), and the exact error. For an exit after launch, include the Apple TV device log.

若进度卡住，请记录工具、具体阶段（签名、安装、容器导入或启动）及完整报错。若在启动后退出，请附 Apple TV 设备日志。
