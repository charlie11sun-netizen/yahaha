"""S3 兼容对象存储封装（boto3）。

所有读写走 S3 SDK，换真 S3 / 阿里云 OSS 仅改 endpoint 与凭证。
"""
from functools import lru_cache

from botocore.client import Config
import boto3

from app.core.config import settings


# boto3 client 构造不便宜且线程安全，进程内复用（此前每次 put/get/签名都新建）
@lru_cache(maxsize=1)
def client():
    return boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        region_name=settings.S3_REGION,
        config=Config(signature_version="s3v4"),
    )


@lru_cache(maxsize=1)
def public_client():
    """Signing-only client whose endpoint is reachable by the browser."""
    return boto3.client(
        "s3",
        endpoint_url=settings.S3_PUBLIC_ENDPOINT,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        region_name=settings.S3_REGION,
        config=Config(signature_version="s3v4"),
    )


def ensure_bucket() -> None:
    c = client()
    try:
        c.head_bucket(Bucket=settings.S3_BUCKET)
    except Exception:
        try:
            c.create_bucket(Bucket=settings.S3_BUCKET)
        except Exception:
            pass


def put_object(key: str, body: bytes | str, content_type: str) -> str:
    if isinstance(body, str):
        body = body.encode("utf-8")
    client().put_object(Bucket=settings.S3_BUCKET, Key=key, Body=body, ContentType=content_type)
    return key


def get_object(key: str) -> bytes | None:
    try:
        return client().get_object(Bucket=settings.S3_BUCKET, Key=key)["Body"].read()
    except Exception:  # noqa: BLE001
        return None


def delete_prefix(prefix: str) -> int:
    """删除某前缀下的全部对象（清理退役游戏的远端产物）。返回删除数量。"""
    c = client()
    deleted = 0
    try:
        token = None
        while True:
            kwargs = {"Bucket": settings.S3_BUCKET, "Prefix": prefix}
            if token:
                kwargs["ContinuationToken"] = token
            resp = c.list_objects_v2(**kwargs)
            objs = [{"Key": o["Key"]} for o in resp.get("Contents", [])]
            if objs:
                c.delete_objects(Bucket=settings.S3_BUCKET, Delete={"Objects": objs})
                deleted += len(objs)
            if resp.get("IsTruncated"):
                token = resp.get("NextContinuationToken")
            else:
                break
    except Exception:  # noqa: BLE001
        pass
    return deleted


def public_url(key: str) -> str:
    """Backward-compatible browser URL for private objects."""
    return presigned_url(key)


def presigned_url(
    key: str,
    expires_seconds: int = 3600,
    *,
    response_content_disposition: str | None = None,
) -> str:
    """Short-lived browser URL for private uploads and other non-public objects."""
    params = {"Bucket": settings.S3_BUCKET, "Key": key}
    if response_content_disposition:
        params["ResponseContentDisposition"] = response_content_disposition
    return public_client().generate_presigned_url(
        "get_object",
        Params=params,
        ExpiresIn=expires_seconds,
    )


def game_prefix(game_id: str, version: str) -> str:
    return f"games/{game_id}/{version}"


def manifest_url(game_id: str, version: str) -> str:
    from app.services.runtime_urls import game_manifest_url

    return game_manifest_url(game_id, version)
