# iOS prepared package

[English](PREPARED_INPUT.md) | [简体中文](PREPARED_INPUT.zh-CN.md)

Supply an HTTPS link to a ZIP, tar.gz, or tar.xz package in the `prepared_input` workflow parameter. The required files are shown below; one enclosing directory is supported.

```text
prepared.json
source-payload.zip
shader-chain.lock
resource-manifest.json
romfs-inputs.zip
legacy/
  pack.json
  pack_index.tsv
generated/host/
  dm_vault_tab.h
  dm_hud_exp.h
  dm_bright_levels.inc
```

| File | Contents |
|---|---|
| `prepared.json` | Format `d2r-mobile-prepared`, schema `2`, game versions, program checksums, payload metadata and each file’s size and SHA-256. `producer.source_commit` identifies the source used to generate the package. |
| `source-payload.zip` | Rewritten game program, loader tables and precompiled iOS Metal libraries under `Payload/DmIOS.app/`. |
| `shader-chain.lock` | Shader toolchain fingerprints. |
| `resource-manifest.json` | Names and sizes of the 18 Data files for this game resource version, shared by iOS and macOS. |
| `romfs-inputs.zip` | Selected original layouts, strings, images, fonts, tables and CASC metadata needed by upstream resource generators. |
| `legacy/` | Existing Legacy texture-pack descriptor and index. |
| `generated/host/` | Game-table headers. |

Interface resources are generated from the selected source. If the workflow reports incompatible prepared inputs, generate a new package.

The workflow downloads this package and compiles the selected source into two IPAs. For Data and Legacy downloads and import steps, see the [installation instructions](../README.md#download-and-use-on-ios).

## Generate an iOS prepared package

In your private repository, configure two Secrets. Each contains a JSON object with an HTTPS download `url` and `sha256`:

| Secret | Input |
|---|---|
| `GAME_ARCHIVE` | An archive containing one `ExeFS` / `RomFS` pair; the same original input used for Mac preparation |
| `LEGACY_METADATA` | A ZIP containing `pack.json` and `pack_index.tsv` from the Legacy pack generation output for the same game resource version |

Save the following as `.github/workflows/prepare-ios-input.yml`, then run **Actions → Prepare iOS input → Run workflow**:

```yaml
name: Prepare iOS input
on:
  workflow_dispatch:
    inputs:
      source_repository:
        description: Source repository
        type: string
        default: jhaizhou-ops/d2r-mobile
      source_ref:
        description: Branch, tag or commit; empty selects the latest release
        type: string
        default: ''
permissions:
  contents: write
  actions: write
jobs:
  prepare:
    uses: jiayx/d2r-mobile-build/.github/workflows/prepare-ios.yml@main
    with:
      source_repository: ${{ inputs.source_repository }}
      source_ref: ${{ inputs.source_ref }}
    secrets:
      GAME_ARCHIVE: ${{ secrets.GAME_ARCHIVE }}
      LEGACY_METADATA: ${{ secrets.LEGACY_METADATA }}
      SOURCE_TOKEN: ${{ secrets.SOURCE_TOKEN }}
```

The workflow defaults to the latest official upstream Release and publishes `D2RMobile-Prepared.zip` and `Prepared-SHA256SUMS.txt` to your private Releases. Set the ZIP’s URL and checksum in your `prepared_input` JSON, then use **Build IPA** for ordinary builds.
