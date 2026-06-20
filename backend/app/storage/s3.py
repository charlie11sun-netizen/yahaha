"""S3 兼容对象存储封装（boto3）。

所有读写走 S3 SDK，换真 S3 / 阿里云 OSS 仅改 endpoint 与凭证。
"""
from botocore.client import Config
import boto3

from app.core.config import settings


def client():
    return boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT,
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
    """浏览器可直接访问的远端地址（桶 games 前缀已设匿名只读）。"""
    return f"{settings.S3_PUBLIC_ENDPOINT}/{settings.S3_BUCKET}/{key}"


def game_prefix(game_id: str, version: str) -> str:
    return f"games/{game_id}/{version}"


def manifest_url(game_id: str, version: str) -> str:
    return public_url(f"{game_prefix(game_id, version)}/manifest.json")
