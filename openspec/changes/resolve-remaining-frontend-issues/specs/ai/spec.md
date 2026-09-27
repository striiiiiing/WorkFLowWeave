## ADDED Requirements

### Requirement: Discover models from a provider draft
The system SHALL discover upstream model IDs from a supplied AI provider configuration without persisting it. It SHALL use the existing credential resolver, validation, timeout, and error behavior, and SHALL prevent caching of the response.

#### Scenario: Unsaved provider
- **WHEN** a valid unsaved provider configuration is submitted for discovery
- **THEN** the system returns the upstream model IDs without creating or changing an AI resource

#### Scenario: Upstream failure
- **WHEN** model discovery fails
- **THEN** the system reports the failure instead of returning a fabricated model list
