#!/usr/bin/env python3
"""The vault pattern layer: topology, ontology, taxonomy, in one place.

Several skills match the same structures with hand-rolled regexes. When a shape drifts they
drift apart silently, and the first symptom is a sweep quietly returning nothing. This is
the matcher of record; the skill's scripts import it rather than reinventing it. The copy
lives beside the scripts that use it, so the skill depends on nothing outside its folder.

Every rule here is deterministic and carries a measured hit count against a live corpus.
Nothing here calls a model, writes a file, or touches the network.

The one rule worth stating up front, because it is the one that was measured wrong first:
SPEAKER MATCHING IS ROSTER-GATED, NEVER SHAPE-GATED. `^A ` looks exactly like a speaker
turn and is usually the English word "I" or a SQL keyword. Over the notes corpus, `I`
opens 167 lines, `The` 91, `FROM` 20 -- each outranking most real teammates. The roster is
declared in the north-star note and reconciled against the corpus; it is never derived by
frequency, because frequency cannot tell a teammate from an advisor who is not on the
project at all.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from functools import lru_cache
from pathlib import Path

# --- project profile ----------------------------------------------------------
#
# Nothing in this module names a project. The structural families, the generic authority
# ranks and the matching machinery are the same for every vault; what differs is one
# project's authored-note prefix, its north-star filename, and the per-document roles its
# operator declared. Those live with the project, and every entry point that needs them
# takes a `project` argument: an alias, or a path to a folder under PROJECTS/.
#
# The profile is `vault-profile.json` inside the project's folder:
#
#     {"prefix": "acme",
#      "north_star": "acme-01-north-star.md",
#      "authority": {"<filename>": {...}},
#      "family_authority": {"<prefix>": {...}},
#      "doc_roles": {"<filename>": {"kind": "told|ancestor|governing", "note": "..."}}}
#
# Absent or unreadable, every function below falls back to generic behavior rather than
# failing: an unrecognized document comes back unranked, which is the surfacing default.

def _projects_dir() -> str:
    """The corpus folder name, overridable for a non-standard layout.

    The override is a NAME, not a relocation: an absolute value or one carrying `..`
    would move the base that `profile_path` confines against, which would make the
    confinement guarantee below false whenever the variable happened to be set."""
    declared = os.environ.get('VAULT_PROJECTS_DIR', '')
    candidate = Path(declared)
    if not declared or candidate.is_absolute() or '..' in candidate.parts:
        return 'PROJECTS'
    return declared


PROJECTS_DIR = _projects_dir()
PROFILE_NAME = 'vault-profile.json'
EMPTY_PROFILE = {'prefix': None, 'north_star': None,
                 'authority': {}, 'family_authority': {}, 'doc_roles': {}}


def profile_path(project: str | Path | None, root: str | Path = '.') -> Path | None:
    """Where a project's profile lives, or None when the project cannot be resolved.

    `project` is a folder path under PROJECTS/, or an alias that names one. An alias
    matching more than one folder root is ambiguous and resolves to nothing, because
    silently picking one would attribute a document to the wrong project.

    `project` is untrusted input. Everything resolves inside PROJECTS/ or not at all:
    a profile is not inert data -- `authority()` merges it over the built-in ranks and
    its free text reaches the generated KG config -- so an absolute path or a `..` walk
    outside the tree returns None rather than loading."""
    if not project:
        return None
    try:
        base = (Path(root).expanduser() / PROJECTS_DIR).resolve()
    except OSError:
        return None
    if not base.is_dir():
        return None

    def confined(candidate: Path) -> Path | None:
        try:
            resolved = candidate.resolve()
        except OSError:
            return None
        return candidate if base == resolved or base in resolved.parents else None

    direct = Path(project)
    if direct.is_dir():
        inside = confined(direct)
        return inside / PROFILE_NAME if inside else None
    if direct.is_absolute() or '..' in direct.parts:
        return None
    matches = sorted(d for d in base.glob(f'{project}*') if d.is_dir() and confined(d))
    roots = {re.split(r'[-_]', d.name, maxsplit=1)[0] for d in matches}
    if len(roots) != 1:
        return None
    for d in matches:
        if (d / PROFILE_NAME).is_file():
            return d / PROFILE_NAME
    return matches[0] / PROFILE_NAME if matches else None


# A key name matching is not enough: every consumer below indexes, merges or measures
# these values, so a JSON list where a mapping belongs raises at the use site rather
# than here. Anything of the wrong shape is dropped back to its empty default.
_PROFILE_SHAPES = {'prefix': str, 'north_star': str,
                   'authority': dict, 'family_authority': dict, 'doc_roles': dict}


def _well_shaped(key: str, value) -> bool:
    expected = _PROFILE_SHAPES[key]
    if not isinstance(value, expected):
        return False
    if expected is dict:
        return all(isinstance(v, dict) for v in value.values())
    return True


@lru_cache(maxsize=16)
def _load(path_str: str) -> tuple:
    try:
        data = json.loads(Path(path_str).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return tuple(sorted(EMPTY_PROFILE.items(), key=lambda kv: kv[0]))
    if not isinstance(data, dict):
        return tuple(sorted(EMPTY_PROFILE.items(), key=lambda kv: kv[0]))
    declared = {k: v for k, v in data.items() if k in EMPTY_PROFILE and _well_shaped(k, v)}
    merged = {**EMPTY_PROFILE, **declared}
    return tuple(sorted(((k, json.dumps(v, sort_keys=True)) for k, v in merged.items())))


def load_profile(project: str | Path | None, root: str | Path = '.') -> dict:
    """A project's declared profile, or the empty one. Never raises."""
    try:
        path = profile_path(project, root)
        if not path or not path.is_file():
            return dict(EMPTY_PROFILE)
        return {k: json.loads(v) for k, v in _load(str(path))}
    except (OSError, ValueError, TypeError, NotImplementedError):
        return dict(EMPTY_PROFILE)

# --- topology -----------------------------------------------------------------

# `## 2026-08-20` and `## 2026-08-20-AB-AND-Z` are both common (20 and 85). The suffix
# carries meaning -- STANDUP-CLIENT, AB-STORY-<id> -- so it is captured, not discarded.
DATE_H2 = re.compile(r'^## (\d{4}-\d{2}-\d{2})(?:-(.+))?$')

# The same heading read by its first ten characters only: `## 2026-08-20 - a title` and
# `## 2026-08-20 STANDUP` match here and not above. `notes-learnings.md` writes its entries
# that way. Section identity still keys on DATE_H2, so a consumer that lists a heading only
# this pattern matches reports it as non-canonical rather than keying it.
DATE_H2_LOOSE = re.compile(r'^## (\d{4}-\d{2}-\d{2})(?!\d)(.*)$')

# NOT uniformly H3. user-stories.md has features at H2 and stories at H3;
# user-stories-active-work.md has all 15 stories at H2; user-stories-backlog.md mixes both
# levels inside one file. Assuming H3 misses 23 of 62 headings.
WORK_ITEM = re.compile(r'^(#{2,3}) (STORY|FEATURE|BUG|TASK)-(\d+)\b[\s:-]*(.*)$')

# Two spellings in the corpus: 18 canonical, 2 with the colon inside the bold.
NOTE_MARK = re.compile(r'^\*\*NOTE\*\*:\s*(.*)$|^\*\*NOTE:\*\*\s*(.*)$', re.IGNORECASE)

# Structural only. A project's authored-note prefix is a fourth family and comes from its
# profile, never from this tuple.
FAMILIES = ('code', 'docs', 'notes', 'user-stories')

# Turns needed before an UNDECLARED candidate is worth reporting as a possible person.
# Measured: every real alias clears it (EF, the rarest, has 3); every stray one-word line
# in the corpus -- Nope, Done, Papa, WIP, DBT, Task, Easy, GL, Hey -- sits at 2 or below.
MIN_TURNS = 3

# Regenerated wholesale by the build; they are outputs, not corpus.
SCAFFOLDING = {'index.md', 'log.md', 'decisions.md', 'glossary.md', 'README.md'}


def family(name: str, project: str | Path | None = None,
           root: str | Path = '.') -> str | None:
    """Filename prefix family, or None for scaffolding and anything unrecognized.

    Pass `project` to recognize that project's authored-note prefix as a family too."""
    stem = Path(name).name
    if stem in SCAFFOLDING:
        return None
    prefix = load_profile(project, root).get('prefix') if project else None
    families = tuple(FAMILIES) + ((prefix,) if prefix else ())
    for f in sorted(families, key=len, reverse=True):
        if stem.startswith(f + '-'):
            return f
    return None


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Flat key -> raw-string frontmatter, plus the body. List values collapse to ''."""
    m = re.match(r'^---\n(.*?)\n---\n?', text, re.S)
    if not m:
        return {}, text
    fm = {}
    for line in m.group(1).split('\n'):
        km = re.match(r'^([A-Za-z_][\w-]*):\s?(.*)$', line)
        if km:
            fm[km.group(1)] = km.group(2).strip()
    return fm, text[m.end():]


def lines_of(text: str) -> list[str]:
    """Lines split on `\\n` only, the way grep and sed number them.

    `str.splitlines()` also breaks on U+2028, U+2029, U+0085 and the \\x0b, \\x0c and
    \\x1c-\\x1e controls. That shifts every later line number away from what grep and sed
    report, and it hides those characters from any check that reads a section body."""
    lines = text.split('\n')
    if lines and lines[-1] == '':
        lines.pop()
    return lines


def date_sections(path: Path, loose: bool = False) -> list[dict]:
    """Every dated H2 in a file, with its line range and body.

    Ranges are 1-indexed and end-exclusive. A consumer that stores a range and reads it
    later MUST re-verify the heading at `start` first: the operator edits raw mid-session,
    and a stale range addresses different bytes without erroring.

    `loose=True` also returns headings only DATE_H2_LOOSE matches, with `canonical` False
    and the rest of the heading, stripped of leading separators, as the suffix.
    """
    lines = lines_of(path.read_text(encoding='utf-8'))
    marks = []
    for i, line in enumerate(lines):
        if m := DATE_H2.match(line):
            marks.append((i, m.group(1), m.group(2) or '', True))
        elif loose and (m := DATE_H2_LOOSE.match(line)):
            marks.append((i, m.group(1), m.group(2).strip(' -:'), False))
    out, seen = [], {}
    for start, d, suffix, canonical in marks:
        end = len(lines)
        for j in range(start + 1, len(lines)):
            if lines[j].startswith('## '):
                end = j
                break
        # Occurrence ordinal. Headings are hand-written and duplicate: the corpus already
        # has `## 2026-07-16-WORKING-SESSION` twice in one file. Without this the two
        # collapse to one key and whichever is read last silently wins.
        seen[(d, suffix)] = seen.get((d, suffix), 0) + 1
        out.append({'file': path.name, 'date': d, 'suffix': suffix,
                    'ord': seen[(d, suffix)], 'canonical': canonical,
                    'start': start + 1, 'end': end,
                    'body': '\n'.join(lines[start:end])})
    return out


def section_key(file: str, date: str, suffix: str, ord: int = 1) -> str:
    """Stable identity for a dated section. NEITHER DATE NOR DATE+SUFFIX IS UNIQUE.

    `notes-chat-notes-client.md` carries three sections dated 2026-08-20 (`-ALL`,
    `-AB-AND-Z`, `-CD-AND-Z`), so a `file#date` key collapses them into one.

    And the suffix does not save it: `notes-meeting-notes.md` has
    `## 2026-07-16-WORKING-SESSION` twice, for two genuinely different sessions -- a
    1,150-byte DBT progress update and a 7,001-byte ways-of-working discussion. Headings
    are hand-written, so uniqueness cannot be assumed from them at all. The occurrence
    ordinal is what makes the key total.
    """
    base = f'{Path(file).name}#{date}' + (f'-{suffix}' if suffix else '')
    return base if ord == 1 else f'{base}~{ord}'


def section_hash(sec: dict) -> str:
    """Short content hash of one section's body. A backup and its verify step carry it, so
    a section edited after it was inspected is caught."""
    return hashlib.sha256(sec['body'].encode('utf-8')).hexdigest()[:12]


def find_by_key(raw: Path, key: str) -> dict | None:
    """The section a `file#date-suffix~N` key names in raw, or None when no section does."""
    path = Path(raw) / key.split('#', 1)[0]
    if not path.is_file():
        return None
    for sec in date_sections(path, loose=True):
        if sec['canonical'] and section_key(sec['file'], sec['date'], sec['suffix'],
                                            sec['ord']) == key:
            return sec
    return None


def verify_range(path: Path, start: int, date: str, suffix: str = '') -> bool:
    """True when `start` still holds the SAME dated heading a caller recorded earlier.

    Line numbers are a transient address, never a durable one: inserting a section shifts
    everything below it. Callers store the heading and re-find it; this only answers
    "is the cached position still valid", and a False means re-read, not repair.

    The suffix is part of the identity. Without it, a file with several sections on one
    date verifies against the wrong one.
    """
    lines = lines_of(path.read_text(encoding='utf-8'))
    if not 1 <= start <= len(lines):
        return False
    m = DATE_H2.match(lines[start - 1])
    return bool(m and m.group(1) == date and (m.group(2) or '') == suffix)


JOINERS = {'AND', 'WITH', 'TO', 'RE'}
EVERYONE = 'ALL'


def parse_suffix(suffix: str, people: dict) -> dict:
    """Who was in a thread, and what it was about, from the heading suffix.

    Several dated sections share one day because several conversations happened that day,
    and the suffix says which. `2026-08-20-AB-AND-Z` is a thread between two people;
    `2026-08-20-ALL` is the group; `2026-08-18-Z-STORY-<id>` is a review; and
    `2026-08-21-STANDUP-INTERNAL` is a meeting type. Roster-gating the tokens is what
    separates the people from the topic, exactly as it does for speaker turns.

    This is what makes "who discussed this, and who would know" answerable: participants
    are attached to the section, and the section is attached to whatever it names.
    """
    work = re.findall(r'((?:STORY|FEATURE|BUG|TASK)-\d+)', suffix)
    rest = re.sub(r'(?:STORY|FEATURE|BUG|TASK)-\d+', '', suffix)
    tokens = [t for t in rest.split('-') if t]

    participants, topic = [], []
    for t in tokens:
        if t in people:
            participants.append(t)
        elif t in JOINERS:
            continue
        elif t == EVERYONE:
            continue        # `ALL` names no one. Who actually spoke is in the body.
        else:
            topic.append(t)

    if work:
        kind = 'review'
    elif any(t in ('STANDUP', 'MEETING', 'SYNC', 'REFINEMENT', 'PLANNING',
                   'WORKING', 'SESSION') for t in topic):
        kind = 'meeting'
    elif participants and not topic:
        kind = 'thread'
    else:
        kind = 'topic'

    return {'participants': sorted(set(participants)), 'work_items': work,
            'topic': '-'.join(topic) or None, 'kind': kind,
            'group': suffix.upper() == EVERYONE}


def who_discussed(paths: list[Path], people: dict, term: str) -> dict:
    """Which sections mention `term`, and who was in them.

    Answers "who would know about this" without reading the whole corpus: the section
    naming the term carries its own participant list in the heading.
    """
    hits, by_person = [], {}
    for p in paths:
        for s in date_sections(p):
            if term.lower() not in s['body'].lower():
                continue
            meta = parse_suffix(s['suffix'], people)
            # THE BODY DECIDES. Headings are hand-written and wrong sometimes, so a name
            # in the suffix never adds a participant on its own -- it is reported as
            # `declared_only` and left out of the answer. Participants are who spoke.
            spoke = sorted({t['alias'] for t in speaker_turns(s['body'], people)})
            declared = meta['participants']
            meta['spoke'] = spoke
            meta['declared_only'] = sorted(set(declared) - set(spoke))
            meta['participants'] = spoke
            hits.append({'key': section_key(s['file'], s['date'], s['suffix'], s['ord']),
                         'date': s['date'], **meta})
            for a in spoke:
                by_person.setdefault(a, []).append(s['date'])
    return {'sections': sorted(hits, key=lambda h: h['date'], reverse=True),
            'people': {a: {'mentions': len(d), 'latest': max(d)}
                       for a, d in sorted(by_person.items(),
                                          key=lambda kv: -len(kv[1]))}}


def find_section(path: Path, date: str, suffix: str = '') -> dict | None:
    """Re-find a section by identity rather than by remembered position."""
    for s in date_sections(path):
        if s['date'] == date and s['suffix'] == suffix:
            return s
    return None


def work_items(text: str) -> list[dict]:
    """Work-item headings at whatever level they appear, with the level recorded."""
    out = []
    for i, line in enumerate(lines_of(text)):
        m = WORK_ITEM.match(line)
        if m:
            out.append({'kind': m.group(2), 'id': f'{m.group(2)}-{m.group(3)}',
                        'level': len(m.group(1)), 'title': (m.group(4) or '').strip(),
                        'line': i + 1})
    return out


def work_item_ids(text: str) -> set[str]:
    """Every work-item id MENTIONED anywhere in the text, heading or prose."""
    return set(re.findall(r'\b((?:STORY|FEATURE|BUG|TASK)-\d+)\b', text))


# --- ontology: the roster -----------------------------------------------------

class RosterError(RuntimeError):
    """The TEAM table did not parse. Loud on purpose -- a short roster fails open."""


def roster(north_star: Path) -> dict:
    """The alias roster, parsed from the `## TEAM` table of the north-star note.

    DECLARED, then reconciled -- never derived by frequency. Frequency cannot distinguish
    `EF` (3 turns, internal, and not on this project) from a teammate, and it cannot
    see `JK` and `MN`, who are declared, real, and completely silent in the notes.

    Raises rather than returning a short roster: a silently-truncated roster degrades into
    dropped speaker turns, which is invisible in the output.
    """
    text = north_star.read_text(encoding='utf-8')
    block = re.search(r'^## TEAM\s*$(.*?)(?=^## |\Z)', text, re.S | re.M)
    if not block:
        raise RosterError(f'no `## TEAM` section in {north_star}')

    rows = [l.strip() for l in block.group(1).splitlines()
            if l.strip().startswith('|') and l.strip().endswith('|')]
    if len(rows) < 3:
        raise RosterError(f'`## TEAM` in {north_star} has no table (found {len(rows)} pipe rows)')

    def cells(row):
        return [c.strip() for c in row.strip('|').split('|')]

    header = [c.lower().replace(' ', '_') for c in cells(rows[0])]
    required = {'alias', 'code', 'org', 'on_project', 'role'}
    if not required.issubset(header):
        raise RosterError(f'`## TEAM` header missing {sorted(required - set(header))}: {header}')

    people = {}
    for row in rows[2:]:                       # row 1 is the ---|--- separator
        c = cells(row)
        if not any(c):                         # an empty row names nobody, so skipping it can't shorten the roster
            continue
        if len(c) != len(header):
            raise RosterError(f'TEAM row has {len(c)} cells, header has {len(header)}: {row}')
        rec = dict(zip(header, c))
        alias = rec['alias']
        if not alias or alias == '-':
            raise RosterError(f'TEAM row with no alias: {row}')
        rec['on_project'] = rec['on_project'].strip().lower() in ('yes', 'true', 'y')
        people[alias] = rec
    if not people:
        raise RosterError(f'`## TEAM` in {north_star} parsed to zero people')
    return people


def turn_shapes(alias: str) -> tuple[re.Pattern, re.Pattern]:
    """The two line shapes a speaker turn takes, for one KNOWN alias.

    Leading whitespace is tolerated on the alone shape. It is not hypothetical:
    `notes-updates.md:866` is `' Z'`, a real turn sitting between GH's message and Z's
    reply, with one stray space. A list item (`- Z`) still cannot match, because the
    bullet breaks the pattern.
    """
    a = re.escape(alias)
    return (re.compile(rf'^[ \t]*{a}[ \t]*$'),    # alone on its line: the reliable shape
            re.compile(rf'^{a} \S'))              # followed by text: only safe roster-gated


def speaker_turns(text: str, people: dict, inline: bool = False) -> list[dict]:
    """Attributed speaker turns, roster-gated.

    ALONE-ON-ITS-LINE ONLY by default. The inline shape (`AB says the thing`) is a real
    turn some of the time, but even roster-gated it cannot be told apart from prose that
    opens with someone's name -- "AB ranks it tied with dbt" is a sentence, not a turn.
    Including it inflated every alias against the measured counts. `inline=True` opts in
    where a caller wants recall over precision.

    A turn runs from its alias line to the next alias line or the next `## ` heading.
    Turns by someone whose `On project` is false are tagged rather than dropped, so a
    consumer can keep the attribution while excluding them from project status.
    """
    lines = lines_of(text)
    shapes = {a: turn_shapes(a) for a in people}
    starts = []
    for i, line in enumerate(lines):
        for alias, (alone, inl) in shapes.items():
            if alone.match(line) or (inline and inl.match(line)):
                starts.append((i, alias))
                break
    out = []
    for n, (i, alias) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
        for j in range(i + 1, end):
            if lines[j].startswith('## '):
                end = j
                break
        out.append({'alias': alias, 'start': i + 1, 'end': end,
                    'on_project': people[alias]['on_project'],
                    'body': '\n'.join(lines[i + 1:end]).strip()})
    return out


def mentions(text: str, people: dict) -> dict:
    """`@ALIAS` counts, roster-gated. Cross-validates the roster independently of turns."""
    found = {}
    for a in people:
        n = len(re.findall(rf'@{re.escape(a)}\b', text))
        if n:
            found[a] = n
    return found


def reconcile_roster(people: dict, paths: list[Path]) -> dict:
    """Drift in both directions between the declared roster and the corpus.

    `undeclared` is a candidate alias observed in the corpus and absent from the table.
    It is REPORTED, never auto-added -- the table is the operator's. Consumers attribute
    these under `unknown` rather than dropping the turns, because a new joiner appears in
    the notes before anyone edits the table.

    A raw alone-on-line scan is noisy: one-word lines like `Nope`, `Done`, `Papa` and
    `WIP` all match the shape. A candidate is only promoted on positive evidence of being
    a person -- an `@mention`, or repeated turns -- rather than filtered by a denylist,
    which would need me to have thought of every stray word in advance. `near_miss`
    carries what the evidence bar excluded, so nothing is silently dropped.

    `silent` is declared and never observed, which is a real state, not an error.
    """
    alone, at = {}, {}
    for p in paths:
        for line in lines_of(p.read_text(encoding='utf-8')):
            m = re.match(r'^([A-Z][A-Za-z]{0,3})[ \t]*$', line)
            if m:
                alone[m.group(1)] = alone.get(m.group(1), 0) + 1
            for a in re.findall(r'@([A-Z][A-Za-z]{0,3})\b', line):
                at[a] = at.get(a, 0) + 1

    seen = set(alone) | set(at)
    observed = {a: alone.get(a, 0) + at.get(a, 0) for a in seen if a in people}
    cand = {a: {'alone': alone.get(a, 0), 'mentions': at.get(a, 0)}
            for a in seen if a not in people}
    undeclared = {a: v for a, v in cand.items() if v['mentions'] or v['alone'] >= MIN_TURNS}
    return {'observed': observed,
            'undeclared': undeclared,
            'near_miss': {a: v for a, v in cand.items() if a not in undeclared},
            'silent': sorted(a for a in people if a not in observed)}


# --- the operator's directives ------------------------------------------------

def note_directives(paths: list[Path], people: dict | None = None) -> list[dict]:
    """`**NOTE**:` lines -- the operator writing to themselves or to the agent.

    These are instructions embedded in the corpus and nothing else looks for them, so they
    surface only when somebody happens to read that section. Both spellings are matched;
    the corpus already contains a variant with the colon inside the bold.

    Each directive carries the dated section that owns it and the nearest preceding
    speaker, so it can be routed rather than merely found.
    """
    out = []
    for p in paths:
        lines = lines_of(p.read_text(encoding='utf-8'))
        cur_date, cur_alias = None, None
        for i, line in enumerate(lines):
            dm = DATE_H2.match(line)
            if dm:
                cur_date, cur_alias = dm.group(1), None
                continue
            if people:
                for a in people:
                    if re.match(rf'^{re.escape(a)}[ \t]*$', line):
                        cur_alias = a
                        break
            m = NOTE_MARK.match(line)
            if m:
                out.append({'file': p.name, 'line': i + 1, 'date_section': cur_date,
                            'alias': cur_alias,
                            'text': (m.group(1) or m.group(2) or '').strip()})
    return out


# --- taxonomy: frontmatter profiles -------------------------------------------

def frontmatter_profiles(paths: list[Path]) -> dict:
    """Per-family key profile, DERIVED from the corpus rather than declared here.

    The profile is the intersection of keys across a family's members, so it reports what
    that family actually agrees on. A hardcoded expected-key list would fail open the
    moment a family gains a key, and a fixture built from the same list would pass clean.
    """
    fams: dict[str, list] = {}
    bare = []
    for p in paths:
        fam = family(p.name)
        if fam is None:
            continue
        fm, _ = parse_frontmatter(p.read_text(encoding='utf-8'))
        if not fm:
            bare.append(p.name)
        fams.setdefault(fam, []).append((p.name, set(fm)))

    profiles = {}
    for fam, members in fams.items():
        with_fm = [keys for _, keys in members if keys]
        common = set.intersection(*with_fm) if with_fm else set()
        profiles[fam] = {
            'files': len(members),
            'common': sorted(common),
            'missing': {n: sorted(common - keys) for n, keys in members
                        if keys and (common - keys)},
        }
    return {'profiles': profiles, 'no_frontmatter': sorted(bare)}


# --- taxonomy: source authority ----------------------------------------------

# Declared by the operator, not inferred. Two axes, because they are independent: how far
# a source can settle a question about CURRENT state, and how likely it is to vanish.
#
#   role       what the file is for
#   volatility living | transient | cold | atomic | point-in-time | stale
#   rank       lower wins when two sources disagree about the present
#
# THE ANCHORS for gathering and conflict resolution are the active user stories, the code,
# and the most recent learnings and notes -- ranks 0 to 2. Everything below those explains
# or records; it does not settle.
#
# An unrecognized name is reported as unranked rather than defaulted, so a new file in the
# drop surfaces instead of quietly inheriting someone else's authority.
AUTHORITY = {
    'user-stories.md': dict(
        rank=1, role='live board', volatility='living',
        note='The real live one, mirroring the tracker. Authoritative for assigned work. '
             'Changed only by propose-then-edit, never edited in passing.'),
    'user-runsheet.md': dict(
        rank=2, role='run sheet', volatility='transient', distill_priority=True,
        note='The ordered steps for in-flight stories, and the operator\'s working scratch '
             'on them. DRAINED every sweep, so anything learned here is lost unless '
             'distilled first. That impermanence is exactly why it is a prime distillation '
             'target. Older vaults name it user-stories-runsheet.md or user-stories-tasks.md.'),
    'user-stories-completed.md': dict(
        rank=3, role='cold storage', volatility='cold',
        note='Finished stories, kept for archived reference.'),
    'user-stories-backlog.md': dict(
        rank=4, role='backlog draft', volatility='living',
        note='Ranked LAST of the story files, below even cold storage: it is a draft, '
             'neither refined nor vetted, so it describes intent rather than state.'),
}
# A project's north-star note ranks 0 as an INPUT rather than an output: it carries the
# audience, use cases, priorities and roster, and is never validated against the corpus
# because it is what the corpus is read FOR. Its filename is project-specific, so the
# entry lives in the project profile's `authority` block.

FAMILY_AUTHORITY = {
    'code': dict(
        rank=1, role='the code itself', volatility='atomic',
        note='Current state of the main branch at flatten time. The whole flatten happens '
             'at once, so every code-* note shares one age, carried in `flattened:`. '
             'Outranks any note where they disagree, but ONLY when the flatten is at least '
             'as recent as the claim.'),
    'notes': dict(
        rank=2, role='dated event record', volatility='living',
        note='Append-only dated logs. Recency is readable per section from the `## '
             'YYYY-MM-DD` heading rather than per file.'),
    'docs': dict(
        rank=5, role='reference document', volatility='point-in-time',
        note='Mixed vintage. Read `effective_date` with `date_confidence`; the ways-of-'
             'working set is the newest and the research set is the stalest.'),
}
# The authored tier ranks LAST by design, below every source it derives from: those notes
# are DOWNSTREAM of the vault notes, so letting one settle a question would be a synthesis
# overruling its own evidence. They are what validation CHECKS; they never settle. The
# north-star note is the exception and carries its own rank 0 entry. Both are keyed on the
# project's own prefix, so they live in the profile's `family_authority` block.

# Per-document roles, declared by the operator 2026-08-21. The `kind` is what decides how a
# doc may be USED, and two kinds are traps if read as ordinary reference:
#
#   told      A deck shown to stakeholders. Evidence of what people were TOLD, never
#             evidence about the system. Use it to answer "what does the client believe",
#             never to settle a technical question.
#   ancestor  A predecessor of something the operator now owns as a deliverable. Looks
#             authoritative -- it is a runbook or a design guide -- but the current
#             deliverable supersedes it. Validating against one inverts the direction of
#             authority, so it is reference-for-completeness only.
#   governing    Sets the scope this work answers to. Read before synthesizing.
#   prior-phase  Belongs to a phase that preceded the current one.
#   sop          A standing procedure, often owned elsewhere and often future-dated.
#
# Every entry is keyed on a real filename from one project's drop, so the table itself is
# project data and lives in that project's `vault-profile.json` rather than here.


def doc_role(name: str, project: str | Path | None = None,
             root: str | Path = '.') -> dict:
    """Declared role for a specific document, or `{}` if it has none.

    Roles are declared per project, so without `project` every document comes back
    role-less, which `usable_as_evidence` treats as usable."""
    roles = load_profile(project, root).get('doc_roles') or {}
    return roles.get(Path(name).name, {})


def usable_as_evidence(name: str, project: str | Path | None = None,
                       root: str | Path = '.') -> bool:
    """False for documents that record what people were TOLD, or that a deliverable has
    since superseded. Both look like reference and neither settles a question about the
    system."""
    return doc_role(name, project, root).get('kind') not in ('told', 'ancestor')


# Subsets of `docs` the operator called out explicitly.
DOCS_SUBSET = {
    'docs-internal-wow-': dict(
        role='ways of working', volatility='living',
        note='The newest of the docs. Carries only `authored-by` in frontmatter, so it '
             'declares no date and recency cannot be read from the file.'),
    'docs-research-': dict(
        role='background research', volatility='stale',
        note='Largely stale but still relevant. Needs a refresh path so it keeps flowing '
             'rather than aging in place.'),
}


def authority(name: str, project: str | Path | None = None,
              root: str | Path = '.') -> dict:
    """What a source is worth, and how long it will be there. Declared, never inferred.

    A project's own entries are layered over the generic ones, so its north-star note and
    authored tier rank correctly. Without `project` only the generic table applies and a
    project-prefixed note comes back unranked, which surfaces it rather than guessing."""
    stem = Path(name).name
    if stem in SCAFFOLDING:
        return {'name': stem, 'rank': 50, 'role': 'generated scaffolding',
                'volatility': 'rebuilt', 'validate': False,
                'note': 'Rewritten wholesale on every assemble. Never a source.'}
    prof = load_profile(project, root)
    by_name = {**AUTHORITY, **(prof.get('authority') or {})}
    by_family = {**FAMILY_AUTHORITY, **(prof.get('family_authority') or {})}
    if stem in by_name:
        return {'name': stem, **by_name[stem]}
    for prefix, extra in DOCS_SUBSET.items():
        if stem.startswith(prefix):
            return {'name': stem, **by_family['docs'], **extra}
    fam = family(stem, project, root)
    if fam in by_family:
        return {'name': stem, **by_family[fam]}
    return {'name': stem, 'rank': 99, 'role': 'unranked', 'volatility': 'unknown',
            'note': 'Not in the declared authority table. Rank it before trusting it.'}


def resolve_anchors(fm: dict) -> dict:
    """Resolve the one YAML feature the flat parser cannot: `&id001` / `*id001`.

    The docs family writes `timestamp: &id001 2026-03-01` and `effective_date: *id001`,
    so a flat read returns the literal string `*id001` and every docs date looks unusable.
    """
    anchors = {}
    for k, v in fm.items():
        m = re.match(r'^&(\S+)\s+(.*)$', str(v))
        if m:
            anchors[m.group(1)] = m.group(2)
            fm[k] = m.group(2)
    for k, v in fm.items():
        m = re.match(r'^\*(\S+)$', str(v))
        if m and m.group(1) in anchors:
            fm[k] = anchors[m.group(1)]
    return fm


def effective_date(path: Path) -> dict:
    """Best date for a note, with the evidence behind it.

    Never one field, because the families disagree: `code-*` carries `flattened`, `docs-*`
    carries `effective_date` plus a `date_confidence`, `notes-*` carries `coverage_end`,
    and the ways-of-working docs carry nothing at all.

    For a dated log, CONTENT BEATS ITS OWN FRONTMATTER. `coverage_end` is hand-maintained
    and drifts: measured 2026-08-21, four of seven `notes-*` files understated their newest
    section, `notes-meeting-notes.md` by 22 days. A freshness check that trusted the
    declared field would age those files out of the window that should include them.
    """
    fm = resolve_anchors(parse_frontmatter(path.read_text(encoding='utf-8'))[0])

    if family(path.name) == 'notes':
        secs = [s['date'] for s in date_sections(path)]
        if secs:
            declared = str(fm.get('coverage_end', '')).strip()
            newest = max(secs)
            return {'date': newest, 'field': 'content:newest-section',
                    'confidence': 'measured', 'signal': 'date-heading',
                    'declared': declared or None,
                    'drift': declared != newest and bool(declared)}

    for key in ('flattened', 'effective_date', 'coverage_end', 'updated', 'timestamp'):
        v = str(fm.get(key, '')).strip()
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', v):
            return {'date': v, 'field': key,
                    'confidence': fm.get('date_confidence', 'declared'),
                    'signal': fm.get('date_signal', key), 'drift': False}
    return {'date': None, 'field': None, 'confidence': 'none',
            'signal': None, 'drift': False}


def coverage_drift(paths: list[Path]) -> list[dict]:
    """Dated logs whose `coverage_end` understates their newest section.

    Reported rather than repaired: the frontmatter is upstream and the operator owns it.
    """
    out = []
    for p in paths:
        d = effective_date(p)
        if d.get('drift'):
            out.append({'file': p.name, 'declared': d['declared'], 'actual': d['date']})
    return out


def corpus(raw: Path, kind: str = 'notes') -> list[Path]:
    """The `<kind>-*.md` files of a raw drop, sorted. `notes` excludes the learnings file,
    which is written BY the sweep and would otherwise be re-harvested as input."""
    out = sorted(raw.glob(f'{kind}-*.md'))
    if kind == 'notes':
        out = [p for p in out if p.name != 'notes-learnings.md']
    return out
