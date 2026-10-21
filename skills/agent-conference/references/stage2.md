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

Return exactly one fenced JSON block and nothing else. The chair reads the block's fields and never any prose around it, so everything you have to say goes inside. Judge every answer before you rank; the keys are ordered so the ranking comes last.

```json
{"rationale": {"A": "two or three sentences: what A gets right, what it gets wrong, and what it alone contributes", "B": "..."}, "errors_found": {"A": "each verified error in A, with file:line, or none", "B": "..."}, "disagreements": "where the answers contradict each other and which side the files support, with file:line", "ranking": ["<best label>", "...", "<worst label>"]}
```

Every error you name must cite the file and line that shows it; an error you did not verify against the files is not an error, so leave it out. The `ranking` list must hold all {{N}} labels exactly once. A label with no verified error gets the string `none` under `errors_found`.
