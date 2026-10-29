# Phonetic transcripts

A compaction of a speech-to-text section applies these rules first. Speech-to-text capture arrives as one run-on block with no speaker labels, and its errors are phonetic, so the words sound right but read wrong.

- Split the block by topic before scanning, so decisions and actions don't stay buried in the run-on.
- Before calling a phrase garbled, say it aloud and find what it rhymes with or sounds like, ranked by fit with the topic: a system, a tool, a file name, a command, a teammate on the roster. The usual errors are that product names split into common words, a file name comes out as a person's name, and an acronym comes out as a word ("sequel" for SQL, "get folder" for Git folder, "yamel" for YAML).
- Prefer the project's own vocabulary: the roster, the systems in the code notes, and terms from sibling sections. Look each candidate up in the vault's graph (`entity`, `search`) rather than reading those notes whole.
- A reading that changes meaning is only a candidate. Mark it as inferred and raise it at the operator gate.
- Resolve people against whatever roster or user legend the project or the operator provides. A spoken first name maps to the alias whose initials and role fit: when the first name starts with the alias's first letter and the role matches what was said, that alias is the candidate. Mark it `(?)` unless the text confirms it. A name with no roster match stays as heard, marked `(?)`.
- Attribute a speaker only from cues in the text: a name used or addressed, first-person ownership ("my slides", "I'll run it"), or who presents which part. When it stays unclear, say so rather than assigning it.
