"""One storage adapter for all brand assets; database stores references only."""
from __future__ import annotations

import io
import os
import warnings
from pathlib import Path

import boto3
from botocore.config import Config
from PIL import Image, UnidentifiedImageError

from .database import DATA_DIR

Image.MAX_IMAGE_PIXELS = 16_000_000


def validate_image(content: bytes, mime: str, asset_type: str) -> tuple[bytes, int, int, str]:
    maximum = 5 * 1024 * 1024 if asset_type == "LOGIN_BACKGROUND" else 2 * 1024 * 1024
    if not content or len(content) > maximum:
        raise ValueError(f"Image must be non-empty and no larger than {maximum // 1024 // 1024} MB")
    formats = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}
    if mime not in formats:
        raise ValueError("Upload PNG, JPG or WEBP. SVG and executable content are not accepted.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as probe:
                if probe.format != formats[mime] or getattr(probe, "n_frames", 1) != 1:
                    raise ValueError("Image content does not match its type, or is animated")
                width, height = probe.size
                if min(width, height) < 16 or max(width, height) > 4096:
                    raise ValueError("Image dimensions must be between 16 and 4096 pixels")
                if asset_type == "FAVICON" and width != height:
                    raise ValueError("Favicon must be a square image")
                probe.verify()
            with Image.open(io.BytesIO(content)) as original:
                image = original.convert("RGBA")
                image.thumbnail((1920, 1080) if asset_type == "LOGIN_BACKGROUND" else (1024, 1024))
                output = io.BytesIO()
                # Re-encode to strip metadata, trailing content and polyglot payloads.
                # PNG logos/favicons remain compatible with email clients and
                # browser icons; larger login backgrounds use optimized WEBP.
                if asset_type == "LOGIN_BACKGROUND":
                    image.save(output, format="WEBP", quality=88, method=4)
                    mime_type = "image/webp"
                else:
                    image.save(output, format="PNG", optimize=True)
                    mime_type = "image/png"
                return output.getvalue(), image.width, image.height, mime_type
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValueError("Image is corrupted or unsafe") from error


class BrandStorage:
    def __init__(self):
        self.bucket = os.getenv("BRAND_S3_BUCKET", "")
        self.directory = Path(os.getenv("BRAND_ASSET_DIR", str(DATA_DIR / "brand-assets"))).resolve()
        self.client = None
        if self.bucket:
            self.client = boto3.client("s3", endpoint_url=os.getenv("BRAND_S3_ENDPOINT") or None,
                                       region_name=os.getenv("AWS_REGION", "ap-south-1"),
                                       config=Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 2}))
        elif os.getenv("APP_ENV") == "production":
            raise RuntimeError("Production white-label assets require BRAND_S3_BUCKET and object storage credentials")

    def path(self, key: str) -> Path:
        target = (self.directory / key).resolve()
        if not target.is_relative_to(self.directory):
            raise ValueError("Invalid storage reference")
        return target

    def put(self, key: str, content: bytes, mime_type: str):
        if self.client:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=content, ContentType=mime_type,
                                   ServerSideEncryption="AES256")
        else:
            target = self.path(key)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as destination:
                destination.write(content)

    def get(self, key: str) -> bytes:
        if self.client:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            try:
                return response["Body"].read(6 * 1024 * 1024)
            finally:
                response["Body"].close()
        return self.path(key).read_bytes()
