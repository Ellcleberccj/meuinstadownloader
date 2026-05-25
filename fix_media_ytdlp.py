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

REF_DOWNLOAD_BLOCK = '''    output_template = str(workdir / "generic_media.%(ext)s")
    cookie_args = ytdlp_cookie_args(workdir)
    command = [
        "yt-dlp",
        *cookie_args,
        "--js-runtimes", "node",
        "--remote-components", "ejs:github",
        "--no-playlist",
        "--max-filesize", "250M",
        "-o", output_template,
        url,
    ]
    try:
        run_checked(command, "Falha ao baixar a mídia pública/autorizada")
    except RuntimeError as exc:
        detail = str(exc)
        if "Sign in to confirm" in detail or "not a bot" in detail:
            raise RuntimeError(youtube_cookie_error_message(bool(cookie_args))) from exc
        raise
    return pick_audio_source(workdir)
'''

OLD_COOKIE_MESSAGE = "O YouTube recusou os cookies configurados em YTDLP_COOKIES_B64. Exporte cookies novos do YouTube em formato Netscape, converta para Base64, atualize a variável na Railway e faça redeploy."
NEW_COOKIE_MESSAGE = "O YouTube bloqueou o download mesmo com YTDLP_COOKIES_B64 configurado. Se o log mostrar YTDLP_COOKIES_B64 configured: True, os cookies chegaram ao container; o bloqueio pode ser IP da Railway, sessão vencida, cliente/player do YouTube ou cookies recusados. Tente outro link, aguarde, ou use uma mídia já baixada/autorizada."


def add_cookie_helper(s):
    if "def ytdlp_cookie_args(" in s:
        return s
    if "def valid_media_url(" in s:
        return s.replace("\ndef valid_media_url(url):", COOKIE_HELPER + "\ndef valid_media_url(url):", 1)
    if "def audio_source_files(" in s:
        return s.replace("\ndef audio_source_files(root):", COOKIE_HELPER + "\ndef audio_source_files(root):", 1)
    return s


def cleanup_duplicate_ytdlp_args(s):
    replacements = {
        '*ytdlp_cookie_args(workdir),\n            *ytdlp_cookie_args(workdir),': '*ytdlp_cookie_args(workdir),',
        '*ytdlp_cookie_args(workdir), *ytdlp_cookie_args(workdir),': '*ytdlp_cookie_args(workdir),',
        '"--remote-components", "ejs:github",\n            "--remote-components", "ejs:github",': '"--remote-components", "ejs:github",',
        '"--remote-components", "ejs:github", "--remote-components", "ejs:github",': '"--remote-components", "ejs:github",',
    }
    for old, new in replacements.items():
        s = s.replace(old, new)
    return s


def patch_app_py(s):
    s = add_cookie_helper(s)
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
    s = s.replace(OLD_COOKIE_MESSAGE, NEW_COOKIE_MESSAGE)
    s = re.sub(
        r'    output_template = str\(workdir / "generic_media\.%\(ext\)s"\)\n.*?    return pick_audio_source\(workdir\)\n',
        REF_DOWNLOAD_BLOCK,
        s,
        count=1,
        flags=re.S,
    )
    s = cleanup_duplicate_ytdlp_args(s)
    return s


def command_block(s, start_marker):
    start = s.find(start_marker)
    if start < 0:
        return ""
    end = s.find("\n    return pick_audio_source(workdir)", start)
    if end < 0:
        end = s.find("\n        ]", start)
    return s[start:end] if end > start else s[start:start + 900]


def has_required_app_ytdlp_args(s):
    block = command_block(s, 'cmd = [')
    return all(item in block for item in [
        "ytdlp_cookie_args(workdir)",
        '"--js-runtimes", "node"',
        '"--remote-components", "ejs:github"',
        '"-x"',
        '"--audio-format", "mp3"',
    ])


def has_required_reference_ytdlp_args(s):
    block = command_block(s, 'output_template = str(workdir / "generic_media.%(ext)s")')
    return all(item in block for item in [
        "cookie_args = ytdlp_cookie_args(workdir)",
        "*cookie_args",
        '"--js-runtimes", "node"',
        '"--remote-components", "ejs:github"',
        '"-o", output_template',
        'run_checked(command, "Falha ao baixar a mídia pública/autorizada")',
    ])


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

    if filename == "app.py" and not has_required_app_ytdlp_args(s):
        raise RuntimeError("Failed to patch yt-dlp cookies/node/EJS args in app.py")
    if filename == "reference_tts.py" and not has_required_reference_ytdlp_args(s):
        raise RuntimeError("Failed to patch yt-dlp cookies/node/EJS args in reference_tts.py")
