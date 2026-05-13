"""
Google Drive client for Jerome 1.1.
- download: service account (reads shared folders)
- upload:   OAuth 2.0 user credentials (writes to personal My Drive)
"""
from __future__ import annotations
import io
import re
from pathlib import Path

from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.file",
]

_SERVICE_ACCOUNT_FILE = Path(__file__).parent / "service_account.json"
OAUTH_CLIENT_FILE = Path(__file__).parent / "oauth_client.json"

_MIME_EXPORT = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
}

_NATIVE_EXTS = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/x-xliff+xml": ".xliff",
    "application/xliff+xml": ".xliff",
    "text/xml": ".xliff",
}


def _sa_service():
    creds = service_account.Credentials.from_service_account_file(
        str(_SERVICE_ACCOUNT_FILE), scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _oauth_service(oauth_creds: Credentials):
    return build("drive", "v3", credentials=oauth_creds, cache_discovery=False)


def get_folder_id_from_url(url: str) -> str:
    m = re.search(r"/folders/([a-zA-Z0-9_-]+)", url)
    if not m:
        raise ValueError(f"Cannot extract folder ID from URL: {url}")
    return m.group(1)


def list_folder(folder_id: str) -> list[dict]:
    svc = _sa_service()
    results = []
    page_token = None
    while True:
        resp = (
            svc.files()
            .list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="nextPageToken, files(id, name, mimeType, size)",
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        results.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return results


def download_file(file_id: str, file_name: str, mime_type: str, dest_dir: Path) -> Path:
    svc = _sa_service()
    if mime_type in _MIME_EXPORT:
        export_mime, ext = _MIME_EXPORT[mime_type]
        dest = dest_dir / f"{Path(file_name).stem}{ext}"
        request = svc.files().export_media(fileId=file_id, mimeType=export_mime)
    else:
        ext = _NATIVE_EXTS.get(mime_type, Path(file_name).suffix or ".bin")
        dest = dest_dir / f"{Path(file_name).stem}{ext}"
        request = svc.files().get_media(fileId=file_id)

    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    dest.write_bytes(buf.getvalue())
    return dest


def upload_file(folder_id: str, local_path: Path, oauth_creds: Credentials) -> str:
    svc = _oauth_service(oauth_creds)
    meta = {"name": local_path.name, "parents": [folder_id]}
    media = MediaFileUpload(str(local_path), resumable=True)
    f = (
        svc.files()
        .create(body=meta, media_body=media, fields="id", supportsAllDrives=True)
        .execute()
    )
    return f["id"]
