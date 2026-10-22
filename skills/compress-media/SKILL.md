---
name: compress-media
description: Shrinks video, audio and image files with ffmpeg, writing a smaller copy beside each untouched original - phone videos, screen recordings, WAV or FLAC audio, PNG, JPEG and HEIC photos, and animated GIFs. Keeps HDR, rotation and audio, and discards results that are not smaller. Also converts between media formats (HEVC, H.264 or AV1 video, AAC, MP3 or Opus audio, JPEG, WebP or AVIF images, GIF to MP4), pulls the audio out of a video, compresses a whole folder, and fits a file under a size limit for an email or chat upload. Invoked explicitly as /compress-media with a file or folder and optional flags. Not for zip archives, PDFs, documents or video editing such as trimming.
argument-hint: "<file-or-folder> [--to TARGET] [--quality low|medium|high] [--max-size SIZE]"
disable-model-invocation: true
---

# compress-media

One script probes each file with ffprobe, picks a format and quality, encodes with ffmpeg, and writes `<name>_small.<ext>` beside the original, which it never modifies.

## Usage

```
python3 <skill-dir>/scripts/compress_media.py PATH [PATH ...] [options]
```

Pass the arguments of `/compress-media <args>` to the script, shell-quoting each path.
With no arguments, ask the user which file or folder to compress.

Give the Bash call `timeout: 600000`.
HEVC encodes 1080p video slower than real time on a laptop (a 55 s clip took 87 s), so run anything over about three minutes of video, or a folder of videos, with `run_in_background`.

| Option | Effect |
|---|---|
| `--to TARGET` | Set the output format from the Formats table. Without it, the default for the input kind is used. |
| `--quality low\|medium\|high` | Set the quality level; the default is `medium`. Offer `high` when the user says the result looks soft. |
| `--max-size SIZE` | Fit each output under a limit such as `25MB` or `500KB`. Units are 1024-based; a bare number means MB. |
| `--out DIR` | Write outputs to `DIR` instead of beside each source. |
| `--recursive` | Descend into subfolders when a folder is given. |
| `--force` | Replace an existing `_small` output. The source is never replaced. |
| `--dry-run` | Print the commands that would run and write nothing. |
| `--json` | Print results as JSON. |

## Formats

| Input | Default | Other `--to` targets |
|---|---|---|
| Video: mov mp4 m4v mkv webm avi mts m2ts 3gp wmv flv mpg | `hevc` (MP4) | `h264` (MP4, alias `mp4`), `av1` (WebM), or `aac`, `mp3`, `opus` to keep only the audio |
| Audio: wav aiff flac m4a mp3 aac ogg opus wma caf | `aac` (M4A) | `mp3`, `opus` |
| Image: jpg png webp tiff bmp jp2 avif | `jpeg`, or `webp` when the image has transparency | `webp`, `avif`, `jpeg` |
| HEIC and HEIF, macOS only, through `sips` | `jpeg` | `webp`, `avif` |
| GIF | `h264` (MP4) when animated, `webp` for a still | `hevc`, `av1`, `webp` (animated) |

Choose the target by where the file is going.
`hevc` gives the smallest file that Apple devices and current players open.
`h264` plays everywhere, including older Windows machines and upload forms that reject HEVC.
`av1` gives the smallest file but is slow to encode and needs a recent player.
For images, `webp` suits the web and `jpeg` suits anything else.

## Behavior

- Without `--to`, a result that is not smaller is deleted and reported as `kept-original`.
  With `--to`, the output is kept even when it is larger, with a note saying so.
  HEIC input usually ends up `kept-original`, because HEIC is already more compact than JPEG; pass `--to jpeg` to convert it anyway.
- HDR video stays HDR in `hevc` and `av1`.
  `h264` converts it to standard range so it does not look washed out.
- Phone rotation is applied to the pixels.
  Only the first video and audio tracks are kept; subtitles and extra data tracks are dropped.
- JPEG and AVIF output has no transparency, so transparent areas become white.
- Images written by ffmpeg have no EXIF data (date, camera, location); HEIC to JPEG through `sips` keeps all of it, location included.
  Video and audio keep their creation date and drop location tags.
- Two sources that map to one output name fail rather than overwrite each other, and an output never replaces a file named as a source.
- `--max-size` on video tries the quality preset first.
  If that is over the limit, it encodes two-pass at the bitrate the limit allows and retries once 15% lower.
  It refuses a limit that leaves under 100 kbps of video, and it works with `hevc` and `h264` only.
  Audio uses the lower of the preset bitrate and the bitrate the limit allows, and retries once 15% lower.
  Images step down a quality ladder until they fit.
- A folder run takes only files with media extensions.
  Hidden files and names ending in `_small` are skipped, and an existing output reports `exists`, so a rerun only processes new files.

## Reading the result

The script prints one line per file, then a summary.

```
IMG_0412.MOV  video -> hevc  113.2 MB -> 5.9 MB  -95%  IMG_0412_small.mp4
beach.heic  kept-original: 1.0 MB, the result was not smaller, so it was discarded
2 file(s): 1 done, 1 kept-original; 113.2 MB -> 5.9 MB across the compressed files
```

Statuses are `done`, `kept-original`, `exists`, `planned` (dry run), `failed` and `unsupported`.
The exit code is 1 when a file failed or was unsupported, 2 when ffmpeg is missing (stderr then gives the install command) or an option is invalid, and 0 otherwise.
A build of ffmpeg that lacks an encoder fails that file and names the encoder.

Tell the user the before and after sizes, the output path and any note.
The output is lossy, so ask the user to check it before deleting the original.

## Tests

The tests run with `python3 -m unittest discover -s <skill-dir>/tests`.
