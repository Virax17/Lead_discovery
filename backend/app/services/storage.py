"""
Export file storage abstraction.

When S3_BUCKET is configured, exports are uploaded to S3 and served via a
presigned URL. This is recommended for production hosts with ephemeral
filesystems, such as Render.

When S3_BUCKET is unset, exports stay on local disk exactly as before, served
via FileResponse and swept by cleanup.py.
"""

import os

from app.config.settings import settings

EXPORT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "exports")
os.makedirs(EXPORT_DIR, exist_ok=True)

PRESIGNED_URL_TTL_SECONDS = 3600


def s3_enabled() -> bool:
    return bool(settings.s3_bucket and settings.s3_region)


def _s3_client():
    import boto3

    return boto3.client("s3", region_name=settings.s3_region)


def _s3_key(filename: str) -> str:
    prefix = settings.s3_prefix.strip("/")
    return f"{prefix}/{filename}" if prefix else filename


def local_path(filename: str) -> str:
    return os.path.join(EXPORT_DIR, filename)


async def object_exists(filename: str) -> bool:
    if s3_enabled():
        client = _s3_client()
        try:
            client.head_object(Bucket=settings.s3_bucket, Key=_s3_key(filename))
            return True
        except Exception:
            return False
    return os.path.exists(local_path(filename))


async def upload_if_needed(filename: str) -> None:
    """Push a freshly generated local file up to S3 when S3 storage is active."""
    if not s3_enabled():
        return
    client = _s3_client()
    client.upload_file(local_path(filename), settings.s3_bucket, _s3_key(filename))


def presigned_url(filename: str) -> str:
    client = _s3_client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": _s3_key(filename)},
        ExpiresIn=PRESIGNED_URL_TTL_SECONDS,
    )
