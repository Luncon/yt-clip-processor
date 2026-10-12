# Spec Delta

## Purpose

Keeps speakers and important visual material visible when landscape interviews, news panels, and screen captures are converted into portrait clips.

## ADDED Requirements

### Requirement: Panel-aware scene boundaries
The processor SHALL separate sustained visual panels and camera cuts before fixing portrait crops. A crop SHALL stay within a detected panel unless doing so would remove part of the intended subject visible in the source.

#### Scenario: News split screen
- **WHEN** a stable divider separates two speaker panels
- **THEN** each pane frames the speaker from its own panel without including pieces of the other panel

#### Scenario: Same-mode camera cut
- **WHEN** a camera cut changes the subject or panel arrangement without changing the face count
- **THEN** the processor recomputes the crop for the new shot

### Requirement: Screen capture with corner camera
The processor SHALL offer a portrait layout that shows the principal screen content and a sustained small corner camera together, even when another face appears in the screen content.

#### Scenario: Streamer commentary
- **WHEN** the source shows a large screen region, a chat column, and a corner host camera
- **THEN** the output shows the screen region as primary content and the host camera as a smaller secondary view

#### Scenario: No reliable screen region
- **WHEN** the corner face is detected but the screen region cannot be determined confidently
- **THEN** the output uses a safe wide content view with the corner face still visible

### Requirement: Conservative speaker focus
The processor SHALL use available speech timing and visual speaker motion to favor a likely active speaker only when the estimate is confident. It SHALL keep stable multi-person framing when the estimate is ambiguous.

#### Scenario: Clear speaker change
- **WHEN** speech and visible mouth motion consistently favor a different panel speaker
- **THEN** the layout gives that speaker greater prominence after a short hold period

#### Scenario: Uncertain speaker
- **WHEN** speakers overlap or motion evidence is weak
- **THEN** the layout continues to show the relevant speakers without switching focus

### Requirement: Face coverage fallback
The processor SHALL check planned crops against sampled detected face bounds and widen or change the layout when a crop would trim the intended visible face.

#### Scenario: Profile near crop edge
- **WHEN** a visible face extends beyond a planned speaker crop
- **THEN** the rendered pane includes the full visible face with a margin when the source frame permits it
