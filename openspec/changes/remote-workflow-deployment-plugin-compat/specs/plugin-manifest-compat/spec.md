## Purpose

定义两种插件清单在迁移期的明确兼容边界，并把十个 QwenPaw 来源能力作为可独立发现、停用和重载的稳定清单，防止聚合包数量与能力数量混淆。

## ADDED Requirements

### Requirement: Plugin manifests are explicitly normalized

The system SHALL accept the existing LogAgent v1 manifest and the approved QwenPaw-style manifest through an explicit normalization step. The normalized result SHALL contain a stable identifier, version, capability kind, relative Python entry, and source metadata. A conflicting `type`/`kind`, unsafe entry, unsupported capability kind, or malformed required field SHALL fail discovery with a diagnostic tied to the package; it SHALL NOT be silently guessed.

#### Scenario: QwenPaw-style source manifest is accepted

- **WHEN** a package provides `id`, `name`, `version`, `type: "collector"`, and a relative `entry.backend`
- **THEN** discovery registers the package as a collector while retaining its display metadata and reports the normalized package ID

#### Scenario: Conflicting or unsafe manifest is rejected

- **WHEN** a manifest declares conflicting `type` and `kind`, an absolute/path-traversing backend, or an unknown type
- **THEN** no capability from that package is published and diagnostics identify manifest validation failure without importing the entry

### Requirement: The source inventory contains ten independently controllable capabilities

The deployed QwenPaw source inventory SHALL contain exactly the following ten source capability IDs, each owned by an independently reloadable source package: `qwenpaw_memos`, `qwenpaw_flomo`, `qwenpaw_halo`, `qwenpaw_karakeep`, `qwenpaw_siyuan`, `qwenpaw_tencent_docs`, `qwenpaw_activity`, `qwenpaw_codex`, `qwenpaw_claude`, and `qwenpaw_dida`. The notification channel package and built-in mock capability SHALL be reported separately and SHALL NOT change this source count.

#### Scenario: Complete ten-source inventory

- **WHEN** the remote backend discovers enabled plugins
- **THEN** the source capability set equals the ten IDs exactly, with no aggregate-only replacement and no duplicate owner

#### Scenario: One source is disabled or reloaded

- **WHEN** one source package is disabled or reloaded while the other nine remain enabled
- **THEN** only that source changes availability; the other nine and the notification channel remain published, and a failed package does not publish partial registrations

### Requirement: Plugin failures are observable and non-sending

The system SHALL expose per-package discovery or reload diagnostics and SHALL prevent a package with an invalid manifest, import error, declaration error, or missing dependency from sending data or being presented as healthy.

#### Scenario: Broken package is isolated

- **WHEN** one source package fails discovery
- **THEN** its capability is unavailable with a reason and the remaining valid packages continue to operate without a fabricated success record
