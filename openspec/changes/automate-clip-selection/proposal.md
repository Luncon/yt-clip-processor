## Why

The current hook mode uses political keyword matches as a candidate gate and score. It misses compelling ordinary-language moments and offers little evidence for automatic selection. Users want clips selected without watching a review queue.

See [investigation](../../../docs/notes/Automatic%20clip%20selection%20investigation.md).

## What Changes

- Replace the keyword-gated ranker with broad transcript candidate generation around sentence and pause boundaries, followed by structural quality scoring and diversity selection.
- Add an optional monitored-source input that chooses a rising, sufficiently long recent upload from saved performance snapshots.
- Save a machine-readable decision manifest with source and clip timestamps, scores, and reasons.
- Preserve the existing `--hooks` spelling as an alias while introducing `--auto-clips`; remove the old keyword signal module.

## Scope

This change automates source and clip selection and rendering. It does not publish to TikTok or claim access to private YouTube retention metrics. The first version uses observed source growth and transcript quality proxies; posted-clip outcome learning is a later capability.
