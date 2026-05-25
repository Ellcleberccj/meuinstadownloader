import os
import re
from pathlib import Path

COOKIE_HELPER = '''

def ytdlp_cookie_args(workdir):
    cookies_b64 = (os.getenv("YTDLP_COOKIES_B64") or "").strip()
    if not cookies_b64:
        return []
    cookies_path = Path(workdir) / "yt_dlp_cookies.txt"
    try:
        cookies_path.write_bytes(__import__("base64").b64decode(cookies_b64))
    except Exception as exc:
        raise RuntimeError("YTDLP_COOKIES_B64 inválida. Gere um cookies.txt em formato Netscape e salve o conteúdo em Base64.") from exc
    if not cookies_path.exists() or cookies_path.stat().st_size == 0:
        raise RuntimeError("YTDLP_COOKIES_B64 gerou um arquivo de cookies vazio. Exporte os cookies do YouTube em formato Netscape e converta para Base64.")
    return ["--cookies", str(cookies_path)]
'''

YTDLP_OLD_APP_INLINE = '["yt-dlp", "--no-playlist", "--max-filesize", "250M", "-x", "--audio-format", "mp3", "--audio-quality", "0", "-o", template, url]'
YTDLP_JS_APP_INLINE = '["yt-dlp", "--js-runtimes", "node", "--no-playlist", "--max-filesize", "250M", "-x", "--audio-format", "mp3", "--audio-quality", "0", "-o", template, url]'
YTDLP_COOKIE_JS_APP_INLINE = '["yt-dlp", *ytdlp_cookie_args(workdir), "--js-runtimes", "node", "--no-playlist", "--max-filesize", "250M", "-x", "--audio-format", "mp3", "--audio-quality", "0", "-o", template, url]'
YTDLP_JS_REMOTE_APP_INLINE = '["yt-dlp", "--js-runtimes", "node", "--remote-components", "ejs:github", "--no-playlist", "--max-filesize", "250M", "-x", "--audio-format", "mp3", "--audio-quality", "0", "-o", template, url]'
YTDLP_NEW_APP_INLINE = '["yt-dlp", *ytdlp_cookie_args(workdir), "--js-runtimes", "node", "--remote-components", "ejs:github", "--no-playlist", "--max-filesize", "250M", "-x", "--audio-format", "mp3", "--audio-quality", "0", "-o", template, url]'

YTDLP_OLD_REF_INLINE = '["yt-dlp", "--no-playlist", "--max-filesize", "250M", "-o", output_template, url]'
YTDLP_JS_REF_INLINE = '["yt-dlp", "--js-runtimes", "node", "--no-playlist", "--max-filesize", "250M", "-o", output_template, url]'
YTDLP_COOKIE_JS_REF_INLINE = '["yt-dlp", *ytdlp_cookie_args(workdir), "--js-runtimes", "node", "--no-playlist", "--max-filesize", "250M", "-o", output_template, url]'
YTDLP_JS_REMOTE_REF_INLINE = '["yt-dlp", "--js-runtimes", "node", "--remote-components", "ejs:github", "--no-playlist", "--max-filesize", "250M", "-o", output_template, url]'
YTDLP_NEW_REF_INLINE = '["yt-dlp", *ytdlp_cookie_args(workdir), "--js-runtimes", "node", "--remote-components", "ejs:github", "--no-playlist", "--max-filesize", "250M", "-o", output_template, url]'

APP_CMD_BLOCK = '''cmd = [
            "yt-dlp",
            *ytdlp_cookie_args(workdir),
            "--js-runtimes", "node",
            "--remote-components", "ejs:github",
            "--no-playlist",
            "--max-filesize", "250M",
            "-x",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "-o", template,
            url,
        ]'''

REF_CMD_INLINE = 'run_checked(["yt-dlp", *ytdlp_cookie_args(workdir), "--js-runtimes", "node", "--remote-components", "ejs:github", "--no-playlist", "--max-filesize", "250M", "-o", output_template, url], "Falha ao baixar a mídia pública/autorizada")'


def add_cookie_helper(s):
    if "def ytdlp_cookie_args(" in s:
        return s
    if "def valid_media_url(" in s:
        return s.replace("\ndef valid_media_url(url):", COOKIE_HELPER + "\ndef valid_media_url(url):", 1)
    if "def audio_source_files(" in s:
        return s.replace("\ndef audio_source_files(root):", COOKIE_HELPER + "\ndef audio_source_files(root):", 1)
    return s


def cleanup_duplicate_ytdlp_args(s):
    s = s.replace(
        '*ytdlp_cookie_args(workdir),\n            *ytdlp_cookie_args(workdir),',
        '*ytdlp_cookie_args(workdir),'
    )
    s = s.replace(
        '*ytdlp_cookie_args(workdir), *ytdlp_cookie_args(workdir),',
        '*ytdlp_cookie_args(workdir),'
    )
    s = s.replace(
        '"--remote-components", "ejs:github",\n            "--remote-components", "ejs:github",',
        '"--remote-components", "ejs:github",'
    )
    s = s.replace(
        '"--remote-components", "ejs:github", "--remote-components", "ejs:github",',
        '"--remote-components", "ejs:github",'
    )
    return s


def patch_app_py(s):
    s = add_cookie_helper(s)
    s = s.replace(YTDLP_OLD_APP_INLINE, YTDLP_NEW_APP_INLINE)
    s = s.replace(YTDLP_JS_APP_INLINE, YTDLP_NEW_APP_INLINE)
    s = s.replace(YTDLP_COOKIE_JS_APP_INLINE, YTDLP_NEW_APP_INLINE)
    s = s.replace(YTDLP_JS_REMOTE_APP_INLINE, YTDLP_NEW_APP_INLINE)
    s = s.replace(
        'cmd = [\n            "yt-dlp",\n            "--no-playlist",',
        'cmd = [\n            "yt-dlp",\n            *ytdlp_cookie_args(workdir),\n            "--js-runtimes", "node",\n            "--remote-components", "ejs:github",\n            "--no-playlist",'
    )
    s = s.replace(
        'cmd = [\n            "yt-dlp",\n            "--js-runtimes", "node",\n            "--no-playlist",',
        'cmd = [\n            "yt-dlp",\n            *ytdlp_cookie_args(workdir),\n            "--js-runtimes", "node",\n            "--remote-components", "ejs:github",\n            "--no-playlist",'
    )
    s = s.replace(
        'cmd = [\n            "yt-dlp",\n            "--js-runtimes", "node",\n            "--remote-components", "ejs:github",\n            "--no-playlist",',
        'cmd = [\n            "yt-dlp",\n            *ytdlp_cookie_args(workdir),\n            "--js-runtimes", "node",\n            "--remote-components", "ejs:github",\n            "--no-playlist",'
    )
    s = s.replace(
        'cmd = [\n            "yt-dlp",\n            *ytdlp_cookie_args(workdir),\n            "--js-runtimes", "node",\n            "--no-playlist",',
        'cmd = [\n            "yt-dlp",\n            *ytdlp_cookie_args(workdir),\n            "--js-runtimes", "node",\n            "--remote-components", "ejs:github",\n            "--no-playlist",'
    )
    s = re.sub(
        r'cmd = \[\s*"yt-dlp",.*?"-o",\s*template,\s*url,\s*\]',
        APP_CMD_BLOCK,
        s,
        count=1,
        flags=re.S,
    )
    s = cleanup_duplicate_ytdlp_args(s)
    s = s.replace(
        "O YouTube bloqueou o IP da Railway e pediu confirmação de login/bot. Tente outro link, aguarde, ou use upload manual/arquivo já baixado.",
        "O YouTube bloqueou o IP da Railway e pediu confirmação de login/bot. Configure ou atualize YTDLP_COOKIES_B64, tente outro link, aguarde, ou use upload manual/arquivo já baixado."
    )
    return s


def patch_reference_tts_py(s):
    s = add_cookie_helper(s)
    s = s.replace(YTDLP_OLD_REF_INLINE, YTDLP_NEW_REF_INLINE)
    s = s.replace(YTDLP_JS_REF_INLINE, YTDLP_NEW_REF_INLINE)
    s = s.replace(YTDLP_COOKIE_JS_REF_INLINE, YTDLP_NEW_REF_INLINE)
    s = s.replace(YTDLP_JS_REMOTE_REF_INLINE, YTDLP_NEW_REF_INLINE)
    s = s.replace(
        'run_checked(["yt-dlp", "--no-playlist", "--max-filesize", "250M", "-o", output_template, url], "Falha ao baixar a mídia pública/autorizada")',
        REF_CMD_INLINE
    )
    s = s.replace(
        'run_checked(["yt-dlp", "--js-runtimes", "node", "--no-playlist", "--max-filesize", "250M", "-o", output_template, url], "Falha ao baixar a mídia pública/autorizada")',
        REF_CMD_INLINE
    )
    s = s.replace(
        'run_checked(["yt-dlp", *ytdlp_cookie_args(workdir), "--js-runtimes", "node", "--no-playlist", "--max-filesize", "250M", "-o", output_template, url], "Falha ao baixar a mídia pública/autorizada")',
        REF_CMD_INLINE
    )
    s = s.replace(
        'run_checked(["yt-dlp", "--js-runtimes", "node", "--remote-components", "ejs:github", "--no-playlist", "--max-filesize", "250M", "-o", output_template, url], "Falha ao baixar a mídia pública/autorizada")',
        REF_CMD_INLINE
    )
    s = re.sub(
        r'run_checked\(\["yt-dlp".*?output_template, url\],\s*"Falha ao baixar a mídia pública/autorizada"\)',
        REF_CMD_INLINE,
        s,
        count=1,
        flags=re.S,
    )
    s = re.sub(
        r'    output_template = str\(workdir / "generic_media\.%\(ext\)s"\)\n    cookie_args = ytdlp_cookie_args\(workdir\)\n    command = \[\n.*?    return pick_audio_source\(workdir\)\n',
        '    output_template = str(workdir / "generic_media.%(ext)s")\n    ' + REF_CMD_INLINE + '\n    return pick_audio_source(workdir)\n',
        s,
        count=1,
        flags=re.S,
    )
    s = cleanup_duplicate_ytdlp_args(s)
    return s


def has_required_ytdlp_args(s):
    return (
        "ytdlp_cookie_args(workdir)" in s
        and '"--js-runtimes", "node"' in s
        and '"--remote-components", "ejs:github"' in s
    )


print("YTDLP_COOKIES_B64 configured:", bool((os.getenv("YTDLP_COOKIES_B64") or "").strip()))

for filename in ["app.py", "reference_tts.py"]:
    path = Path(filename)
    if not path.exists():
        continue
    s = path.read_text(encoding="utf-8")
    before = s

    if filename == "app.py":
        s = patch_app_py(s)
    else:
        s = patch_reference_tts_py(s)

    if s != before:
        path.write_text(s, encoding="utf-8")
        print(f"Patched yt-dlp command in {filename}")

    if not has_required_ytdlp_args(s):
        raise RuntimeError(f"Failed to patch yt-dlp cookies/node/EJS args in {filename}")
