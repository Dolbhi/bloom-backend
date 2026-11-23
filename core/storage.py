"""
Photo storage (feature F5).

The app asks the API for a short-lived upload URL, then PUTs the photo straight to storage.
The database only ever stores the `photo_key` (a path like submissions/12/2026/11/ab12cd.jpg).

Two backends, picked with the PHOTO_STORAGE env var:

- "local": dev only. The upload URL points back at this Django server
  (/api/v1/uploads/local/<signed token>), which writes the file under MEDIA_ROOT.
  Works on a phone on the same Wi-Fi with no cloud account.
- "s3": any S3-compatible bucket (Cloudflare R2, Supabase Storage S3, AWS S3) via boto3
  pre-signed PUT URLs. Note: a pre-signed PUT can't enforce the file size; the size the app
  declares is checked at presign time, and the real size is checked again by HEAD on submit.
"""
import secrets
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.core import signing
from django.urls import reverse
from django.utils import timezone

LOCAL_UPLOAD_SALT = "bloom.local-upload"


def new_photo_key(user_id, content_type):
    """Key includes the user id so we can check a key was issued to the user who submits it."""
    ext = settings.PHOTO_ALLOWED_TYPES[content_type]
    now = timezone.now()
    return f"submissions/{user_id}/{now:%Y}/{now:%m}/{secrets.token_hex(8)}.{ext}"


def key_belongs_to(key, user_id):
    return key.startswith(f"submissions/{user_id}/") and ".." not in key


def _absolute(request, path):
    return request.build_absolute_uri(path) if request is not None else path


# --- local backend ----------------------------------------------------------

class LocalStorage:
    def presign_upload(self, key, content_type, request=None):
        token = signing.dumps({"key": key, "ct": content_type}, salt=LOCAL_UPLOAD_SALT)
        return _absolute(request, reverse("local-upload", args=[token]))

    def read_upload_token(self, token):
        """Returns (key, content_type) or raises signing.BadSignature / SignatureExpired."""
        data = signing.loads(token, salt=LOCAL_UPLOAD_SALT, max_age=settings.PHOTO_UPLOAD_EXPIRES)
        return data["key"], data["ct"]

    def path_for(self, key):
        path = (Path(settings.MEDIA_ROOT) / key).resolve()
        if not str(path).startswith(str(Path(settings.MEDIA_ROOT).resolve())):
            raise ValueError("Invalid key")
        return path

    def exists(self, key):
        try:
            return self.path_for(key).is_file()
        except ValueError:
            return False

    def size(self, key):
        return self.path_for(key).stat().st_size

    def url(self, key, request=None):
        # Django may already have turned "media/" into "/media/"; a doubled "//" would read as a host name
        return _absolute(request, f"/{settings.MEDIA_URL.lstrip('/')}{key}")


# --- S3-compatible backend --------------------------------------------------

class S3Storage:
    def __init__(self):
        import boto3
        from botocore.config import Config

        self.bucket = settings.S3_BUCKET
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL or None,
            region_name=settings.S3_REGION,
            aws_access_key_id=settings.S3_ACCESS_KEY_ID,
            aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def presign_upload(self, key, content_type, request=None):
        return self.client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=settings.PHOTO_UPLOAD_EXPIRES,
            HttpMethod="PUT",
        )

    def _head(self, key):
        from botocore.exceptions import ClientError

        try:
            return self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError:
            return None

    def exists(self, key):
        return self._head(key) is not None

    def size(self, key):
        head = self._head(key)
        return head["ContentLength"] if head else 0

    def url(self, key, request=None):
        if settings.PHOTO_PUBLIC_BASE_URL:
            return f"{settings.PHOTO_PUBLIC_BASE_URL}/{key}"
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=settings.PHOTO_URL_EXPIRES
        )


@lru_cache(maxsize=1)
def get_storage():
    if settings.PHOTO_STORAGE == "s3":
        return S3Storage()
    return LocalStorage()


def photo_url(key, request=None):
    """Turns a stored photo_key into a URL the app can load. None if there is no photo."""
    if not key:
        return None
    return get_storage().url(key, request)
