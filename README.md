# d2r-mobile build workflow

[English](README.md) | [简体中文](README.zh-CN.md)

Build iOS and macOS apps from [d2r-mobile](https://github.com/jhaizhou-ops/d2r-mobile) source with GitHub Actions. Each run defaults to the latest official upstream Release and publishes to your private repository.

## Configure and build

1. Click [Use this template](https://github.com/jiayx/d2r-mobile-build/generate) and create a **Private** repository.
2. In **Actions**, select **Build IPA** (iOS) or **Build macOS**, click **Run workflow**, and paste the JSON for your platform into **`prepared_input`**:

   **Build IPA (iOS)**

   ```json
   {
     "url": "https://github.com/jiayx/d2r-mobile-build/releases/download/ios-shader-refresh-v1-2ac64814c30e1227d8f09f75d42f6d4e832b2a9965fd1739d78aef7fdb184e73/D2RMobile-Prepared.zip",
     "sha256_url": "https://github.com/jiayx/d2r-mobile-build/releases/download/ios-shader-refresh-v1-2ac64814c30e1227d8f09f75d42f6d4e832b2a9965fd1739d78aef7fdb184e73/Prepared-SHA256SUMS.txt"
   }
   ```

   **Build macOS**

   ```json
   {
     "url": "https://github.com/jiayx/d2r-mobile-build/releases/download/macos-shader-refresh-v1-ba0635da60c32e1a1d7fe8779e6f29ad07b44016260cec038ebd96071ac2d2fd/D2RMobile-MacPrepared.zip",
     "sha256_url": "https://github.com/jiayx/d2r-mobile-build/releases/download/macos-shader-refresh-v1-ba0635da60c32e1a1d7fe8779e6f29ad07b44016260cec038ebd96071ac2d2fd/MacPrepared-SHA256SUMS.txt"
   }
   ```

   Prepared inputs are published as versioned GitHub Releases. Reuse these packages until the build reports that the selected upstream source needs newer inputs.

   The prepared packages are approximately **287 MB for iOS** and **292 MB for macOS**.

3. Click **Run workflow** to start the build. Downloading, compiling, packaging and publishing typically takes **about 6 minutes for iOS** or **7 minutes for macOS**.

- Run with the defaults to compile the latest official upstream Release.
- To test development code, set `source_ref` to `main`, another branch, a tag, or a commit.
- To test your changes, set `source_repository` to your fork and `source_ref` to its branch. For private source repositories, add a **`SOURCE_TOKEN`** Secret with Contents read access to that repository.

The build entry automatically uses this project's latest build logic. Repeated builds and reruns of the same upstream version each receive independent Release and file names.

To prepare your own inputs, see [Generate an iOS prepared package](docs/PREPARED_INPUT.md#generate-an-ios-prepared-package) or [Generate a macOS prepared package](docs/MACOS_PREPARED_INPUT.md#generate-a-macos-prepared-package).

## Download and use on iOS

After the build, download from your repository’s **Releases**:

| File | Purpose |
|---|---|
| `D2RMobile-<version>-build.<run>.<attempt>.ipa` | iOS 26 and later |
| `D2RMobile-<version>-build.<run>.<attempt>-ios18.ipa` | iOS 18–25 |
| `SHA256SUMS.txt`, `build-report.json` | Checksums and build details |

Download [Data](https://github.com/jiayx/d2r-mobile-build/releases/tag/data-3.3.94012-97a2ada74145114ff8364bdc51a756408ef0c6d332e58fefe68eb0ee2b7c4a31) and, for A14–A16 devices, the [Legacy Device Pack](https://github.com/jiayx/d2r-mobile-build/releases/tag/legacy-3.3.94012-3e82ab6dec4dee197c05cfc558f60d794e62394f4d843c908c2b91837fa6f9ce) from the resource Releases. Verify the attached SHA-256 checksums. These resources are published once and reused across app updates; existing matching Data and Legacy need no replacement. The app download does not include them.

Resource packages:

| Package | Download size | Purpose |
|---|---|---|
| `D2R-Mobile-Resources.zip.001`, `.002`, `.003` | 5.42 GB total | Data required on every supported device; contains the `D2R Mobile Resources` folder with 18 `.data` files |
| `Legacy-Device-Pack.zip` | 1.02 GB | Additional textures for A14–A16 devices; contains the `Legacy Device Pack` folder |

1. Sign and install the IPA with [Sideloadly](https://sideloadly.io/), [iloader](https://iloader.app/), [AltStore Classic](https://faq.altstore.io/altstore-classic/your-altstore), or [SideStore](https://sidestore.io/), then open the app once.
2. Download Data from the resource Release above or reuse your existing matching Data. For split archives, you need all `.001`, `.002`, and `.003` parts and open `.001` with an extractor supporting split archives. Copy the entire extracted `D2R Mobile Resources` folder to **Files → On My iPhone → D2R Mobile**. Alternatively, connect to a Mac and drag the folder into the app under **Finder → your iPhone → Files**.
3. A14–A16 devices also need a matching `Legacy-Device-Pack.zip`. Extract it and import the entire `Legacy Device Pack` folder beside the resource folder. A17 Pro and newer devices and M-series iPads use the standard Data.

   Under **Files → On My iPhone → D2R Mobile**, the two folders should be at the same level:

   ```text
   D2R Mobile/
   ├── D2R Mobile Resources/
   └── Legacy Device Pack/
   ```

4. Return to the app after copying. If the resource prompt is still shown, tap **Retry**; the app automatically detects and loads the resources. The IPA includes precompiled Metal shaders.

The IPA carries an ad-hoc request for `com.apple.developer.kernel.increased-memory-limit`. Your signing tool must enable the capability for the App ID and preserve it in the final signature and provisioning profile. Free accounts can support this with compatible signing tools; support varies by tool/version. This does not guarantee a fixed memory allowance or eliminate every crash. The IPA still requires signing before installation.

Device requirements: A14 / M1 or newer, with at least 6 GB of memory.

In LiveContainer on an M1 iPad, if opening the character-name keyboard crashes the app, try the `-ios18.ipa` variant, which also runs on iPadOS 26 and later.

## Update the IPA

Run **Build IPA** again to build the latest official upstream Release. Back up saves, keep the app identifier unchanged, and install over the existing app. Previously imported matching Data and Legacy resources remain reusable.

Reuse your existing prepared input configuration when updating. If the workflow asks for a newer prepared package, update `prepared_input` and run it again.

## Download and use on macOS

Run **Build macOS** with the macOS JSON configuration above. After the build, download the ZIP matching your Mac from your repository’s **Releases**:

| File | Purpose |
|---|---|
| `D2RMobile-<version>-build.<run>.<attempt>-macos26.zip` | Apple silicon Macs running macOS 26 or later; contains `D2R Mobile.app` |
| `D2RMobile-<version>-build.<run>.<attempt>-macos15.zip` | Apple silicon Macs running macOS 15–25; contains `D2R Mobile M3.app` |
| `Mac-SHA256SUMS.txt`, `macos-build-report.json` | Checksums and build details |

1. Extract the ZIP and drag the `.app` into **Applications**.
2. Download [Data](https://github.com/jiayx/d2r-mobile-build/releases/tag/data-3.3.94012-97a2ada74145114ff8364bdc51a756408ef0c6d332e58fefe68eb0ee2b7c4a31) or reuse your existing matching resources. If you have all three `D2R-Mobile-Resources.zip` parts, open `.001` to extract them. Keep the entire `D2R Mobile Resources` folder in a stable location, such as your Games folder, including `build_manifest.psv` and all 18 `.data` files inside `data`. You can reuse an existing iOS resource folder with this structure:

   ```text
   D2R Mobile Resources/
   └── data/
       ├── build_manifest.psv
       ├── 00-00000000.data
       └── … (the other 17 .data files)
   ```

   If your existing resource folder is missing `build_manifest.psv`, extract your complete matching resource archive again; an incomplete folder is not ready to use.
3. Open the app from **Applications**. If macOS blocks it because the developer cannot be verified, open **System Settings → Privacy & Security → Open Anyway**, then confirm **Open**. See Apple’s [instructions for opening an app you trust](https://support.apple.com/102445).
4. When the app asks for resources, select the entire **`D2R Mobile Resources`** folder containing `data`. The app remembers this location. Metal shaders are included precompiled.

## Update the macOS app

Run **Build macOS** again with the macOS JSON configuration to build the latest official upstream Release. Quit the app and back up saves, then download and extract the ZIP for the same macOS 26 or macOS 15 app variant. Replace the existing `.app` in **Applications** with the new one.

Keep the resource folder in the same location. Existing Data can be reused while the game resource version remains unchanged. The macOS 15 app uses its own save directory and can coexist with the macOS 26 app.

Reuse your existing Mac prepared input configuration when updating. If the workflow asks for a newer Mac prepared package, update `prepared_input` and run it again.

## Apple TV (experimental)

An upstream-based tvOS build workflow is available. The [experimental v2.2.0 package](https://github.com/jiayx/d2r-mobile-build/releases/tag/v2.2.0-build.7.1-tvos) has passed native compilation and package checks. See [requirements, build and installation](docs/TVOS.md). It targets Apple TV 4K (3rd generation, A15), tvOS 26+, and an extended gamepad. No physical-device testing; saves are stored in purgeable Caches.

TV builds use one standalone prepared input (about 226 MB), linked in the TV guide; they no longer download the iOS/Mac packages or rely on an expiring shader artifact.
