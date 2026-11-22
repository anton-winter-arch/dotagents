# SPEC - web access and downloads for agents

Eval fixture: a stand-in spec so trigger cases that name it find a file.

## Goal

Agent web requests are paced per host and downloaded files are scanned before use.

## Acceptance

- [ ] Requests to one host are spaced by a fixed delay.
- [ ] A refused host is not contacted again in the session.
