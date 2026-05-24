import base64
import io
import json
import os
import re
import shutil
import tempfile
import threading
import zipfile
import uuid
import yt_dlp
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, Response, flash, redirect, render_template_string, request, send_file, url_for
import instaloader
from instaloader import Profile, Post
from instaloader.exceptions import BadCredentialsException, ConnectionException, InstaloaderException, LoginException, LoginRequiredException, ProfileNotExistsException, TwoFactorAuthRequiredException

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-me")
DATA_DIR = Path(os.getenv("DATA_DIR", "/data" if Path("/data").exists() else "./data"))
SESSION_DIR = DATA_DIR / "sessions"
YOUTUBE_DIR = DATA_DIR / "youtube_mp3"
YOUTUBE_DIR.mkdir(parents=True, exist_ok=True)
SESSION_DIR.mkdir(parents=True, exist_ok=True)
LOCK = threading.Lock()
USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")
LAST_LOGIN_STATUS = {"ok": None, "message": "Ainda não foi feito teste de login."}

CSS = """
<style>:root{color-scheme:dark}body{margin:0;font-family:Inter,system-ui,Arial;background:#0f1115;color:#f4f4f5}main{max-width:1050px;margin:auto;padding:42px 20px}.card{background:#171a21;border:1px solid #2b2f3a;border-radius:22px;padding:28px}h1{margin:0 0 10px;font-size:32px}p{color:#c7cbda;line-height:1.55}label{display:block;margin:22px 0 8px;font-weight:700}input{width:100%;box-sizing:border-box;padding:14px 16px;border-radius:14px;border:1px solid #3a3f4c;background:#0f1115;color:white;font-size:16px}button,.btn{display:inline-block;text-align:center;text-decoration:none;margin-top:14px;padding:13px 16px;border:0;border-radius:14px;background:#f4f4f5;color:#111827;font-weight:800;font-size:15px;cursor:pointer}.btn2{background:#252a35;color:#f4f4f5;border:1px solid #3a3f4c}.msg{padding:12px 14px;border-radius:14px;margin:16px 0;background:#312320;color:#ffd7c2;border:1px solid #744534}.ok{background:#172b1c;color:#c9f7d2;border-color:#2f6840}code{background:#0f1115;border:1px solid #2b2f3a;border-radius:8px;padding:2px 6px}a{color:#dbeafe}.note{font-size:14px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:18px;margin-top:22px}.story{background:#101319;border:1px solid #2b2f3a;border-radius:18px;padding:12px}.story img,.story video{width:100%;border-radius:14px;background:#050507;max-height:420px;object-fit:contain}.actions{display:flex;gap:10px;flex-wrap:wrap}.actions .btn,.actions button{flex:1}.small{font-size:13px;color:#9ca3af}.loading{display:none;margin:16px 0;padding:14px;border-radius:14px;background:#101319;border:1px solid #3a3f4c;color:#dbeafe}.spin{display:inline-block;width:15px;height:15px;border:2px solid #596273;border-top-color:white;border-radius:50%;animation:s .8s linear infinite;margin-right:8px;vertical-align:-2px}@keyframes s{to{transform:rotate(360deg)}}button[disabled]{opacity:.65;cursor:wait}</style><script>document.addEventListener('DOMContentLoaded',()=>{document.querySelectorAll('form').forEach(f=>f.addEventListener('submit',()=>{let b=f.querySelector('button');let l=document.getElementById('loadingBox');if(b){b.disabled=true;b.innerHTML='<span class="spin"></span>Processando...'}if(l){l.style.display='block';l.innerHTML='<span class="spin"></span>Preparando. Aguarde, o download ou preview vai abrir automaticamente.'}}))})</script>
"""

HTML = """
<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Insta Downloader</title>""" + CSS + """</head>
<body><main><div class="card"><h1>Insta Downloader</h1><p>Baixe stories, posts e reels disponíveis para a conta logada.</p>
{% with messages=get_flashed_messages(with_categories=true) %}{% for c,m in messages %}<div class="msg {{'ok' if c=='ok' else ''}}">{{m}}</div>{% endfor %}{% endwith %}<div id="loadingBox" class="loading"></div>
<form method="get" action="{{url_for('preview')}}"><label>Usuário do Instagram para stories</label><input name="username" placeholder="exemplo: instagram" required><button>Ver preview dos stories</button></form>
<form method="post" action="{{url_for('download')}}"><label>Baixar todos os stories em ZIP</label><input name="username" placeholder="exemplo: instagram" required><button>Baixar todos os stories em ZIP</button></form>
<form method="get" action="{{url_for('download_from_link')}}"><label>Link de um story específico</label><input name="url" placeholder="https://www.instagram.com/stories/usuario/123456789/"><button>Baixar story pelo link</button></form>
<form method="get" action="{{url_for('download_post_link')}}"><label>Link de post/reels</label><input name="url" placeholder="https://www.instagram.com/reel/CODIGO/ ou https://www.instagram.com/p/CODIGO/" required><button>Baixar post/reels</button></form>
<form method="get" action="{{url_for('download_youtube_mp3')}}">
  <label>Link do YouTube para MP3</label>
  <input name="url" placeholder="https://www.youtube.com/watch?v=CODIGO" required>
  <button>Converter YouTube para MP3</button>
</form>
<form method="post" action="{{url_for('test_login')}}"><button class="btn2">Testar login configurado</button></form>
<p class="note">Debug: <a href="{{url_for('debug_env')}}">/debug-env</a>. Após mudar variáveis na Railway, faça Redeploy.</p></div></main></body></html>
"""

PREVIEW_HTML = """
<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Preview stories</title>""" + CSS + """</head>
<body><main><div class="card"><h1>Stories de @{{username}}</h1><p>Escolha um story para baixar individualmente ou baixe todos em ZIP.</p><div id="loadingBox" class="loading"></div><div class="actions"><a class="btn btn2" href="{{url_for('index')}}">Voltar</a><form method="post" action="{{url_for('download')}}" style="flex:1"><input type="hidden" name="username" value="{{username}}"><button>Baixar todos em ZIP</button></form></div>
{% if not items %}<div class="msg">Nenhum story disponível encontrado.</div>{% endif %}<div class="grid">{% for s in items %}<div class="story">{% if s.is_video %}<video controls preload="metadata" src="{{s.preview_url}}"></video>{% else %}<img src="{{s.preview_url}}" alt="story {{loop.index}}">{% endif %}<p class="small">{{loop.index}} · {{s.kind}} · ID {{s.mediaid}}</p><div class="actions"><a class="btn" href="{{url_for('download_one', username=username, mediaid=s.mediaid)}}">Baixar este</a><a class="btn btn2" target="_blank" href="{{s.preview_url}}">Abrir mídia</a></div></div>{% endfor %}</div></div></main></body></html>
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

def parse_story_link(link):
    parsed = urlparse((link or "").strip())
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 3 and parts[0] == "stories":
        return normalize_user(parts[1]), parts[2]
    raise ValueError("Link inválido. Use um link no formato https://www.instagram.com/stories/usuario/id/")

def parse_post_shortcode(link):
    parsed = urlparse((link or "").strip())
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2 and parts[0] in {"p", "reel", "tv"}:
        return parts[1]
    raise ValueError("Link inválido. Use um link de post, reels ou IGTV do Instagram.")

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

def iter_story_items(L, username):
    profile = Profile.from_username(L.context, username)
    for story in L.get_stories(userids=[profile.userid]):
        for item in story.get_items():
            yield item

def story_media_id(item):
    return str(getattr(item, "mediaid", "") or getattr(item, "media_id", "") or getattr(item, "shortcode", ""))

def item_preview_url(item):
    return item.video_url if getattr(item, "is_video", False) else item.url

def media_files(root):
    return [f for f in root.rglob("*") if f.is_file() and f.suffix.lower() in [".jpg", ".jpeg", ".png", ".mp4"]]

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

@app.get("/preview")
@auth_required
def preview():
    root = Path(tempfile.mkdtemp(prefix="preview_"))
    try:
        username = normalize_user(request.args.get("username", ""))
        with LOCK:
            L = make_loader(root)
            items = []
            for item in iter_story_items(L, username):
                mid = story_media_id(item)
                if mid:
                    items.append({"mediaid": mid, "is_video": bool(getattr(item, "is_video", False)), "kind": "vídeo" if getattr(item, "is_video", False) else "foto", "preview_url": item_preview_url(item)})
        return render_template_string(PREVIEW_HTML, username=username, items=items)
    except Exception as e:
        flash(f"Erro ao gerar preview: {type(e).__name__}: {e}", "error")
        return redirect(url_for("index"))
    finally:
        shutil.rmtree(root, ignore_errors=True)

@app.get("/download-one/<username>/<mediaid>")
@auth_required
def download_one(username, mediaid):
    root = Path(tempfile.mkdtemp(prefix="story_one_"))
    try:
        username = normalize_user(username)
        with LOCK:
            L = make_loader(root)
            found = None
            for item in iter_story_items(L, username):
                if story_media_id(item) == str(mediaid):
                    found = item
                    break
            if not found:
                flash("Story não encontrado. Ele pode ter expirado ou não estar mais disponível.", "error")
                return redirect(url_for("preview", username=username))
            L.download_storyitem(found, target=username)
        files = media_files(root)
        if not files:
            flash("Não consegui encontrar o arquivo baixado.", "error")
            return redirect(url_for("preview", username=username))
        return send_file(files[0], as_attachment=True, download_name=files[0].name, max_age=0)
    except Exception as e:
        flash(f"Erro ao baixar story: {type(e).__name__}: {e}", "error")
        return redirect(url_for("index"))

@app.get("/download-link")
@auth_required
def download_from_link():
    try:
        username, mediaid = parse_story_link(request.args.get("url", ""))
        return redirect(url_for("download_one", username=username, mediaid=mediaid))
    except Exception as e:
        flash(str(e), "error")
        return redirect(url_for("index"))

@app.get("/download-post")
@auth_required
def download_post_link():
    root = Path(tempfile.mkdtemp(prefix="post_"))
    try:
        shortcode = parse_post_shortcode(request.args.get("url", ""))
        with LOCK:
            L = make_loader(root)
            post = Post.from_shortcode(L.context, shortcode)
            L.download_post(post, target=f"post_{shortcode}")
        files = media_files(root)
        if not files:
            flash("Não consegui encontrar mídia nesse post/reels.", "error")
            return redirect(url_for("index"))
        if len(files) == 1:
            return send_file(files[0], as_attachment=True, download_name=files[0].name, max_age=0)
        return send_file(zip_dir(root), mimetype="application/zip", as_attachment=True, download_name=f"post_{shortcode}.zip", max_age=0)
    except Exception as e:
        flash(f"Erro ao baixar post/reels: {type(e).__name__}: {e}", "error")
        return redirect(url_for("index"))
    finally:
        shutil.rmtree(root, ignore_errors=True)

def is_youtube_url(url):
    parsed = urlparse((url or "").strip())
    host = parsed.netloc.lower()
    return parsed.scheme in ("http", "https") and ("youtube.com" in host or "youtu.be" in host)


@app.get("/download-youtube")
@auth_required
def download_youtube_mp3():
    url = (request.args.get("url") or "").strip()

    if not is_youtube_url(url):
        flash("Envie um link válido do YouTube.", "error")
        return redirect(url_for("index"))

    try:
        job_id = uuid.uuid4().hex[:16]
        output_template = str(YOUTUBE_DIR / f"{job_id}.%(ext)s")

        options = {
            "format": "bestaudio/best",
            "outtmpl": output_template,
            "noplaylist": True,
            "max_filesize": 250 * 1024 * 1024,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
            "quiet": True,
            "no_warnings": True,
        }

        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])

        files = list(YOUTUBE_DIR.glob(f"{job_id}*.mp3"))

        if not files:
            flash("O MP3 não foi encontrado depois da conversão.", "error")
            return redirect(url_for("index"))

        return send_file(
            files[0],
            as_attachment=True,
            download_name=files[0].name,
            max_age=0,
        )

    except Exception as e:
        flash(f"Erro ao converter YouTube para MP3: {type(e).__name__}: {e}", "error")
        return redirect(url_for("index"))

@app.post("/download")
@auth_required
def download():
    try:
        target = normalize_user(request.form.get("username", ""))
        root = Path(tempfile.mkdtemp(prefix="stories_"))
        with LOCK:
            L = make_loader(root)
            count = 0
            for item in iter_story_items(L, target):
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
