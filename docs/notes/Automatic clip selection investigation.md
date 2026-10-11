# Automatic clip selection investigation

The existing `find_hook_clips` first rejects windows with no political or
conflict keyword score. Face presence can also reject an entire window before
clip quality is measured. This can miss ordinary language that carries a
strong exchange. The later score still rewards keyword categories heavily.

The source monitor now records repeat view snapshots, but has no connection to
media processing. The automatic workflow should select a rising, long enough
source when requested; build candidates across the full transcript; select
distinct, self-contained clips; and save the decision evidence. It should
return fewer than requested when the available footage is weak.

See [automate-clip-selection](../../openspec/changes/automate-clip-selection/proposal.md).
