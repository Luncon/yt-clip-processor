# Tasks

## 1. Visual scene structure

- [x] 1.1 Detect stable panel dividers and same-mode camera cuts on sampled frames; verify with synthetic frame and scene tests.
- [x] 1.2 Use panel bounds and all sampled face positions to build safe per-scene dual crops; verify profile and panel split tests.

## 2. Screen capture layout

- [x] 2.1 Classify a sustained corner camera over screen content before ordinary dual mode; verify with a Hasan-like frame and a conventional interview frame.
- [x] 2.2 Render screen content and corner camera in portrait with a readable content region; verify output geometry and a representative source segment.

## 3. Speaker focus and validation

- [x] 3.1 Use speech timing and conservative mouth motion to identify a likely active speaker; verify clear and ambiguous sequences.
- [x] 3.2 Apply speaker prominence only after stable evidence and verify that uncertain dual scenes retain equal panes.
- [x] 3.3 Check planned face coverage and widen unsafe crops; verify boundary cases in image-level tests.

## 4. Integration

- [x] 4.1 Run the full test suite and strict OpenSpec validation, and document the new layouts and their limits in README.

## Workflow follow-up

- Review representative real outputs before archiving the change.
