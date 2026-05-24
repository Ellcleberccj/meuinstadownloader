# Instagram Stories Downloader para Railway

App Flask pronto para deploy na Railway usando o pacote `instaloader` incluído no projeto.

Use apenas para baixar stories públicos, seus próprios stories, ou conteúdo de contas para as quais você tem autorização. O app não burla perfil privado, bloqueio, login, 2FA ou limitações do Instagram.

## Deploy na Railway

1. Suba esta pasta para um repositório GitHub.
2. Na Railway, crie um novo projeto a partir desse repositório.
3. A Railway vai detectar o `Dockerfile` e subir o app automaticamente.
4. Configure as variáveis em **Variables**:

```env
IG_USERNAME=seu_usuario_instagram
IG_PASSWORD=sua_senha_instagram
FLASK_SECRET_KEY=coloque_uma_string_grande_aleatoria
APP_USERNAME=admin_opcional
APP_PASSWORD=senha_do_painel_opcional
```

`APP_USERNAME` e `APP_PASSWORD` protegem a tela do app com senha. Recomendo usar em produção.

## Sessão persistente

A Railway pode reiniciar o container. O app tenta salvar sessão em `/data/sessions`. Para maior estabilidade, adicione um Volume na Railway montado em `/data`.

Alternativa: gerar uma sessão local e colar em `IG_SESSION_B64`.

```bash
pip install -r requirements.txt
python scripts/export_session_base64.py
```

Depois, na Railway, configure:

```env
IG_USERNAME=seu_usuario_instagram
IG_SESSION_B64=valor_gerado_pelo_script
```

## Rodar localmente

```bash
pip install -r requirements.txt
export IG_USERNAME=seu_usuario_instagram
export IG_PASSWORD=sua_senha_instagram
python app.py
```

Abra `http://localhost:8080`.

## Observações importantes

- Stories exigem login no Instagram pelo próprio funcionamento do Instaloader.
- Contas com 2FA podem exigir sessão gerada localmente.
- Evite uso agressivo para não tomar rate limit.
- O arquivo baixado vem em ZIP com fotos e vídeos dos stories disponíveis no momento.
