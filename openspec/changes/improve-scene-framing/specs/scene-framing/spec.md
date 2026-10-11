# Spec Delta

## Purpose

Keeps people and useful context visible when landscape footage is reframed into portrait clips across different scene layouts.

## ADDED Requirements

### Requirement: Dual speaker framing
The processor SHALL show both speakers in separate portrait panes with enough context to retain a detected face near the source midpoint, when that face is fully present in the source frame.

#### Scenario: Profile near the split boundary
- **WHEN** a two-person scene contains a face that extends across the source midpoint
- **THEN** that speaker's pane includes the complete visible face with surrounding space

### Requirement: Wide shot framing
The processor SHALL enlarge the centered portion of a landscape wide shot within the portrait canvas instead of displaying the entire landscape frame at a small size.

#### Scenario: Wide landscape shot
- **WHEN** a 16:9 source frame is classified as wide
- **THEN** its centered content occupies at least 65% of the output height and the output remains 9:16
