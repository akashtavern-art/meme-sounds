# Meme Sound Extractor

Standalone script to download a YouTube video's audio and cut meme clips from a
timestamp list.

The input format is one item per line:

```
MM:SS Clip Name
```

Each clip starts at the timestamp and ends at the next timestamp (last one goes
to the end of the source audio).

## Files

- `run.py` main pipeline
- `timestamps.txt` sample timestamp list
- `requirements.txt` Python dependencies
- `.gitignore`

## Requirements

- `yt-dlp` and `ffmpeg` installed on PATH
- Python 3.10+

Install Python deps:

```bash
python -m pip install -r requirements.txt
```

## Usage

```bash
python run.py "<youtube-url>" timestamps.txt \
  --workdir /tmp/meme_sound_project
```

Keep generated files:

```bash
python run.py "<youtube-url>" timestamps.txt --workdir /tmp/meme_sound_project
```

Cleanup automatically:

```bash
python run.py "<youtube-url>" timestamps.txt --workdir /tmp/meme_sound_project --cleanup
```

Upload to Google Drive folder `MEME_sounds` (service account JSON required):

```bash
python run.py "<youtube-url>" timestamps.txt \
  --service-account /path/to/service-account.json
```

The script prints a small JSON summary:

```json
{
  "expected": 217,
  "produced": 217,
  "missing_count": 0,
  "missing": [],
  "output_dir": "/tmp/meme_sound_project/clips"
}
```

## Notes

- If YouTube throttles one extractor mode, the script retries using a fallback.
- Google API authentication is optional; without credentials upload is skipped.
