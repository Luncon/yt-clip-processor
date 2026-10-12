# Automatic clip selection

## ADDED Requirements

### Requirement: Broad candidate discovery
The processor SHALL consider complete transcript windows across the video without requiring political keywords or a visible face at the beginning.

#### Scenario: Plain-language exchange
- **WHEN** a source contains a complete, clear exchange without topic keywords
- **THEN** it remains eligible for automatic clip selection

### Requirement: Quality and diversity
The processor SHALL choose up to the requested number of distinct clips with clear boundaries and sufficient transcript content, and SHALL skip weak candidates.

#### Scenario: Insufficient quality
- **WHEN** fewer candidates pass the quality threshold than requested
- **THEN** only passing candidates are rendered

#### Scenario: Repeated topic
- **WHEN** two high-scoring candidates overlap or substantially repeat the same transcript content
- **THEN** at most one is selected

### Requirement: Semantic ranking when available
The processor SHALL optionally assess candidate meaning with the configured model service while preserving a local selection path if that service is unavailable.

#### Scenario: Model assessment succeeds
- **WHEN** `GROQ_API_KEY` is configured and a valid semantic score is returned
- **THEN** semantic and structural scores both contribute to candidate ranking

#### Scenario: Model assessment fails
- **WHEN** the model service fails or returns invalid scores
- **THEN** automatic selection continues using local structural scores

### Requirement: Monitored source input
The CLI SHALL optionally choose a recent, long enough video using positive view growth from the monitor's saved observations.

#### Scenario: Rising upload
- **WHEN** `--from-monitor` is used and an eligible video has repeat observations
- **THEN** the selected video URL is passed to the existing processing pipeline

#### Scenario: No usable source
- **WHEN** no monitored video is recent, long enough, and rising
- **THEN** the CLI exits with an actionable error before downloading media

### Requirement: Selection evidence
The processor SHALL save source and clip selection reasons with timestamps and render outcomes in the output directory.

#### Scenario: Automatic run
- **WHEN** automatic clip mode completes
- **THEN** a JSON manifest lists selected clip ranges, scores, reasons, and saved files

### Requirement: Existing option compatibility
The CLI SHALL accept `--hooks` as an alias for the automatic clip count during migration.

#### Scenario: Legacy invocation
- **WHEN** a user supplies `--hooks 3`
- **THEN** the new selector requests up to three automatic clips
