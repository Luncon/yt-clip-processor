# Source monitoring

## ADDED Requirements

### Requirement: Configured sources
The monitor SHALL poll recent public uploads for the four pilot YouTube channels, and SHALL allow the channel handles to be configured.

#### Scenario: Default source list
- **WHEN** the monitor runs without a source configuration
- **THEN** it polls Tucker Carlson, Candace Owens, HasanAbi, and Fox News

### Requirement: Repeatable observations
The monitor SHALL persist each discovered video's identity and dated public statistics without persisting the API key.

#### Scenario: Repeated polling
- **WHEN** the same video is polled twice
- **THEN** both observations remain available and the video record is not duplicated

### Requirement: Performance report
The monitor SHALL report observed view growth per hour only when two observations exist, and SHALL distinguish missing statistics from zero.

#### Scenario: First observation
- **WHEN** a video has one observation
- **THEN** its view growth is reported as unavailable

#### Scenario: Second observation
- **WHEN** a video has two observations at different times
- **THEN** its view growth is computed from the difference in views divided by elapsed hours

### Requirement: Explicit setup errors
The monitor SHALL report missing API credentials and unavailable configured channels as actionable errors.

#### Scenario: Missing credential
- **WHEN** polling is requested without `YOUTUBE_API_KEY`
- **THEN** the CLI explains how to provide the key

#### Scenario: Unavailable channel
- **WHEN** a configured handle resolves to no channel
- **THEN** the monitor names that handle in an error
