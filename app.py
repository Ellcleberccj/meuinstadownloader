import base64
import io
import json
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
from instaloader.exceptions import BadCredentialsException, ConnectionException, InstaloaderException, LoginException, LoginRequiredException, ProfileNotExistsException, TwoFactorAuthRequiredException

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-me")
DATA_DIR = Path(os.getenv("DATA_DIR", "/data" if Path("/data").exists() else "./data"))
SESSION_DIR = DATA_DIR / "sessions"
SESSION_DIR.mkdir(parents=True, exist_ok=True)
LOCK = threading.Lock()
USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")
LAST_LOGIN_STATUS = {"ok": None, "message": "Ainda não foi feito teste de login."}

HTML = """
<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Insta Downloader</title>
<style>:root{color-scheme:dark}body{margin:0;font-family:Inter,system-ui,Arial;background:#0f1115;color:#f4f4f5}main{max-width:760px;margin:auto;padding:48px 20px}.card{background:#171a21;border:1px solid #2b2f3a;border-radius:22px;padding:28px}h1{margin:0 0 10px;font-size:32px}p{color:#c7cbda;line-height:1.55}label{display:block;margin:22px 0 8px;font-weight:700}input{width:100%;box-sizing:border-box;padding:14px 16px;border-radius:14px;border:1px solid #3a3f4c;background:#0f1115;color:white;font-size:16px}button{margin-top:20px;width:100%;padding:15px;border:0;border-radius:14px;background:#f4f4f5;color:#111827;font-weight:800;font-size:16px;cursor:pointer}.msg{padding:12px 14px;border-radius:14px;margin:16px 0;background:#312320;color:#ffd7c2;border:1px solid #744534}.ok{background:#172b1c;color:#c9f7d2;border-color:#2f6840}code{background:#0f1115;border:1px solid #2b2f3a;border-radius:8px;padding:2px 6px}a{color:#dbeafe}.note{font-size:14px}</style></head>
<body><main><div class="card"><h1>Baixar stories do Instagram</h1><p>Digite o @ de um perfil para baixar os stories disponíveis em ZIP. Use apenas com conteúdo público, próprio ou autorizado.</p>
{% with messages=get_flashed_messages(with_categories=true) %}{% for c,m in messages %}<div class="msg {{'ok' if c=='ok' else ''}}">{{m}}</div>{% endfor %}{% endwith %}
<form method="post" action="{{url_for('download')}}"><label>Usuário do Instagram</label><input name="username" placeholder="exemplo: instagram" required><button>Baixar stories em ZIP</button></form>
<form method="post" action="{{url_for('test_login')}}"><button>Testar login configurado</button></form>
<p class="note">Debug: <a href="{{url_for('debug_env')}}">/debug-env</a>. Após mudar variáveis na Railway, faça Redeploy.</p></div></main></body></html>
"""

def clean(name, default=""):
    v = os.getenv(name, default)
    return default if v is None else v.strip().strip('"').strip("'")

def auth_required(fn):
    u, p = os.getenv("APP_USERNAME"), os.getenv("APP_PASSWORD")
    if not u or not p:
        return fn
    @wraps(fn)
    def w(*a, **kw):
        auth = request.authorization
        if not auth or auth.username != u or auth.password != p:
            return Response("Autenticação necessária", 401, {"WWW-Authenticate": 'Basic realm="Insta Downloader"'})
        return fn(*a, **kw)
    return w

def normalize_user(v):
    v = (v or "").strip().strip('"').strip("'").removeprefix("@").strip("/")
    if "instagram.com/" in v:
        v = v.split("instagram.com/", 1)[1].split("/", 1)[0]
    if not USERNAME_RE.fullmatch(v):
        raise ValueError("Usuário inválido. Use apenas o @ ou a URL do perfil.")
    return v

def make_loader(root: Path):
    L = instaloader.Instaloader(dirname_pattern=str(root / "{target}"), filename_pattern="{date_utc}_UTC_{mediaid}", download_pictures=True, download_videos=True, download_video_thumbnails=False, download_geotags=False, download_comments=False, save_metadata=False, compress_json=False, quiet=True, request_timeout=120, max_connection_attempts=2, sanitize_paths=True)
    ig_user = clean("IG_USERNAME").removeprefix("@").strip()
    ig_pass = clean("IG_PASSWORD")
    if not ig_user:
        raise LoginRequiredException("IG_USERNAME não está chegando no app. Confira as variáveis no serviço correto da Railway e faça Redeploy.")
    session_path = SESSION_DIR / f"session-{ig_user}"
    if clean("IG_SESSION_B64") and not session_path.exists():
        session_path.write_bytes(base64.b64decode(clean("IG_SESSION_B64")))
    if session_path.exists():
        try:
            L.load_session_from_file(ig_user, str(session_path))
            if L.test_login():
                return L
            session_path.unlink(missing_ok=True)
        except Exception:
            session_path.unlink(missing_ok=True)
    if clean("IG_COOKIES_JSON"):
        cookies = json.loads(clean("IG_COOKIES_JSON"))
        if not cookies.get("sessionid") or not cookies.get("csrftoken"):
            raise LoginRequiredException('IG_COOKIES_JSON precisa conter pelo menos "sessionid" e "csrftoken".')
        L.load_session(ig_user, cookies)
        if not L.test_login():
            raise LoginRequiredException("Cookies carregados, mas o Instagram não confirmou login. Copie cookies novos do navegador.")
        return L
    if not ig_pass:
        raise LoginRequiredException("Configure IG_PASSWORD, IG_SESSION_B64 ou IG_COOKIES_JSON na Railway.")
    L.login(ig_user, ig_pass)
    logged = L.test_login()
    if not logged:
        raise LoginRequiredException("Senha carregada, mas o Instagram não confirmou login. Use IG_SESSION_B64 ou IG_COOKIES_JSON.")
    L.save_session_to_file(str(session_path))
    return L

def zip_dir(root):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in root.rglob("*"):
            if f.is_file():
                z.write(f, f.relative_to(root))
    buf.seek(0)
    return buf

@app.get("/")
@auth_required
def index():
    return render_template_string(HTML)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/debug-env")
@auth_required
def debug_env():
    return {"IG_USERNAME_configurado": bool(os.getenv("IG_USERNAME")), "IG_USERNAME_normalizado": (clean("IG_USERNAME").removeprefix("@").strip()[:2] + "***") if os.getenv("IG_USERNAME") else None, "IG_PASSWORD_configurado": bool(os.getenv("IG_PASSWORD")), "IG_PASSWORD_tamanho": len(clean("IG_PASSWORD")) if os.getenv("IG_PASSWORD") else 0, "IG_SESSION_B64_configurado": bool(os.getenv("IG_SESSION_B64")), "IG_COOKIES_JSON_configurado": bool(os.getenv("IG_COOKIES_JSON")), "DATA_DIR": str(DATA_DIR), "SESSION_DIR_existe": SESSION_DIR.exists(), "ultimo_teste_login": LAST_LOGIN_STATUS}

@app.post("/test-login")
@auth_required
def test_login():
    root = Path(tempfile.mkdtemp(prefix="test_login_"))
    try:
        with LOCK:
            L = make_loader(root)
            user = L.test_login()
        LAST_LOGIN_STATUS.update({"ok": True, "message": f"Login confirmado como @{user}."})
        flash(f"Login confirmado como @{user}.", "ok")
    except Exception as e:
        LAST_LOGIN_STATUS.update({"ok": False, "message": f"{type(e).__name__}: {e}"})
        flash(f"Falha no teste de login: {type(e).__name__}: {e}", "error")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return redirect(url_for("index"))

@app.post("/download")
@auth_required
def download():
    try:
        target = normalize_user(request.form.get("username", ""))
        root = Path(tempfile.mkdtemp(prefix="stories_"))
        with LOCK:
            L = make_loader(root)
            profile = Profile.from_username(L.context, target)
            count = 0
            for story in L.get_stories(userids=[profile.userid]):
                for item in story.get_items():
                    if L.download_storyitem(item, target=target):
                        count += 1
        if count == 0:
            flash("Nenhum story disponível foi encontrado para esse perfil pela conta logada.", "error")
            return redirect(url_for("index"))
        return send_file(zip_dir(root), mimetype="application/zip", as_attachment=True, download_name=f"{target}_stories.zip", max_age=0)
    except ValueError as e:
        flash(str(e), "error")
    except ProfileNotExistsException:
        flash("Perfil não encontrado.", "error")
    except TwoFactorAuthRequiredException:
        flash("Essa conta tem 2FA. Use IG_SESSION_B64 ou IG_COOKIES_JSON.", "error")
    except BadCredentialsException:
        flash("Falha no login: usuário ou senha recusados. Confira as variáveis e faça Redeploy.", "error")
    except (LoginException, LoginRequiredException, ConnectionException, InstaloaderException) as e:
        flash(f"Erro: {type(e).__name__}: {e}", "error")
    finally:
        if 'root' in locals():
            shutil.rmtree(root, ignore_errors=True)
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
