# Meu Insta Downloader

App Flask pronto para Railway para baixar stories disponíveis para a conta logada.

## O que mudou

O app agora tem um botão **Testar login configurado** e a rota `/debug-env` mostra se as variáveis estão chegando na Railway sem expor sua senha.

## Variáveis na Railway

Login por senha:

```env
IG_USERNAME=seu_usuario_sem_arroba
IG_PASSWORD=sua_senha
```

Depois de alterar qualquer variável, faça **Redeploy** no serviço da Railway.

## Alternativa mais estável

Se senha normal falhar, use sessão local:

```bash
pip install -r requirements.txt
python scripts/export_session_base64.py
```

Depois coloque na Railway:

```env
IG_USERNAME=seu_usuario_sem_arroba
IG_SESSION_B64=valor_gerado_pelo_script
```

## Alternativa por cookies do navegador

Também é aceito:

```env
IG_USERNAME=seu_usuario_sem_arroba
IG_COOKIES_JSON={"sessionid":"...","csrftoken":"...","ds_user_id":"...","mid":"..."}
```

## Proteção opcional

```env
APP_USERNAME=admin
APP_PASSWORD=senha_forte
```

## Observação

O app não burla perfil privado, bloqueios, 2FA ou restrições do Instagram. Ele baixa apenas stories que a conta logada consegue visualizar.
