"""Gera uma sessão do Instaloader em base64 para colar na variável IG_SESSION_B64 da Railway."""
import base64
import getpass
from pathlib import Path

import instaloader

username = input("Instagram username: ").strip()
password = getpass.getpass("Instagram password: ")

session_file = Path(f"session-{username}")
loader = instaloader.Instaloader(quiet=False)
loader.login(username, password)
loader.save_session_to_file(str(session_file))
print("\nCole isto em IG_SESSION_B64 na Railway:\n")
print(base64.b64encode(session_file.read_bytes()).decode())
