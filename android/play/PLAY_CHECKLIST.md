# Google Play submission checklist — Amosclaud Android

## Verified status of key requirements (see REPORT.md for full detail)

- [x] `targetSdk` = 35, `compileSdk` = 35 (`android/app/build.gradle.kts`). Meets the Play requirement (>= 35 as of this checklist).
- [x] `versionCode` = 1, `versionName` = "1.0.0" present in `android/app/build.gradle.kts`.
- [x] App icon `play/icon-512.png` (512×512) and feature graphic `play/feature-graphic-1024x500.png` (1024×500) present.
- [x] Adaptive launcher icons for mdpi/hdpi/xhdpi/xxhdpi/xxxhdpi with foreground/background/round variants, plus a monochrome layer (`mipmap-anydpi-v26/ic_launcher.xml` and `ic_launcher_round.xml` both declare `<monochrome>`).
- [x] Privacy policy draft present (`play/privacy-policy.md`) covering the data actually collected: name, email, password (auth only, not stored after request), session cookies, chosen API URL, and app content (chat, community posts, mail). **Must be finalized and hosted at `https://amosclauds.com/privacy` before submission — this is still a draft, not a hosted policy.**
- [x] Data safety form draft (`play/data-safety.md`) updated to match actual collection, including that the Community feed is user-generated content read by other users, with in-app report/block controls.
- [x] In-app account deletion exists and works: `SettingsActivity` has a delete-account flow (`btnDeleteAccount` → confirms email/password → calls `AmosclaudApiClient.deleteAccount` → `DELETE /api/v1/account`). **Still required:** a public web page at `https://amosclauds.com/account/delete` that lets a user request deletion without opening the app — confirm this page exists and is live before submission (not verifiable from the Android repo).
- [x] Permissions: only `INTERNET` and `ACCESS_NETWORK_STATE` are declared (`AndroidManifest.xml`), both justified by the app's HTTP API client.
- [x] Cleartext traffic is disabled by default (`network_security_config.xml`: `cleartextTrafficPermitted="false"` at the base config; only `10.0.2.2`/`localhost`/`127.0.0.1` are exempted for local development).
- [x] Release build type has `isMinifyEnabled = true` with `proguard-rules.pro` present and referenced.
- [x] Release signing config reads `keystore.properties` (git-ignored) or `AMOSCLAUD_KEYSTORE_*` environment variables; no secrets are committed. If neither is present, the release signing config is simply absent (unsigned) rather than failing — a real upload keystore must be supplied before `bundleRelease` produces an uploadable artifact.
- [x] User-generated content (Community feed) compliance: in-app **Report** and **Block** actions on every community post (long-press), device-local block-list filtering (works even without a server block endpoint), graceful handling of a missing/not-yet-implemented report endpoint (404/501 still shows a user-facing confirmation, never crashes), and an in-app **Community content policy** screen. See REPORT.md for exact implementation.
- [ ] `play/assetlinks.json` — **not applicable.** This is a pure native app; it does not use a Trusted Web Activity or Android App Links, so no `assetlinks.json` needs to be hosted today. If App Links / TWA are added later, host `assetlinks.json` at `https://amosclauds.com/.well-known/assetlinks.json` and add an `intent-filter` with `autoVerify="true"` at that time.
- [ ] Gradle wrapper: `gradlew`, `gradlew.bat`, and `gradle/wrapper/gradle-wrapper.jar` are now present and executable, alongside the existing `gradle-wrapper.properties` (Gradle 8.7, compatible with AGP 8.4.0). Build was attempted in the sandbox — see REPORT.md for exactly which Gradle tasks passed.

## Original submission checklist

- [ ] Create or confirm the Google Play developer account.
- [ ] Confirm the permanent application ID before first upload: **`com.amosclaudai`**. It becomes **PERMANENT** at the first upload.
- [ ] Enroll in **Play App Signing** in Play Console.
- [ ] Generate an upload key (keep it private):
  ```sh
  keytool -genkeypair -v -keystore upload-keystore.jks -keyalias upload -keyalg RSA -keysize 2048 -validity 10000
  ```
- [ ] Place the keystore outside source control (or use a protected CI secret). Create `android/keystore.properties` using this template; **NEVER COMMIT** this file or any keystore:
  ```properties
  storeFile=../upload-keystore.jks
  storePassword=YOUR_STORE_PASSWORD
  keyAlias=upload
  keyPassword=YOUR_KEY_PASSWORD
  ```
  Alternatively supply `AMOSCLAUD_KEYSTORE_FILE`, `AMOSCLAUD_KEYSTORE_PASSWORD`, `AMOSCLAUD_KEY_ALIAS`, and `AMOSCLAUD_KEY_PASSWORD` as CI environment variables.
- [ ] Build the signed release bundle from `android/`:
  ```sh
  ./gradlew bundleRelease
  ```
- [ ] Confirm the generated `.aab` is signed with the **upload key** before uploading. A debug-signed/local unsigned artifact must **never** be uploaded.
- [ ] Upload the release `.aab` to the appropriate Play Console testing track, then test it before production rollout.
- [ ] Add the store icon (`icon-512.png`) and feature graphic (`feature-graphic-1024x500.png`), and complete the store listing.
- [ ] Capture and upload at least **2 phone screenshots** that show real in-app UI. Also capture 7-inch and 10-inch tablet screenshots if tablets are claimed/supported in the listing.
- [ ] Host the finalized privacy policy at **https://amosclauds.com/privacy** and enter that URL in Play Console.
- [ ] Complete the Data safety form using `data-safety.md`, after verifying server-side collection and processors.
- [ ] Complete the Content rating questionnaire using `content-rating.md`.
- [ ] Set the target audience to the appropriate non-child audience; do not designate the app as for children.
- [ ] Declare that the app contains **no ads**.
- [ ] Provide and validate the required web account-deletion URL: **https://amosclauds.com/account/delete**.
- [ ] Confirm the package targets SDK 35. Android 15 / SDK 35 enforces edge-to-edge by default, so spot-check every screen on an Android 15 emulator/device for status bars, navigation bars, insets, and keyboard behavior.
- [ ] Review release notes, countries/regions, pricing, app access instructions, content declarations, and all Play policy warnings before rollout.
