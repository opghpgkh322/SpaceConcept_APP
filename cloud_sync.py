# cloud_sync.py
import os, requests

API_URL = "https://cloud-api.yandex.net/v1/disk"
def _auth(token): return {"Authorization": f"OAuth {token}"}

def get_download_href(token, path):
    resp = requests.get(f"{API_URL}/resources/download", params={"path": path}, headers=_auth(token), timeout=30)
    resp.raise_for_status()
    return resp.json()["href"]

def get_upload_href(token, path, overwrite=True):
    resp = requests.get(f"{API_URL}/resources/upload", params={"path": path, "overwrite": str(overwrite).lower()},
                        headers=_auth(token), timeout=30)
    resp.raise_for_status()
    return resp.json()["href"]

def download_db(token, remote_path, local_path):
    href = get_download_href(token, remote_path)
    with requests.get(href, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "wb") as f:
            for chunk in resp.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)

def upload_db(token, remote_path, local_path):
    href = get_upload_href(token, remote_path, overwrite=True)
    with open(local_path, "rb") as f:
        resp = requests.put(href, data=f, timeout=120)
        resp.raise_for_status()
