import base64
import io
import os
import re
import shutil
import tempfile
import threading
import zipfile
from functools import wraps
from pathlib import Path

from flask import Flask, Response, flash, redirect, render_template_string, request, send_file, url_for

import instaloader
from instaloader import Profile
from instaloader.exceptions import (
    BadCredentialsException,
    ConnectionException,
    InstaloaderException,
    LoginException,
    LoginRequiredException,
    ProfileNotExistsException,
    TwoFactorAuthRequiredException,
)

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-me-in-railway-vars")

DATA_DIR = Path(os.getenv("DATA_DIR", "/data" if Path("/data").exists() else "./data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
SESSION_DIR = DATA_DIR / "sessions"
SESSION_DIR.mkdir(parents=True, exist_ok=True)

USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")
LOCK = threading.Lock()

INDEX_HTML = """
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Instagram Stories Downloader</title>
  <style>
    :root { color-scheme: dark; }
    body { margin: 0; font-family: Inter, system-ui, Arial, sans-serif; background: #0f1115; color: #f4f4f5; }
    main { max-width: 720px; margin: 0 auto; padding: 48px 20px; }
    .card { background: #171a21; border: 1px solid #2b2f3a; border-radius: 22px; padding: 28px; box-shadow: 0 20px 60px rgba(0,0,0,.25); }
    h1 { margin: 0 0 10px; font-size: 32px; line-height: 1.1; }
    p { color: #b6bac6; line-height: 1.55; }
    label { display: block; margin: 22px 0 8px; font-weight: 700; }
    input { width: 100%; box-sizing: border-box; padding: 14px 16px; border-radius: 14px; border: 1px solid #3a3f4c; background: #0f1115; color: white; font-size: 16px; }
    button { margin-top: 20px; width: 100%; padding: 15px 18px; border: 0; border-radius: 14px; background: #f4f4f5; color: #111827; font-weight: 800; font-size: 16px; cursor: pointer; }
    .msg { padding: 12px 14px; border-radius: 14px; margin: 16px 0; background: #312320; color: #ffd7c2; border: 1px solid #744534; }
    .note { font-size: 14px; }
    code { background: #0f1115; border: 1px solid #2b2f3a; border-radius: 8px; padding: 2px 6px; }
  </style>
</head>
<body>
<main>
  <div class="card">
    <h1>Baixar stories do Instagram</h1>
    <p>Digite o @ de um perfil para baixar os stories disponíveis em um arquivo ZIP. Use apenas com conteúdo público, seu próprio conteúdo ou contas para as quais você tem autorização.</p>
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        {% for message in messages %}<div class="msg">{{ message }}</div>{% endfor %}
      {% endif %}
    {% endwith %}
    <form method="post" action="{{ url_for('download') }}">
      <label for="username">Usuário do Instagram</label>
      <input id="username" name="username" placeholder="exemplo: instagram" autocomplete="off" required>
      <button type="submit">Baixar stories em ZIP</button>
    </form>
    <p class="note">Observação: o Instagram normalmente exige login para stories. Configure <code>IG_USERNAME</code> e <code>IG_PASSWORD</code> nas variáveis da Railway, ou monte uma sessão persistente em <code>/data</code>.</p>
  </div>
</main>
</body>
</html>
"""


def require_basic_auth(fn):
    app_user = os.getenv("APP_USERNAME")
    app_pass = os.getenv("APP_PASSWORD")
    if not app_user or not app_pass:
        return fn

    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth = request.authorization
        if not auth or auth.username != app_user or auth.password != app_pass:
            return Response(
                "Autenticação necessária", 401,
                {"WWW-Authenticate": 'Basic realm="Stories Downloader"'}
            )
        return fn(*args, **kwargs)

    return wrapper


def normalize_username(value: str) -> str:
    value = (value or "").strip()
    value = value.removeprefix("@").strip("/")
    if "instagram.com/" in value:
        value = value.split("instagram.com/", 1)[1].split("/", 1)[0]
    if not USERNAME_RE.fullmatch(value):
        raise ValueError("Usuário inválido. Use apenas o @ ou a URL do perfil.")
    return value


def load_session_from_env(session_path: Path) -> None:
    encoded = os.getenv("IG_SESSION_B64")
    if encoded and not session_path.exists():
        session_path.write_bytes(base64.b64decode(encoded))


def build_loader(download_dir: Path) -> instaloader.Instaloader:
    loader = instaloader.Instaloader(
        dirname_pattern=str(download_dir / "{target}"),
        filename_pattern="{date_utc}_UTC_{mediaid}",
        download_pictures=True,
        download_videos=True,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        quiet=True,
        request_timeout=120,
        max_connection_attempts=2,
        sanitize_paths=True,
    )

    ig_user = os.getenv("IG_USERNAME")
    ig_pass = os.getenv("IG_PASSWORD")
    if not ig_user:
        raise LoginRequiredException("Configure IG_USERNAME e IG_PASSWORD nas variáveis da Railway.")

    session_path = SESSION_DIR / f"session-{ig_user}"
    load_session_from_env(session_path)

    if session_path.exists():
        try:
            loader.load_session_from_file(ig_user, str(session_path))
            return loader
        except Exception:
            session_path.unlink(missing_ok=True)

    if not ig_pass:
        raise LoginRequiredException("Sessão não encontrada e IG_PASSWORD não foi configurado.")

    loader.login(ig_user, ig_pass)
    loader.save_session_to_file(str(session_path))
    return loader


def zip_directory(source_dir: Path, username: str) -> io.BytesIO:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file in source_dir.rglob("*"):
            if file.is_file():
                zf.write(file, file.relative_to(source_dir))
    buffer.seek(0)
    return buffer


@app.get("/")
@require_basic_auth
def index():
    return render_template_string(INDEX_HTML)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/download")
@require_basic_auth
def download():
    try:
        username = normalize_username(request.form.get("username", ""))
    except ValueError as exc:
        flash(str(exc))
        return redirect(url_for("index"))

    temp_root = Path(tempfile.mkdtemp(prefix="stories_"))
    try:
        with LOCK:
            loader = build_loader(temp_root)
            profile = Profile.from_username(loader.context, username)
            downloaded_count = 0
            for story in loader.get_stories(userids=[profile.userid]):
                for item in story.get_items():
                    if loader.download_storyitem(item, target=username):
                        downloaded_count += 1

        if downloaded_count == 0:
            flash("Nenhum story disponível foi encontrado para esse perfil, ou os arquivos já estavam indisponíveis.")
            return redirect(url_for("index"))

        zip_buffer = zip_directory(temp_root, username)
        return send_file(
            zip_buffer,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"{username}_stories.zip",
            max_age=0,
        )

    except ProfileNotExistsException:
        flash("Perfil não encontrado.")
        return redirect(url_for("index"))
    except TwoFactorAuthRequiredException:
        flash("Essa conta tem 2FA. Gere uma sessão local e envie como IG_SESSION_B64, ou use uma conta sem 2FA para automação.")
        return redirect(url_for("index"))
    except (BadCredentialsException, LoginException):
        flash("Falha no login do Instagram. Confira IG_USERNAME e IG_PASSWORD na Railway.")
        return redirect(url_for("index"))
    except LoginRequiredException as exc:
        flash(str(exc))
        return redirect(url_for("index"))
    except ConnectionException as exc:
        flash(f"Erro de conexão/limite do Instagram: {exc}")
        return redirect(url_for("index"))
    except InstaloaderException as exc:
        flash(f"Erro do Instaloader: {exc}")
        return redirect(url_for("index"))
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
