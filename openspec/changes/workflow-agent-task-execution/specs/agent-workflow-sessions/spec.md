## ADDED Requirements

### Requirement: Unified Workflow source session creation

The existing Agent session creation endpoint SHALL accept an optional Workflow Session ID and optional Task ID. The server SHALL derive the session kind from their presence: `standalone`, `workflow_continue`, or `workflow_subtask`.

#### Scenario: Continue a Workflow result

- **WHEN** a session is created with a Workflow Session ID and no Task ID
- **THEN** the server creates a `workflow_continue` session from the final Workflow result
- **AND** it uses the existing default model, enabled tools and continuation prompt behavior

#### Scenario: Create a Workflow subtask session

- **WHEN** a session is created with a Workflow Session ID and a Task ID
- **THEN** the server creates a `workflow_subtask` session from the selected analysis result or the reserved `final` aggregate result
- **AND** it records both source identifiers in the session metadata

### Requirement: Optional continuation of subtask sessions

A `workflow_subtask` session SHALL remain a normal Agent Session after its first turn. Users MAY send later messages through the existing Agent message API, and those messages SHALL remain scoped to the Agent Session without updating the parent Workflow result.

#### Scenario: Continue a displayed subtask

- **WHEN** a user sends a later message to a displayed Workflow subtask session
- **THEN** the existing Agent transcript and checkpoint behavior handle the new turn
- **AND** the parent Workflow's saved analysis or aggregate result is unchanged

### Requirement: Session metadata compatibility

Agent session listings, session details and `session.created` history SHALL expose the derived session kind, Workflow Session ID and optional Task ID. Existing sessions without the new fields SHALL remain readable with a derived compatible kind.

#### Scenario: Restore an existing session

- **WHEN** a stored session predates session kind and Task ID metadata
- **THEN** a session with a Workflow source is exposed as `workflow_continue`
- **AND** a session without a Workflow source is exposed as `standalone`
