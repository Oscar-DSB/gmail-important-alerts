"""Script local para generar el token OAuth 2.0 de Gmail.

Uso:
    python scripts/setup_gmail_oauth.py

Requiere `credentials.json` (descargado de Google Cloud Console, tipo
"Desktop app") en el directorio raíz del proyecto. Abre el navegador para
autorizar el acceso y guarda las credenciales en `gmail_token.json`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: E402

import config  # noqa: E402

CREDENTIALS_PATH = Path(__file__).resolve().parent.parent / "credentials.json"
TOKEN_PATH = Path(__file__).resolve().parent.parent / "gmail_token.json"


def main() -> None:
    if not CREDENTIALS_PATH.exists():
        print(f"No se encontró {CREDENTIALS_PATH}.")
        print("Descarga las credenciales OAuth (tipo 'Desktop app') desde")
        print("Google Cloud Console > APIs y servicios > Credenciales,")
        print(f"y guárdalas como {CREDENTIALS_PATH}.")
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), config.GMAIL_SCOPES)
    credentials = flow.run_local_server(port=0)

    if not credentials.refresh_token:
        print("ADVERTENCIA: no se obtuvo refresh_token.")
        print("Revoca el acceso previo en https://myaccount.google.com/permissions")
        print("y vuelve a ejecutar este script para forzar el consentimiento.")

    token_data = json.loads(credentials.to_json())
    TOKEN_PATH.write_text(json.dumps(token_data, indent=2), encoding="utf-8")

    print(f"Credenciales guardadas temporalmente en {TOKEN_PATH}")
    print()
    print("Siguiente paso: sube el contenido de este archivo como GitHub Secret.")
    print("Puedes usar scripts/setup_github_secrets.sh, o manualmente:")
    print()
    print(f"  gh secret set GMAIL_OAUTH_TOKEN_JSON < {TOKEN_PATH.name}")
    print()
    print("Después, elimina el archivo local por seguridad:")
    print(f"  rm {TOKEN_PATH.name}")


if __name__ == "__main__":
    main()
