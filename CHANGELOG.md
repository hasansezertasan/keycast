# Changelog

## [0.3.0](https://github.com/hasansezertasan/keycast/compare/v0.2.0...v0.3.0) (2026-07-23)


### Features

* add startup input-capture status summary to overlay and logs ([#36](https://github.com/hasansezertasan/keycast/issues/36)) ([08659cb](https://github.com/hasansezertasan/keycast/commit/08659cbf8d5ceda3ded616467a701cdd1a11a574))
* add the Microsoft Store MSIX channel (ADR-009) ([#39](https://github.com/hasansezertasan/keycast/issues/39)) ([d9d6066](https://github.com/hasansezertasan/keycast/commit/d9d6066a058666a80be9b99b6c6701d58b4cfaab))
* detect Mac App Store installs (ADR-011) ([#45](https://github.com/hasansezertasan/keycast/issues/45)) ([302326b](https://github.com/hasansezertasan/keycast/commit/302326b0654bcf0eadee6fa315d21017573b6202))
* mask keystrokes during macOS secure input (ADR-015) ([#46](https://github.com/hasansezertasan/keycast/issues/46)) ([12b7e1c](https://github.com/hasansezertasan/keycast/commit/12b7e1c9f5338414e08aa494ebef77ffbbb865cb))
* system-wide Screencast Mode (presets + chord grouping) ([#38](https://github.com/hasansezertasan/keycast/issues/38)) ([946856e](https://github.com/hasansezertasan/keycast/commit/946856e4eebd3dad273133a3749242e5c1e66aa2))


### Bug Fixes

* classify pip-into-Homebrew-Python as pip, not formula ([#47](https://github.com/hasansezertasan/keycast/issues/47)) ([7c3e376](https://github.com/hasansezertasan/keycast/commit/7c3e37639dcb57995929d0c4964c65f508d2340c))
* security and robustness hardening from code review ([#49](https://github.com/hasansezertasan/keycast/issues/49)) ([b924469](https://github.com/hasansezertasan/keycast/commit/b924469568f75309cd647af9e1bbbf56078c9163))


### Documentation

* add the Microsoft Store submission runbook to PACKAGING.md ([#41](https://github.com/hasansezertasan/keycast/issues/41)) ([52e3c1e](https://github.com/hasansezertasan/keycast/commit/52e3c1e34ffc3537e92acefdfdde0ffce4c3846a))
* ADR-016 keep keycast.updates in-tree until a second consumer ([#50](https://github.com/hasansezertasan/keycast/issues/50)) ([657c89f](https://github.com/hasansezertasan/keycast/commit/657c89f337446876a645aafaf3501ad1ae73a539))
* document Homebrew cask and formula install in README ([#31](https://github.com/hasansezertasan/keycast/issues/31)) ([98cf856](https://github.com/hasansezertasan/keycast/commit/98cf8563a475838dde2779f5e8fcd4a2c9f192fd))
* document Microsoft Store version mapping in PACKAGING.md ([#42](https://github.com/hasansezertasan/keycast/issues/42)) ([71fb652](https://github.com/hasansezertasan/keycast/commit/71fb65222769987b89053d9acef7e210d8c6f448))
* record Microsoft Store MSIX distribution decision in ADR-009 ([#37](https://github.com/hasansezertasan/keycast/issues/37)) ([8fad399](https://github.com/hasansezertasan/keycast/commit/8fad399212243fd7f84abb26c72f87d5b71d987b))
* record Scoop bucket distribution in ADR-008 ([#34](https://github.com/hasansezertasan/keycast/issues/34)) ([299864c](https://github.com/hasansezertasan/keycast/commit/299864ca689bb84a9f6c30ffc5e324963cc70129))
* start Store registration from Store Developer, not Partner Center ([#48](https://github.com/hasansezertasan/keycast/issues/48)) ([f1490b7](https://github.com/hasansezertasan/keycast/commit/f1490b76dccf0f5b5e6ef33b502c9e3a9704a4c1))
* surface Scoop install path in README and PROJECT_OVERVIEW ([#33](https://github.com/hasansezertasan/keycast/issues/33)) ([12b6d39](https://github.com/hasansezertasan/keycast/commit/12b6d39b6dfdb426bdee182793a8a5a97505cd7c))

## [0.2.0](https://github.com/hasansezertasan/keycast/compare/v0.1.0...v0.2.0) (2026-07-01)


### Features

* add application icons (.icns / .ico) ([#13](https://github.com/hasansezertasan/keycast/issues/13)) ([5701c2c](https://github.com/hasansezertasan/keycast/commit/5701c2c30855e41916aa7a3602613149247e4235))
* desktop release polish (version splash, download docs, cask automation) ([#11](https://github.com/hasansezertasan/keycast/issues/11)) ([4e07daf](https://github.com/hasansezertasan/keycast/commit/4e07dafa2d6c5dfa0991fb17afa9875345e62934))
* detect Scoop installs and auto-bump the Scoop bucket ([#25](https://github.com/hasansezertasan/keycast/issues/25)) ([fc97c22](https://github.com/hasansezertasan/keycast/commit/fc97c2264f35970039955d410ab0e189e97065ee))
* install-source-aware update check (notify, Phase 1) ([#18](https://github.com/hasansezertasan/keycast/issues/18)) ([ee49a2e](https://github.com/hasansezertasan/keycast/commit/ee49a2e3ac65c1e294812dbbeb2fd28b1f9461a3))
* **packaging:** styled drag-to-Applications macOS .dmg via dmgbuild ([#24](https://github.com/hasansezertasan/keycast/issues/24)) ([94e7843](https://github.com/hasansezertasan/keycast/commit/94e7843a39de4ea1335377d5a235b555a9f63ef9))
* **release:** rolling beta prerelease channel with stable-only cask/scoop ([#27](https://github.com/hasansezertasan/keycast/issues/27)) ([0fad5dc](https://github.com/hasansezertasan/keycast/commit/0fad5dca9d6028a4cc95eb5fcd20ed2b3490c130))
* ship a Windows installer (Inno Setup) alongside the zip ([#22](https://github.com/hasansezertasan/keycast/issues/22)) ([e9fbe16](https://github.com/hasansezertasan/keycast/commit/e9fbe16a2442aefdd986f53d68b4393d6655df00))
* show app icon when running keycast from source ([#14](https://github.com/hasansezertasan/keycast/issues/14)) ([b0da3a0](https://github.com/hasansezertasan/keycast/commit/b0da3a0bc3174a66487ab189259a9045ffd30ca2))


### Bug Fixes

* **display:** keep macOS overlay frameless and non-resizable under Tk 9 ([#15](https://github.com/hasansezertasan/keycast/issues/15)) ([18efed8](https://github.com/hasansezertasan/keycast/commit/18efed83a9732080da59968834af4031b40f479e))


### Documentation

* **adr-001:** record macOS signing/notarization deferral ([#21](https://github.com/hasansezertasan/keycast/issues/21)) ([8878ffd](https://github.com/hasansezertasan/keycast/commit/8878ffd7b224de565747a784ebb1ccdd96ded5a4))
* ADR-003 — Phase 2 self-update (proposed/deferred) ([#20](https://github.com/hasansezertasan/keycast/issues/20)) ([e7f15ea](https://github.com/hasansezertasan/keycast/commit/e7f15ea5a4de9cff45099b4776f15b40703444ab))
* ADR-007 prerelease/release-channel strategy (deferred) + operational reference ([#28](https://github.com/hasansezertasan/keycast/issues/28)) ([7729a0e](https://github.com/hasansezertasan/keycast/commit/7729a0e2f1df32c229c5c7f8d1b5e288a01c29d7))
* spec install-source-aware update check (ADR-002, [#9](https://github.com/hasansezertasan/keycast/issues/9)) ([#17](https://github.com/hasansezertasan/keycast/issues/17)) ([c84cf05](https://github.com/hasansezertasan/keycast/commit/c84cf051a6b1f4f3b5ee713aa57fd0795707326f))

## 0.1.0 (2026-06-23)


### Features

* add keycast keystroke and mouse visualizer ([#1](https://github.com/hasansezertasan/keycast/issues/1)) ([1c254d9](https://github.com/hasansezertasan/keycast/commit/1c254d9d7acbbafd03bbb2c7bcf44d488b76e548))
