#!/usr/bin/env python3

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path


def run_cmd(cmd: list[str], check: bool = True, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        cmd,
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            "Command failed: {}\nSTDOUT: {}\nSTDERR: {}".format(
                " ".join(cmd), proc.stdout.strip(), proc.stderr.strip()
            )
        )
    return proc


def parse_entries(path: Path) -> list[tuple[str, float]]:
    line_re = re.compile(r"^\s*(\d{1,2}):(\d{2})\s+(.+?)\s*$")
    entries: list[tuple[str, float]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        if line.lstrip().startswith("#"):
            continue
        match = line_re.match(line)
        if not match:
            raise ValueError(
                f"Invalid timestamp format on line {line_no}: {line}\n"
                "Expected: MM:SS Name"
            )
        mins, secs, name = match.groups()
        start = int(mins) * 60 + int(secs)
        entries.append((name.strip(), float(start)))
    if not entries:
        raise ValueError("No valid timestamp entries found")
    return entries


def safe_name(name: str, used: dict[str, int]) -> str:
    cleaned = re.sub(r"[<>:\"/|?*]", "", name)
    cleaned = re.sub(r"\s+", "_", cleaned.strip())
    cleaned = re.sub(r"_+", "_", cleaned)
    cleaned = cleaned.strip("._-")
    if not cleaned:
        cleaned = "meme"
    if len(cleaned) > 120:
        cleaned = cleaned[:120]
    count = used.get(cleaned, 0)
    used[cleaned] = count + 1
    if count:
        return f"{cleaned}_{count}"
    return cleaned


def download_audio(url: str, workdir: Path) -> Path:
    audio_dir = workdir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(audio_dir / "%(title)s.%(ext)s")

    cmd = [
        "yt-dlp",
        "--no-playlist",
        "-f",
        "bestaudio/best",
        "-x",
        "--audio-format",
        "mp3",
        "--audio-quality",
        "0",
        "--extractor-args",
        "youtube:player_client=android",
        "-o",
        output_template,
        url,
    ]

    proc = run_cmd(cmd, check=False)
    if proc.returncode != 0:
        # Retry without Android client if token-sensitive formats fail.
        cmd = [
            "yt-dlp",
            "--no-playlist",
            "-f",
            "bestaudio/best",
            "-x",
            "--audio-format",
            "mp3",
            "--audio-quality",
            "0",
            "-o",
            output_template,
            url,
        ]
        proc = run_cmd(cmd, check=True)

    mp3_files = sorted(audio_dir.glob("*.mp3"))
    if not mp3_files:
        # Keep error message explicit when yt-dlp output is not enough.
        raise RuntimeError("yt-dlp completed but no mp3 file was found")
    # If multiple files appear (rare), keep the most recent.
    return max(mp3_files, key=lambda p: p.stat().st_mtime)


def get_audio_duration(path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    proc = run_cmd(cmd, check=True)
    return float(proc.stdout.strip())


def cut_clip(input_path: Path, start: float, end: float, out_path: Path) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start:.3f}",
        "-to",
        f"{end:.3f}",
        "-i",
        str(input_path),
        "-c",
        "copy",
        str(out_path),
    ]
    run_cmd(cmd, check=True)


def ensure_folder_exists(service, folder_name: str = "MEME_sounds") -> str:
    query = (
        "mimeType='application/vnd.google-apps.folder' and "
        "name='{}' and trashed=false".format(folder_name)
    )
    results = (
        service.files()
        .list(q=query, fields="files(id,name)", pageSize=2)
        .execute()
    )
    for item in results.get("files", []):
        if item.get("name") == folder_name:
            return item["id"]

    metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    created = service.files().create(body=metadata, fields="id").execute()
    return created["id"]


def upload_to_drive(service_account: str, files: list[Path], folder_id: str) -> list[dict[str, str]]:
    from google.oauth2 import service_account as sa
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = sa.Credentials.from_service_account_file(
        service_account, scopes=["https://www.googleapis.com/auth/drive.file"]
    )
    service = build("drive", "v3", credentials=creds, static_discovery=False)
    folder = ensure_folder_exists(service)
    uploads: list[dict[str, str]] = []

    for f in files:
        metadata = {"name": f.name, "parents": [folder]}
        media = MediaFileUpload(str(f), mimetype="audio/mpeg", resumable=True)
        created = (
            service.files()
            .create(body=metadata, media_body=media, fields="id,name,webViewLink")
            .execute()
        )
        uploads.append(created)

    return uploads


def process_audio(
    audio_path: Path,
    entries: list[tuple[str, float]],
    clips_dir: Path,
    duration: float,
) -> tuple[list[dict[str, object]], list[str]]:
    clips_dir.mkdir(parents=True, exist_ok=True)
    used = {}
    results: list[dict[str, object]] = []
    missing: list[str] = []

    for i, (name, start) in enumerate(entries):
        end = entries[i + 1][1] if i + 1 < len(entries) else duration
        if end <= start:
            missing.append(name)
            continue
        out_file = clips_dir / f"{safe_name(name, used)}.mp3"
        cut_clip(audio_path, start, end, out_file)
        results.append(
            {
                "name": name,
                "start": start,
                "end": end,
                "file": str(out_file),
            }
        )
    return results, missing


def write_report(workdir: Path, expected: int, produced: int, missing: list[str], output_dir: Path, uploads: list[dict[str, str]] | None = None) -> Path:
    report = {
        "expected": expected,
        "produced": produced,
        "missing_count": len(missing),
        "missing": missing,
        "output_dir": str(output_dir),
    }
    if uploads:
        report["uploads"] = uploads
    report_path = workdir / "report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Split a YouTube audio file into meme clips by timestamps"
    )
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument("timestamps", help="Path to timestamp list file")
    parser.add_argument("--workdir", default="/tmp/meme_sound_project", help="Working directory")
    parser.add_argument("--service-account", dest="service_account", help="Google service account JSON path")
    parser.add_argument("--cleanup", action="store_true", help="Delete working directory after success")
    args = parser.parse_args()

    workdir = Path(args.workdir).expanduser().resolve()
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    try:
        entries = parse_entries(Path(args.timestamps).expanduser().resolve())
        audio_path = download_audio(args.url, workdir)
        duration = get_audio_duration(audio_path)
        clips_dir = workdir / "clips"
        produced_files, missing = process_audio(audio_path, entries, clips_dir, duration)
        produced = len(produced_files)

        upload_result: list[dict[str, str]] = []
        if args.service_account:
            files = [Path(item["file"]) for item in produced_files]
            if files:
                upload_result = upload_to_drive(args.service_account, files, "MEME_sounds")

        write_report(
            workdir,
            expected=len(entries),
            produced=produced,
            missing=missing,
            output_dir=clips_dir,
            uploads=upload_result if upload_result else None,
        )

        if args.cleanup:
            shutil.rmtree(workdir)

        result = {
            "expected": len(entries),
            "produced": produced,
            "missing_count": len(missing),
            "missing": missing,
            "output_dir": str(clips_dir),
        }
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:  # keep a simple command-line fail mode
        print(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
