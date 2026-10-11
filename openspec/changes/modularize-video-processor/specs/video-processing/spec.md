# Spec Delta

## Purpose

The video processor turns a YouTube URL or local video into short clips using either uniform intervals or selected hook moments.

## ADDED Requirements

### Requirement: Supported sources
The CLI SHALL accept a local video path or a single YouTube video URL and place completed clips under the selected output directory.

#### Scenario: Local video
- **WHEN** a user provides an existing local video path
- **THEN** the processor uses that file as its source and writes completed clips to the output directory

#### Scenario: YouTube video
- **WHEN** a user provides a valid YouTube video URL
- **THEN** the processor downloads that video and writes completed clips to the output directory

### Requirement: Clip modes
The CLI SHALL support uniform length clips and transcript selected hook clips with optional vertical reframing and burned subtitles.

#### Scenario: Uniform clips
- **WHEN** hook mode is not requested
- **THEN** the processor cuts the source into consecutive clips using the configured length

#### Scenario: Hook clips
- **WHEN** a positive hook count is requested
- **THEN** the processor transcribes the source, ranks candidates, and produces up to that many selected clips

### Requirement: Safe output handling
The processor SHALL remove only its own intermediate files and SHALL preserve completed clips and unrelated files in the output directory.

#### Scenario: Fresh run
- **WHEN** a user requests a fresh run in an output directory containing unrelated files
- **THEN** those unrelated files remain in place

### Requirement: Validated options
The CLI SHALL reject invalid numeric options and incompatible mode combinations before processing media.

#### Scenario: Invalid clip length
- **WHEN** a user sets clip length to zero or less
- **THEN** the CLI reports an argument error without starting processing

#### Scenario: Hook mode without transcription
- **WHEN** a user requests hooks and disables transcription
- **THEN** the CLI reports an argument error without starting processing

### Requirement: Conditional dependencies
The processor SHALL require optional software only when the selected workflow uses it.

#### Scenario: Local copy path
- **WHEN** a local source is processed without transcription or vertical reframing
- **THEN** the run does not require YouTube download, transcription, or face detection packages

### Requirement: Diverse hook selection
The processor SHALL avoid selecting clips with substantially repeated transcript topics, even when their time ranges do not overlap.

#### Scenario: Repeated topic
- **WHEN** multiple separated candidates contain substantially the same topic words
- **THEN** the processor selects at most one of those candidates

### Requirement: Portrait source handling
The processor SHALL produce a valid vertical clip when the source is narrower than a 9:16 aspect ratio.

#### Scenario: Narrow portrait fallback
- **WHEN** face tracking is unavailable for a narrow portrait source
- **THEN** the fallback render succeeds without requesting a crop larger than the source frame

### Requirement: Efficient local uniform processing
The processor SHALL read a local source without first duplicating it in the work directory and SHALL render subtitles while producing each final uniform clip.

#### Scenario: Subtitled uniform clips
- **WHEN** a local source is processed into multiple uniform clips with subtitles
- **THEN** each final clip has subtitles at the corresponding local timestamps without a full-video subtitle render
