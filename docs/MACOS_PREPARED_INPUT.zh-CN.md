# macOS 预处理包

[English](MACOS_PREPARED_INPUT.md) | [简体中文](MACOS_PREPARED_INPUT.zh-CN.md)

在运行参数 `prepared_input` 中填写预处理包的 HTTPS 下载地址 `url` 和校验值 `sha256`。ZIP 内的目录如下：

```text
manifest.json
product/
msl/b-<着色器链版本>/
romfs-inputs.zip
generated/
  dm_vault_tab.h
  dm_hud_exp.h
  dm_bright_levels.inc
shader-chain.lock
c1_full.tsv
```

| 路径 | 内容 |
|---|---|
| `manifest.json` | 格式标识 `d2r-mobile-macos-prepared`、格式版本 `2`、源码提交、游戏程序校验值、生成规则标识、生成工具链及各文件 SHA-256 |
| `product/` | 上游改写后的 `touch` 游戏程序与装载表 |
| `msl/` | 最低面向 macOS 15.0 的 Metal 着色器库，每份 `_b.metallib` 配有对应的 `_b.json` 反射文件；两份 Mac 应用共用 |
| `romfs-inputs.zip` | 生成 Mac 布局、文案、图片、字体、数据表和覆盖层需要的原始输入子集 |
| `generated/` | 游戏数据表头文件 |
| `shader-chain.lock`、`c1_full.tsv` | 配套着色器工具指纹与下标清单 |

界面资源跟随所选源码生成。若工作流提示预处理输入不兼容，请生成新的预处理包。

## 生成 macOS 预处理包

在私有仓库添加 `GAME_ARCHIVE` Secret，JSON 中填写包含一对 `ExeFS`/`RomFS` 的压缩包 HTTPS 地址 `url` 和校验值 `sha256`。添加以下工作流生成 Mac 预处理包：

```yaml
name: Prepare Mac input
on: workflow_dispatch
permissions:
  contents: write
  actions: write
jobs:
  prepare:
    uses: jiayx/d2r-mobile-build/.github/workflows/prepare-macos.yml@main
    secrets:
      GAME_ARCHIVE: ${{ secrets.GAME_ARCHIVE }}
```

工作流将 `D2RMobile-MacPrepared.zip` 和 `MacPrepared-SHA256SUMS.txt` 发布到自己的私有 Releases。将此 ZIP 作为 **Build macOS** 的输入。同一私有仓库的附件可使用 `https://api.github.com/repos/OWNER/REPO/releases/assets/附件ID` 形式的地址，下载时由该仓库的工作流令牌认证。
