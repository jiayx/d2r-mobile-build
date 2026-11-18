# macOS prepared package

[English](MACOS_PREPARED_INPUT.md) | [简体中文](MACOS_PREPARED_INPUT.zh-CN.md)

In the `prepared_input` workflow parameter, set the package’s HTTPS `url` and `sha256` to this package. The ZIP has this layout:

```text
manifest.json
product/
msl/b-<shader-chain>/
romfs-inputs.zip
generated/
  dm_vault_tab.h
  dm_hud_exp.h
  dm_bright_levels.inc
shader-chain.lock
c1_full.tsv
```

| Path | Contents |
|---|---|
| `manifest.json` | Format `d2r-mobile-macos-prepared`, schema `2`, source commit, game program hashes, generation key, producer toolchain and every file’s SHA-256 |
| `product/` | Upstream’s rewritten `touch` game programs and loader tables |
| `msl/` | macOS Metal libraries targeting macOS 15.0; each `_b.metallib` has a matching `_b.json` reflection file. Shared by both Mac apps |
| `romfs-inputs.zip` | Selected original inputs for generating Mac layouts, strings, images, fonts, data tables and overlays |
| `generated/` | Game-table headers |
| `shader-chain.lock`, `c1_full.tsv` | Matching shader tool fingerprints and index metadata |

Interface resources are generated from the selected source. If the workflow reports incompatible prepared inputs, generate a new package.

## Generate a macOS prepared package

In a private repository, add a `GAME_ARCHIVE` Secret with a JSON object containing the HTTPS `url` and `sha256` of an archive with one `ExeFS`/`RomFS` pair. Use this workflow to generate the Mac prepared package:

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

The workflow publishes `D2RMobile-MacPrepared.zip` and `MacPrepared-SHA256SUMS.txt` to your private Releases. Use this ZIP as the input to **Build macOS**. An asset URL in the same private repository can use `https://api.github.com/repos/OWNER/REPO/releases/assets/ASSET_ID`; downloads authenticate with that repository’s workflow token.
