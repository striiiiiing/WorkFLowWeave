## ADDED Requirements

### Requirement: Continue the latest workflow result
The workflow list SHALL offer a continuation action in each workflow card's action row. A valid configured default Agent model SHALL be used directly; otherwise the user SHALL be able to select an available model.

#### Scenario: Valid default model
- **WHEN** a workflow has a continuable latest result and the browser default model is available
- **THEN** the action creates an Agent session from that result and opens it without requiring model selection

#### Scenario: Missing or stale default model
- **WHEN** the default model is missing or no longer available
- **THEN** the action presents the available models for explicit selection

### Requirement: Discover provider models from the current form
Clicking the model name input SHALL request model discovery using the current provider form values, including values not yet saved. Discovery SHALL not add a model until the user chooses to add it.

#### Scenario: Changed connection
- **WHEN** the user changes the address or credential and clicks the model name input
- **THEN** discovery uses the changed connection and cannot display an older request's results afterward

### Requirement: Display actual Agent reasoning
When an Agent event contains reasoning text, the transcript SHALL show it separately from the final answer, collapsed by default unless the user's display setting requests expansion. Events without reasoning text SHALL not create an empty reasoning block.

#### Scenario: Stream and replay
- **WHEN** reasoning arrives during a turn and the same session is later reloaded
- **THEN** the actual reasoning remains available in both views with the configured default expansion state
