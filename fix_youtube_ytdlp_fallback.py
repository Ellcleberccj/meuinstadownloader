import re
from pathlib import Path

REFERENCE_PATCH = r'''
def youtube_cookie_error_message(has_cookies):
    if has_cookies:
        return (
            "O YouTube bloqueou o download mesmo com YTDLP_COOKIES_B64 configurado. "
            "Isso não prova que os cookies estão errados: pode ser bloqueio do IP da Railway, "
            "limite temporário, exigência de PO Token ou mudança no cliente/player do YouTube. "
            "O app tentou clientes alternativos do yt-dlp antes de desistir. "
            "Tente outro link, aguarde um pouco, ou use uma mídia já baixada/autorizada."
        )
    return "O YouTube pediu login/bot e YTDLP_COOKIES_B64 não está configurada no container. Configure cookies do YouTube em formato Netscape convertido para Base64 na Railway e faça redeploy."


def ytdlp_retryable_detail(detail):
    text = (detail or "").lower()
    markers = [
        "sign in to confirm",
        "not a bot",
        "requested format is not available",
        "only images are available",
        "n challenge solving failed",
        "remote component challenge",
        "http error 403",
    ]
    return any(marker in text for marker in markers)


def ytdlp_common_args(cookie_args):
    args = [
        "yt-dlp",
        *cookie_args,
        "--js-runtimes", "node",
        "--remote-components", "ejs:github",
        "--no-playlist",
        "--max-filesize", "250M",
        "-f", "ba/bestaudio/best",
    ]
    user_agent = env_text("YTDLP_USER_AGENT", "")
    if user_agent:
        args.extend(["--user-agent", user_agent])
    return args


def ytdlp_reference_commands(cookie_args, output_template, url, is_youtube):
    base = ytdlp_common_args(cookie_args)
    commands = [base + ["-o", output_template, url]]
    if not is_youtube:
        return commands

    extractor_attempts = []
    custom_extractor_args = env_text("YTDLP_EXTRACTOR_ARGS", "")
    if custom_extractor_args:
        extractor_attempts.append(custom_extractor_args)
    extractor_attempts.extend([
        "youtube:player_client=tv,mweb",
        "youtube:player_client=web_safari,web_embedded",
        "youtube:player_client=web",
    ])

    for extractor_args in extractor_attempts:
        commands.append(base + ["--extractor-args", extractor_args, "-o", output_template, url])
    return commands


def cleanup_generic_media_outputs(workdir):
    for file in Path(workdir).glob("generic_media.*"):
        try:
            file.unlink(missing_ok=True)
        except OSError:
            pass


def run_ytdlp_reference_download(cookie_args, output_template, url, workdir, is_youtube):
    errors = []
    for command in ytdlp_reference_commands(cookie_args, output_template, url, is_youtube):
        cleanup_generic_media_outputs(workdir)
        try:
            run_checked(command, "Falha ao baixar a mídia pública/autorizada")
            return pick_audio_source(workdir)
        except RuntimeError as exc:
            detail = str(exc)
            errors.append(detail)
            if not ytdlp_retryable_detail(detail):
                raise

    last_error = errors[-1] if errors else "erro desconhecido"
    if is_youtube and ytdlp_retryable_detail(last_error):
        raise RuntimeError(f"{youtube_cookie_error_message(bool(cookie_args))} Último detalhe do yt-dlp: {last_error[:700]}")
    raise RuntimeError(last_error)

'''

DOWNLOAD_BLOCK = '''    output_template = str(workdir / "generic_media.%(ext)s")
    cookie_args = ytdlp_cookie_args(workdir)
    is_youtube = "youtube.com" in host or "youtu.be" in host
    return run_ytdlp_reference_download(cookie_args, output_template, url, workdir, is_youtube)
'''


def patch_reference_tts(text):
    if "def ytdlp_reference_commands(" not in text:
        text = re.sub(
            r'\ndef youtube_cookie_error_message\(has_cookies\):.*?\n\ndef clamp_reference_seconds\(',
            REFERENCE_PATCH + "\ndef clamp_reference_seconds(",
            text,
            count=1,
            flags=re.S,
        )

    text = re.sub(
        r'    output_template = str\(workdir / "generic_media\.%(ext\)s"\)\n'
        r'    cookie_args = ytdlp_cookie_args\(workdir\)\n'
        r'    command = \[\n.*?\n'
        r'    return pick_audio_source\(workdir\)\n',
        DOWNLOAD_BLOCK,
        text,
        count=1,
        flags=re.S,
    )
    return text


path = Path("reference_tts.py")
if path.exists():
    before = path.read_text(encoding="utf-8")
    after = patch_reference_tts(before)
    if after != before:
        path.write_text(after, encoding="utf-8")
        print("Patched reference_tts.py YouTube yt-dlp fallback")

    required = [
        '"--js-runtimes", "node"',
        '"--remote-components", "ejs:github"',
        '"-f", "ba/bestaudio/best"',
        '"--extractor-args"',
        "run_ytdlp_reference_download",
    ]
    missing = [item for item in required if item not in path.read_text(encoding="utf-8")]
    if missing:
        raise RuntimeError("Failed to patch YouTube yt-dlp fallback in reference_tts.py: " + ", ".join(missing))
