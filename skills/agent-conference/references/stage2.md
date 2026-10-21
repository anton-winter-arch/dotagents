# Blind review

A panel of models each answered the question below independently. Their answers follow, labeled {{LABELS}}. The labels are shuffled and the authors are hidden; one of them may be yours. Review them on accuracy and insight alone. Do not try to guess authorship and do not favor an answer because it reads like your own.

The files the answers refer to are below the answers. Check claims against them. {{TOOLS}} {{REDACTION}}

# Question

{{QUESTION}}

# Files

{{FILES}}

# Answers

{{RESPONSES}}

# What to return

First, write two to four sentences on each answer: what it gets right, what it gets wrong, and what it alone contributes. Every error you name must cite the file and line that shows it; an error you did not verify against the files is not an error, so leave it out. The chair reads the JSON block below, not these paragraphs, so put the substance there.

Then rank all {{N}} answers from best to worst. End your message with exactly one fenced JSON block and nothing after it:

```json
{"ranking": ["<best label>", "...", "<worst label>"], "rationale": {"A": "one sentence on why A sits where it does", "B": "..."}, "errors_found": {"A": "each verified error in A, with file:line", "B": "..."}, "disagreements": "where the answers contradict each other and which side the files support, with file:line"}
```

The `ranking` list must hold every label exactly once. A label with no verified error gets the string `none` under `errors_found`.
