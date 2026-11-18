# Apple TV (experimental) / Apple TV（实验性）

Requires **Apple TV 4K (3rd generation, A15), tvOS 26+**, and an Xbox / PlayStation / compatible gamepad. Siri Remote is not supported. Download the [experimental v2.2.0 package](https://github.com/jiayx/d2r-mobile-build/releases/tag/v2.2.0-build.7.1-tvos). No physical-device testing.

需要 **第三代 Apple TV 4K（A15）、tvOS 26+** 和 Xbox / PlayStation 等兼容手柄，不支持 Siri 遥控器。下载 [v2.2.0 实验版](https://github.com/jiayx/d2r-mobile-build/releases/tag/v2.2.0-build.7.1-tvos)。未做真机测试。

## Build / 构建

Run **Build Apple TV (experimental)** with the following `prepared_input`. Leave `source_ref` empty to build the latest official upstream Release.

运行 **Build Apple TV (experimental)**，填写以下 `prepared_input`。`source_ref` 留空构建上游最新正式 Release。

```json
{
  "url": "https://github.com/jiayx/d2r-mobile-build/releases/download/tvos-prepared-v1-ef88cf20fa3fec561f5caf26dad069b106e48386e2dcc3e786e43d7003891c48/D2RMobile-TVPrepared.zip",
  "sha256_url": "https://github.com/jiayx/d2r-mobile-build/releases/download/tvos-prepared-v1-ef88cf20fa3fec561f5caf26dad069b106e48386e2dcc3e786e43d7003891c48/TVPrepared-SHA256SUMS.txt"
}
```

The build publishes an experimental prerelease containing an unsigned IPA, TV overlay, checksums and a build report.

构建结果发布为实验性预发布，包含未签名 IPA、TV 覆盖层、校验文件和构建报告。

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

**tvOS may purge Caches, including saves. Back up saves; cloud saving is not supported.**

**tvOS 可能清理 Caches，包括存档。请备份存档；暂不支持云存档。**
