# Project notes

Open this repository's **root folder** as an Obsidian vault. Keep project notes
under `docs/notes/`; this lets notes link to code and OpenSpec files using
ordinary Markdown links. Obsidian is optional: every note remains readable in
GitHub and a text editor. Vault settings in `.obsidian/` are personal and are
not needed to use these notes.

In Obsidian, choose **Open folder as vault** and select this repository's root.
Enable the built-in **Templates** plugin, then set its **Template folder
location** to `docs/notes/templates`. Create new notes in `docs/notes/` and
insert the Idea or Investigation template as needed.

## Start here

- [Prototype baseline](Prototype%20baseline.md) records what the current code
  appears to do and what still needs verification.
- [Model workflow smoke test](Model%20workflow%20smoke%20test.md) records the
  real Whisper and MediaPipe integration run and its limits.
- [Debate scene transition test](Debate%20scene%20transition%20test.md) records
  the real news footage layout test and the wide-shot finding.
- [Three source workflow test](Three%20source%20workflow%20test.md) records the
  interview, portrait, and podium speech runs and their fixes.
- [Inbox](Inbox.md) holds quick ideas before they deserve a full note.
- [Idea template](templates/Idea.md) captures a problem and a proposed outcome.
- [Investigation template](templates/Investigation.md) captures evidence from
  code or experiments.

## From note to specification

1. Capture a thought in the inbox. Create a note from a template when it needs
   more detail. Link to code, output, or other evidence where possible.
2. Discuss the intended behavior and resolve open questions. A note is working
   material, so an idea in a note is not a product requirement.
3. For a significant change, create an OpenSpec change with the CLI or the
   `openspec-propose` workflow. Put the problem and scope in `proposal.md`,
   observable behavior in delta `specs/`, consequential implementation choices
   in `design.md`, and verifiable work in `tasks.md`.
4. Link the note to the change and the change back to the note. Review the
   relevant existing specs before implementing. After implementation and
   verification, archive the change so the durable capability spec is updated.

The durable requirements live in `openspec/specs/`. Active change artifacts live
in `openspec/changes/`. Keep each fact in its proper place rather than copying
whole notes into specs.

## Useful OpenSpec commands

Run these from the repository root:

```sh
openspec list
openspec list --specs
openspec new change <short-name>
openspec status --change <short-name>
openspec validate <short-name>
```

Use `openspec list` to see work in progress and `openspec list --specs` to see
durable capabilities. The change name should describe the outcome, such as
`improve-hook-selection`. Do not create an OpenSpec change directory by hand.
