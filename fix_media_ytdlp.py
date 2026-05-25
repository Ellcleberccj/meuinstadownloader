from pathlib import Path

YTDLP_OLD_APP_INLINE = '["yt-dlp", "--no-playlist", "--max-filesize", "250M", "-x", "--audio-format", "mp3", "--audio-quality", "0", "-o", template, url]'
YTDLP_NEW_APP_INLINE = '["yt-dlp", "--js-runtimes", "node", "--no-playlist", "--max-filesize", "250M", "-x", "--audio-format", "mp3", "--audio-quality", "0", "-o", template, url]'

YTDLP_OLD_REF_INLINE = '["yt-dlp", "--no-playlist", "--max-filesize", "250M", "-o", output_template, url]'
YTDLP_NEW_REF_INLINE = '["yt-dlp", "--js-runtimes", "node", "--no-playlist", "--max-filesize", "250M", "-o", output_template, url]'

for filename in ["app.py", "reference_tts.py"]:
    path = Path(filename)
    if not path.exists():
        continue
    s = path.read_text(encoding="utf-8")
    before = s

    s = s.replace(YTDLP_OLD_APP_INLINE, YTDLP_NEW_APP_INLINE)
    s = s.replace(YTDLP_OLD_REF_INLINE, YTDLP_NEW_REF_INLINE)

    # Also handle the pretty multi-line command inserted by patch_loading.py.
    s = s.replace(
        'cmd = [\n            "yt-dlp",\n            "--no-playlist",',
        'cmd = [\n            "yt-dlp",\n            "--js-runtimes", "node",\n            "--no-playlist",'
    )

    # Handle reference_tts.py generic media command if formatted over one line.
    s = s.replace(
        'run_checked(["yt-dlp", "--no-playlist", "--max-filesize", "250M", "-o", output_template, url], "Falha ao baixar a mídia pública/autorizada")',
        'run_checked(["yt-dlp", "--js-runtimes", "node", "--no-playlist", "--max-filesize", "250M", "-o", output_template, url], "Falha ao baixar a mídia pública/autorizada")'
    )

    if s != before:
        path.write_text(s, encoding="utf-8")
        print(f"Patched yt-dlp command in {filename}")
