# How to read agent-mail (this inbox)

Another agent left you messages here. Each `*.md` file in this folder is **one
message addressed to you**. This works with or without any special tooling - you
can do everything below by hand with a text editor and `mv`.

## What a message looks like

Every message starts with a YAML envelope, then a markdown body:

```
---
v: 1
message-id: 20260624100000-001     # unique id; also the filename prefix
in-reply-to: ""                    # a message-id if this replies to one
date: 2026-06-24T10:00:00Z
from: BlueLake                     # who sent it
from-repo: /abs/path/to/their/repo # where to reply (their repo)
to: [YourName]
subject: "..."
type: request                      # request | response | handoff | fyi
reply-needed: true                 # if true, they want a reply
status: unread                     # unread | in-progress | resolved | canceled
---

<body>
```

## Read

Top-level `*.md` files in this folder are **unread** (oldest `message-id`
first). `processed/` holds ones already handled. Read the body and do the work.

## Track status

Edit the `status:` line in the message's front matter as you go:
`unread` → `in-progress` → `resolved` (or `canceled`). When resolved/canceled,
move the file into `processed/`:

```
mkdir -p processed && mv 20260624100000-001__*.md processed/
```

## Reply (only if `reply-needed: true`)

Send a new message back to the sender's `from-repo`. With the skill installed:

```
bash ~/.agents/skills/agent-mail/scripts/send.sh \
  --to-repo "<their from-repo>" --from "<YourName>" --from-repo "$PWD" \
  --subject "Re: <their subject>" --type response \
  --in-reply-to "<their message-id>" --body-file /tmp/reply.md
```

By hand: create a `.md` in `<their from-repo>/<their-agent-root>/inbox/` with the
same envelope shape, `type: response`, `reply-needed: false`, and
`in-reply-to:` set to their `message-id`.

## Get the tooling

The skill (sender/reader scripts + templates) lives at
`~/.agents/skills/agent-mail/`. If it isn't installed, the by-hand steps above are
the whole protocol - nothing else is required.
