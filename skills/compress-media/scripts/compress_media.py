#!/usr/bin/env python3
"""Shrink video, audio and image files with ffmpeg, writing a smaller copy beside each original.

Run: compress_media.py PATH [PATH ...] [--to TARGET] [--quality low|medium|high]
     [--max-size SIZE] [--out DIR] [--recursive] [--force] [--dry-run] [--json]

Stdlib only. Needs ffmpeg and ffprobe on PATH; HEIC input also needs the macOS sips tool.
The source file is never modified. Output goes to <stem>_small.<ext>.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

KINDS = {
    "video": {".mov", ".mp4", ".m4v", ".mkv", ".webm", ".avi", ".mts", ".m2ts", ".3gp", ".wmv", ".flv", ".mpg", ".mpeg"},
    "audio": {".wav", ".aif", ".aiff", ".flac", ".m4a", ".mp3", ".aac", ".ogg", ".oga", ".opus", ".wma", ".caf"},
    "image": {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp", ".jp2", ".avif"},
    "heic": {".heic", ".heif"},
    "gif": {".gif"},
}

# target -> (output kind, extension)
TARGETS = {
    "hevc": ("video", ".mp4"),
    "h264": ("video", ".mp4"),
    "av1": ("video", ".webm"),
    "aac": ("audio", ".m4a"),
    "mp3": ("audio", ".mp3"),
    "opus": ("audio", ".opus"),
    "jpeg": ("image", ".jpg"),
    "webp": ("image", ".webp"),
    "avif": ("image", ".avif"),
}
ALIASES = {"h265": "hevc", "x265": "hevc", "mp4": "h264", "x264": "h264", "webm": "av1", "m4a": "aac", "jpg": "jpeg"}

# Output kinds each input kind may become.
ALLOWED = {
    "video": {"video", "audio"},
    "audio": {"audio"},
    "image": {"image"},
    "heic": {"image"},
    "gif": {"video", "image"},
}

ENCODERS = {
    "hevc": "libx265", "h264": "libx264", "av1": "libsvtav1",
    "aac": "aac", "mp3": "libmp3lame", "opus": "libopus",
    "jpeg": "mjpeg", "webp": "libwebp", "avif": "libaom-av1",
}

LEVELS = ("low", "medium", "high")
VIDEO_CRF = {
    "hevc": {"low": 30, "medium": 26, "high": 22},
    "h264": {"low": 28, "medium": 23, "high": 19},
    "av1": {"low": 40, "medium": 34, "high": 28},
}
AUDIO_KBPS = {
    "aac": {"low": 96, "medium": 128, "high": 192},
    "mp3": {"low": 96, "medium": 128, "high": 192},
    "opus": {"low": 48, "medium": 80, "high": 128},
}
AUDIO_FLOOR_KBPS = {"aac": 32, "mp3": 32, "opus": 12}

# Image quality ladders, best first. A preset starts at its index; --max-size walks down from there.
IMAGE_LADDER = {
    "jpeg": [2, 3, 4, 5, 6, 8, 10, 13, 16, 20, 25, 31],        # ffmpeg mjpeg -q:v, lower is better
    "webp": [95, 90, 85, 80, 75, 70, 60, 50, 40, 30, 20, 10],  # libwebp -quality
    "avif": [18, 22, 26, 30, 34, 38, 42, 46, 50, 55, 60, 63],  # libaom -crf, lower is better
    "sips": [95, 90, 85, 80, 75, 70, 60, 50, 40, 30, 20, 10],  # sips JPEG quality percent
}
IMAGE_START = {"high": 2, "medium": 4, "low": 6}

SUFFIX = "_small"
MIN_VIDEO_KBPS = 100
HEADROOM = 0.95      # share of a size limit spent on streams; the rest covers container overhead
RETRY_FACTOR = 0.85  # bitrate cut for the one retry after an overshoot
HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}
ALPHA_RE = re.compile(r"^(yuva|gbrap|ya|rgba|bgra|argb|abgr|pal8)")
COLOR_NAME_RE = re.compile(r"[a-z0-9-]+")
TONEMAP = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
           "tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p")
EVEN = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
# Lays a transparent image over an opaque white copy of itself, for formats with no alpha channel.
FLATTEN = "format=rgba,split[fg][bg];[bg]lutrgb=r=255:g=255:b=255:a=255[white];[white][fg]overlay=format=auto"
# Inputs are often received files; a container must not be able to make ffmpeg open a URL.
LOCAL_ONLY = ["-protocol_whitelist", "file"]
# Shared copies keep the creation date but drop where they were made. An empty value deletes a key.
DROP_LOCATION = ["-metadata", "location=", "-metadata", "location-eng=",
                 "-metadata", "com.apple.quicktime.location.ISO6709="]
INSTALL_HINT = ("ffmpeg and ffprobe are required and were not found on PATH. Install them with "
                "`brew install ffmpeg` (macOS), `sudo apt install ffmpeg` (Debian, Ubuntu) "
                "or `winget install ffmpeg` (Windows).")
FAILING = {"failed", "unsupported"}


class MediaError(Exception):
    pass


@dataclass
class Media:
    path: Path
    kind: str
    size: int
    duration: float = 0.0
    pix_fmt: str = ""
    color_transfer: str = ""
    color_primaries: str = ""
    color_space: str = ""
    acodec: str = ""
    frames: int = 0
    has_video: bool = False
    has_audio: bool = False

    @property
    def alpha(self) -> bool:
        return bool(ALPHA_RE.match(self.pix_fmt))

    @property
    def hdr(self) -> bool:
        return self.color_transfer in HDR_TRANSFERS

    @property
    def deep(self) -> bool:
        """10- or 12-bit samples."""
        return bool(re.search(r"p1[02]", self.pix_fmt))

    @property
    def animated(self) -> bool:
        return self.frames > 1


# ---------------------------------------------------------------- pure helpers

def kind_of(path: Path) -> str | None:
    ext = path.suffix.lower()
    return next((k for k, exts in KINDS.items() if ext in exts), None)


def parse_size(text: str) -> int:
    """'25MB', '25m', '500k', '1.5GB', '900B', or a bare number meaning MB. Units are 1024-based."""
    m = re.fullmatch(r"\s*([0-9]*\.?[0-9]+)\s*([kmg]?)(i?b)?\s*", text.lower())
    if not m:
        raise ValueError(f"cannot read size {text!r}; write it like 25MB, 500KB or 1.5GB")
    number, unit, bytes_suffix = float(m.group(1)), m.group(2), m.group(3)
    if not unit:
        return int(number) if bytes_suffix else int(number * 1024 ** 2)
    return int(number * 1024 ** ("kmg".index(unit) + 1))


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def resolve_target(name: str) -> str:
    t = ALIASES.get(name.lower(), name.lower())
    if t not in TARGETS:
        raise MediaError(f"unknown target {name!r}; choose from {', '.join(TARGETS)} "
                         f"(aliases {', '.join(ALIASES)})")
    return t


def pick_target(m: Media, to: str | None) -> str:
    if to:
        t = resolve_target(to)
        if TARGETS[t][0] not in ALLOWED[m.kind]:
            raise MediaError(f"a {m.kind} file cannot become {t}")
        return t
    if m.kind == "video":
        return "hevc"
    if m.kind == "audio":
        return "aac"
    if m.kind == "heic":
        return "jpeg"
    if m.kind == "gif":
        return "h264" if m.animated else "webp"
    return "webp" if m.alpha else "jpeg"


def output_path(src: Path, ext: str, out_dir: Path | None) -> Path:
    return (out_dir or src.parent) / f"{src.stem}{SUFFIX}{ext}"


def video_budget(max_bytes: int, duration: float, has_audio: bool, audio_kbps: int) -> tuple[int, int]:
    """Split a size limit into (video kbps, audio kbps); raise when the video share is unwatchable."""
    if duration <= 0:
        raise MediaError("the duration is unknown, so a size limit cannot be planned")
    total = max_bytes * 8 / 1000 / duration * HEADROOM
    audio = audio_kbps if has_audio else 0
    if has_audio and total - audio < MIN_VIDEO_KBPS:
        audio = min(audio, 64)
    video = int(total - audio)
    if video < MIN_VIDEO_KBPS:
        raise MediaError(f"{human(max_bytes)} leaves about {max(video, 0)} kbps for {duration:.0f} s of video; "
                         f"anything under {MIN_VIDEO_KBPS} kbps is unwatchable, so raise the limit")
    return video, audio


def audio_budget(max_bytes: int, duration: float, target: str, preset_kbps: int) -> int:
    if duration <= 0:
        raise MediaError("the duration is unknown, so a size limit cannot be planned")
    budget = int(max_bytes * 8 / 1000 / duration * HEADROOM)
    if budget < AUDIO_FLOOR_KBPS[target]:
        raise MediaError(f"{human(max_bytes)} allows about {budget} kbps for {duration:.0f} s of audio; "
                         f"{target} needs at least {AUDIO_FLOOR_KBPS[target]} kbps")
    return min(preset_kbps, budget)


# ---------------------------------------------------------------- command builders

def video_args(m: Media, target: str, quality: str, *, kbps: int = 0, audio_kbps: int = 0,
               pass_no: int = 0) -> list[str]:
    """ffmpeg arguments between the input and the output for one video encode."""
    # Color tags go through setparams: output options such as -color_trc do not tag the stream
    # when the decoded frames carry their own (even unknown) values.
    filters = [EVEN]
    if m.hdr and target == "h264":
        filters = [TONEMAP, EVEN, "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709"]
    elif m.hdr:
        # Values come from the file's metadata, so only plain names reach the filter string.
        tags = [f"{key}={value}" for key, value in (("color_primaries", m.color_primaries),
                ("color_trc", m.color_transfer), ("colorspace", m.color_space))
                if COLOR_NAME_RE.fullmatch(value) and value != "unknown"]
        if tags:
            filters.append("setparams=" + ":".join(tags))
    filters.append("format=yuv420p10le" if m.deep and target != "h264" else "format=yuv420p")

    args = ["-map", "0:v:0", "-vf", ",".join(filters), "-c:v", ENCODERS[target]]
    if target == "hevc":
        x265 = ["log-level=error"] + ([f"pass={pass_no}", "stats=pass.log"] if kbps else [])
        args += ["-preset", "medium", "-tag:v", "hvc1", "-x265-params", ":".join(x265)]
    elif target == "h264":
        args += ["-preset", "medium"] + (["-pass", str(pass_no), "-passlogfile", "pass"] if kbps else [])
    else:
        args += ["-preset", "6"]
    args += ["-b:v", f"{kbps}k"] if kbps else ["-crf", str(VIDEO_CRF[target][quality])]

    if pass_no == 1 or not m.has_audio or m.kind == "gif":
        args.append("-an")
    elif target == "av1":
        args += ["-map", "0:a:0", "-c:a", "libopus", "-b:a", f"{audio_kbps or AUDIO_KBPS['opus'][quality]}k"]
    elif m.acodec == "aac" and not audio_kbps:
        args += ["-map", "0:a:0", "-c:a", "copy"]
    else:
        args += ["-map", "0:a:0", "-c:a", "aac", "-b:a", f"{audio_kbps or AUDIO_KBPS['aac'][quality]}k"]
    if target != "av1":
        args += ["-movflags", "+faststart"]
    return args + ["-map_metadata", "0", *DROP_LOCATION]


def audio_args(target: str, kbps: int) -> list[str]:
    args = ["-map", "0:a:0", "-c:a", ENCODERS[target], "-b:a", f"{kbps}k", "-map_metadata", "0", *DROP_LOCATION]
    return args + (["-movflags", "+faststart"] if target == "aac" else [])


def image_args(m: Media, target: str, level: int) -> list[str]:
    value = str(IMAGE_LADDER[target][level])
    if target == "webp" and m.animated:
        return ["-map", "0:v:0", "-c:v", "libwebp_anim", "-quality", value, "-loop", "0"]
    flatten = FLATTEN + "," if m.alpha and target in ("jpeg", "avif") else ""
    args = ["-map", "0:v:0", "-frames:v", "1"]
    if target == "jpeg":
        return args + ["-vf", flatten + "format=yuvj420p", "-c:v", "mjpeg", "-q:v", value, "-update", "1"]
    if target == "webp":
        return args + ["-c:v", "libwebp", "-quality", value, "-compression_level", "6"]
    return args + ["-vf", flatten + "format=yuv420p", "-c:v", "libaom-av1", "-still-picture", "1",
                   "-cpu-used", "6", "-crf", value]


def ffmpeg_cmd(src: Path, args: list[str], dst: Path | None) -> list[str]:
    tail = [str(dst)] if dst else ["-f", "null", os.devnull]
    return (["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y", *LOCAL_ONLY, "-i", str(src)]
            + args + tail)


def sips_cmd(src: Path, dst: Path, fmt: str, percent: int = 0) -> list[str]:
    opts = ["-s", "formatOptions", str(percent)] if percent else []
    return ["sips", "-s", "format", fmt] + opts + [str(src), "--out", str(dst)]


# ---------------------------------------------------------------- running

def run(cmd: list[str], cwd: Path | None = None) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, cwd=cwd)
    if r.returncode != 0:
        lines = [ln for ln in (r.stderr or r.stdout).splitlines() if ln.strip()]
        raise MediaError(f"{cmd[0]} failed: {' | '.join(lines[-3:]) or f'exit {r.returncode}'}")


@functools.lru_cache(maxsize=None)
def ffmpeg_list(flag: str) -> frozenset[str]:
    """Names from `ffmpeg -encoders` or `ffmpeg -filters`."""
    r = subprocess.run(["ffmpeg", "-hide_banner", flag], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return frozenset(parts[1] for parts in map(str.split, r.stdout.splitlines()) if len(parts) >= 2)


def check_support(m: Media, target: str) -> None:
    out_kind = TARGETS[target][0]
    need = []
    if m.kind == "heic":
        if not shutil.which("sips"):
            raise MediaError("HEIC needs the macOS sips tool, which is not on this machine; "
                             "convert the photo to JPEG elsewhere first")
        if target == "jpeg":
            return
    if target == "webp" and m.animated:
        need.append("libwebp_anim")
    else:
        need.append(ENCODERS[target])
    if out_kind == "video" and m.has_audio and m.kind != "gif":
        need.append("libopus" if target == "av1" else "aac")
    missing = [e for e in need if e not in ffmpeg_list("-encoders")]
    if m.hdr and target == "h264" and "zscale" not in ffmpeg_list("-filters"):
        missing.append("zscale filter (libzimg)")
    if missing:
        raise MediaError(f"this ffmpeg build lacks {', '.join(missing)}; install a full build "
                         f"(brew install ffmpeg) or pick another --to")


def probe(path: Path) -> Media:
    kind = kind_of(path)
    if kind is None:
        raise MediaError("not a supported media type")
    m = Media(path, kind, path.stat().st_size)
    if kind == "heic":
        return m  # ffmpeg cannot decode HEIC grids; sips converts it
    cmd = ["ffprobe", "-v", "error", *LOCAL_ONLY, "-show_format", "-show_streams", "-of", "json", str(path)]
    if kind == "gif":
        cmd.insert(1, "-count_packets")
    r = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise MediaError(f"ffprobe could not read it: {(r.stderr.strip().splitlines() or ['no output'])[-1]}")
    data = json.loads(r.stdout or "{}")
    m.duration = float(data.get("format", {}).get("duration") or 0)
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and not m.has_video and not s.get("disposition", {}).get("attached_pic"):
            m.has_video = True
            m.pix_fmt = s.get("pix_fmt", "")
            m.color_transfer = s.get("color_transfer", "")
            m.color_primaries = s.get("color_primaries", "")
            m.color_space = s.get("color_space", "")
            m.frames = int(s.get("nb_read_packets") or 0)
        elif s.get("codec_type") == "audio" and not m.has_audio:
            m.has_audio = True
            m.acodec = s.get("codec_name", "")
    if m.kind == "video" and not m.has_video and m.has_audio:
        m.kind = "audio"
    if m.kind == "audio" and not m.has_audio:
        raise MediaError("no audio stream found")
    if m.kind != "audio" and not m.has_video:
        raise MediaError("no picture stream found")
    return m


def encode_video(m: Media, target: str, dst: Path, quality: str, max_size: int, work: Path) -> None:
    run(ffmpeg_cmd(m.path, video_args(m, target, quality), dst))
    if not max_size or dst.stat().st_size <= max_size:
        return
    has_audio = m.has_audio and m.kind != "gif"
    video, audio = video_budget(max_size, m.duration, has_audio, AUDIO_KBPS["aac"][quality])
    for factor in (1.0, RETRY_FACTOR):
        kbps = int(video * factor)
        if kbps < MIN_VIDEO_KBPS:
            break
        run(ffmpeg_cmd(m.path, video_args(m, target, quality, kbps=kbps, pass_no=1), None), cwd=work)
        run(ffmpeg_cmd(m.path, video_args(m, target, quality, kbps=kbps, audio_kbps=audio, pass_no=2), dst), cwd=work)
        if dst.stat().st_size <= max_size:
            return
    raise MediaError(f"still {human(dst.stat().st_size)} after two-pass encodes; "
                     f"{human(max_size)} is too small for {m.duration:.0f} s of video")


def encode_audio(m: Media, target: str, dst: Path, quality: str, max_size: int) -> None:
    if not m.has_audio:
        raise MediaError("no audio track to keep")
    kbps = AUDIO_KBPS[target][quality]
    if max_size:
        kbps = audio_budget(max_size, m.duration, target, kbps)
    for factor in (1.0, RETRY_FACTOR):
        run(ffmpeg_cmd(m.path, audio_args(target, max(int(kbps * factor), AUDIO_FLOOR_KBPS[target])), dst))
        if not max_size or dst.stat().st_size <= max_size:
            return
    raise MediaError(f"still {human(dst.stat().st_size)} at the lowest bitrate tried; raise the limit")


def walk_ladder(build, ladder: str, dst: Path, quality: str, max_size: int) -> None:
    """Encode at the preset's quality; with a size limit, step down the ladder until it fits."""
    start = IMAGE_START[quality]
    stop = len(IMAGE_LADDER[ladder]) if max_size else start + 1
    for level in range(start, stop):
        run(build(level))
        if not max_size or dst.stat().st_size <= max_size:
            return
    raise MediaError(f"still {human(dst.stat().st_size)} at the lowest quality; raise the limit")


def encode_image(m: Media, target: str, dst: Path, quality: str, max_size: int, work: Path) -> None:
    if m.kind == "heic":
        if target == "jpeg":
            walk_ladder(lambda i: sips_cmd(m.path, dst, "jpeg", IMAGE_LADDER["sips"][i]), "sips", dst, quality, max_size)
            return
        png = work / "decoded.png"
        run(sips_cmd(m.path, png, "png"))
        m = probe(png)
    walk_ladder(lambda i: ffmpeg_cmd(m.path, image_args(m, target, i), dst), target, dst, quality, max_size)


def plan(m: Media, target: str, quality: str, max_size: int, dst: Path) -> list[str]:
    """The first command(s) a real run would execute, for --dry-run."""
    out_kind = TARGETS[target][0]
    level = IMAGE_START[quality]
    if m.kind == "heic":
        if target == "jpeg":
            cmds = [sips_cmd(m.path, dst, "jpeg", IMAGE_LADDER["sips"][level])]
        else:
            png = Path("decoded.png")
            cmds = [sips_cmd(m.path, png, "png"), ffmpeg_cmd(png, image_args(Media(png, "image", 0), target, level), dst)]
    elif out_kind == "video":
        cmds = [ffmpeg_cmd(m.path, video_args(m, target, quality), dst)]
    elif out_kind == "audio":
        cmds = [ffmpeg_cmd(m.path, audio_args(target, AUDIO_KBPS[target][quality]), dst)]
    else:
        cmds = [ffmpeg_cmd(m.path, image_args(m, target, level), dst)]
    lines = [shlex.join(c) for c in cmds]
    if max_size:
        lines.append(f"(then lower quality or two-pass bitrate until it is under {human(max_size)})")
    return lines


def compress(src: Path, to: str | None, quality: str, max_size: int, out_dir: Path | None,
             force: bool, dry_run: bool, claimed: set[Path] | None = None,
             sources: frozenset[Path] = frozenset()) -> dict:
    """Compress one file. `claimed` collects the outputs this run has written or planned, and
    `sources` holds every source of the run, resolved, so no output overwrites either."""
    claimed = set() if claimed is None else claimed
    res = {"source": str(src), "kind": kind_of(src), "target": None, "output": None,
           "before": None, "after": None, "status": "failed", "note": ""}
    try:
        m = probe(src)
        res["kind"], res["before"] = m.kind, m.size
        target = pick_target(m, to)
        res["target"] = target
        if max_size and target == "av1":
            raise MediaError("--max-size works with hevc and h264 video; av1 has no two-pass here")
        check_support(m, target)
        # absolute(), not resolve(): a symlink at the output path is replaced, never followed.
        dst = output_path(src, TARGETS[target][1], out_dir).absolute()
        res["output"] = str(dst)
        if dst.resolve() == src.resolve() or dst.resolve() in sources:
            raise MediaError(f"the output {dst.name} would replace a source file")
        if dst in claimed:
            raise MediaError(f"another file in this run already writes {dst.name}")
        if (dst.exists() or dst.is_symlink()) and not force:
            res.update(status="exists", note="output already exists; pass --force to replace it")
            return res
        if dry_run:
            claimed.add(dst)
            res.update(status="planned", note="\n".join(plan(m, target, quality, max_size, dst)))
            return res
        dst.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=dst.parent, prefix=".compress-media-") as tmp:
            work = Path(tmp)
            part = work / f"out{dst.suffix}"
            m.path = m.path.resolve()
            out_kind = TARGETS[target][0]
            if out_kind == "video":
                encode_video(m, target, part, quality, max_size, work)
            elif out_kind == "audio":
                encode_audio(m, target, part, quality, max_size)
            else:
                encode_image(m, target, part, quality, max_size, work)
            after = part.stat().st_size
            res["after"] = after
            if after >= m.size and not to:
                res.update(status="kept-original", output=None,
                           note="the result was not smaller, so it was discarded")
                return res
            os.replace(part, dst)
        claimed.add(dst)
        res["status"] = "done"
        if after >= m.size:
            res["note"] = "larger than the original; kept because --to asked for this format"
    except MediaError as e:
        res.update(status="unsupported" if str(e) == "not a supported media type" else "failed", note=str(e))
    except (OSError, ValueError) as e:
        res["note"] = str(e)
    return res


def collect(paths: list[str], recursive: bool) -> tuple[list[Path], list[dict]]:
    """Expand folders into their media files; explicit files are taken as given."""
    files, missing = [], []
    for raw in paths:
        p = Path(raw).expanduser()
        if p.is_dir():
            found = p.rglob("*") if recursive else p.iterdir()
            files += sorted(f for f in found if f.is_file() and kind_of(f)
                            and not f.stem.endswith(SUFFIX)
                            and not any(part.startswith(".") for part in f.relative_to(p).parts))
        elif p.is_file():
            files.append(p)
        else:
            missing.append({"source": str(p), "kind": None, "target": None, "output": None,
                            "before": None, "after": None, "status": "failed", "note": "no such file or folder"})
    # One entry per real file, under the path it was named by, so a symlinked source's
    # output lands beside the link rather than beside its target.
    unique: dict[Path, Path] = {}
    for f in files:
        unique.setdefault(f.resolve(), f.absolute())
    return list(unique.values()), missing


def describe(r: dict) -> str:
    name = Path(r["source"]).name
    if r["status"] == "done":
        pct = (r["after"] - r["before"]) * 100 / r["before"] if r["before"] else 0
        line = (f"{name}  {r['kind']} -> {r['target']}  {human(r['before'])} -> {human(r['after'])}  "
                f"{pct:+.0f}%  {Path(r['output']).name}")
        return line + (f"  ({r['note']})" if r["note"] else "")
    if r["status"] == "planned":
        return f"{name}  {r['kind']} -> {r['target']}  would run:\n  " + r["note"].replace("\n", "\n  ")
    detail = f"{human(r['before'])}, {r['note']}" if r["before"] else r["note"]
    return f"{name}  {r['status']}: {detail}"


def summary(results: list[dict]) -> str:
    counts = {s: sum(r["status"] == s for r in results) for s in
              ("done", "kept-original", "exists", "planned", "failed", "unsupported")}
    parts = [f"{n} {s}" for s, n in counts.items() if n]
    done = [r for r in results if r["status"] == "done"]
    line = f"{len(results)} file(s): {', '.join(parts)}"
    if done:
        before, after = sum(r["before"] for r in done), sum(r["after"] for r in done)
        line += f"; {human(before)} -> {human(after)} across the compressed files"
    return line


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Shrink video, audio and image files with ffmpeg.")
    ap.add_argument("paths", nargs="+", help="files or folders")
    ap.add_argument("--to", help=f"output format: {', '.join(TARGETS)}")
    ap.add_argument("--quality", choices=LEVELS, default="medium")
    ap.add_argument("--max-size", type=parse_size, default=0, metavar="SIZE",
                    help="fit each output under SIZE, such as 25MB")
    ap.add_argument("--out", type=Path, help="write outputs here instead of beside each source")
    ap.add_argument("--recursive", action="store_true", help="descend into subfolders")
    ap.add_argument("--force", action="store_true", help="replace an existing output (never the source)")
    ap.add_argument("--dry-run", action="store_true", help="print the commands without running them")
    ap.add_argument("--json", action="store_true", help="print results as JSON")
    args = ap.parse_args(argv)

    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        print(INSTALL_HINT, file=sys.stderr)
        return 2
    if args.to:
        try:
            resolve_target(args.to)
        except MediaError as e:
            print(e, file=sys.stderr)
            return 2

    files, results = collect(args.paths, args.recursive)
    if not args.json:
        for r in results:
            print(describe(r), flush=True)
    out_dir = args.out.expanduser() if args.out else None
    claimed: set[Path] = set()
    sources = frozenset(f.resolve() for f in files)
    for f in files:
        r = compress(f, args.to, args.quality, args.max_size, out_dir, args.force, args.dry_run,
                     claimed, sources)
        results.append(r)
        if not args.json:
            print(describe(r), flush=True)

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(summary(results))
    return 1 if any(r["status"] in FAILING for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
