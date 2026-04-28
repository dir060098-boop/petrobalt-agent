"""
Supabase Storage service.

Supports:
  - Regular upload  (files ≤ 6 MB)
  - Resumable/TUS   (files > 6 MB) — via direct HTTP to Supabase TUS endpoint

All methods return a public URL string or raise StorageError.
"""
from __future__ import annotations

import logging
import mimetypes
import uuid
from pathlib import PurePosixPath

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_TUS_CHUNK = 5 * 1024 * 1024   # 5 MB per TUS chunk
_LARGE_FILE_THRESHOLD = 6 * 1024 * 1024  # 6 MB


class StorageError(Exception):
    pass


def _make_path(prefix: str, original_filename: str) -> str:
    """Generate a unique storage path: prefix/uuid_filename."""
    suffix = PurePosixPath(original_filename).suffix or ""
    return f"{prefix}/{uuid.uuid4().hex}{suffix}"


class StorageService:
    """
    Thin wrapper around Supabase Storage REST API.
    Gracefully degrades when Supabase is not configured (returns None).
    """

    def __init__(self) -> None:
        self._settings = get_settings()

    @property
    def _configured(self) -> bool:
        return self._settings.supabase_configured

    @property
    def _base_url(self) -> str:
        return f"{self._settings.supabase_url}/storage/v1"

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._settings.supabase_service_key}",
            "apikey": self._settings.supabase_service_key,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    async def upload_mk_pdf(
        self, data: bytes, original_filename: str
    ) -> str | None:
        """Upload МК PDF to mk-files bucket. Returns public URL or None."""
        return await self._upload(
            bucket=self._settings.storage_bucket_mk,
            data=data,
            path=_make_path("mk", original_filename),
            content_type="application/pdf",
        )

    async def upload_drawing(
        self, data: bytes, original_filename: str
    ) -> str | None:
        """Upload чертёж (PDF/DWG) to drawings bucket."""
        content_type = mimetypes.guess_type(original_filename)[0] or "application/octet-stream"
        return await self._upload(
            bucket=self._settings.storage_bucket_drawings,
            data=data,
            path=_make_path("drawings", original_filename),
            content_type=content_type,
        )

    async def upload_quote(
        self, data: bytes, original_filename: str
    ) -> str | None:
        """Upload КП attachment to quote-attachments bucket."""
        content_type = mimetypes.guess_type(original_filename)[0] or "application/octet-stream"
        return await self._upload(
            bucket=self._settings.storage_bucket_quotes,
            data=data,
            path=_make_path("quotes", original_filename),
            content_type=content_type,
        )

    def public_url(self, bucket: str, path: str) -> str:
        """Construct a public URL for a stored object."""
        return f"{self._base_url}/object/public/{bucket}/{path}"

    # ─────────────────────────────────────────────────────────────────────────
    # Internal upload dispatcher
    # ─────────────────────────────────────────────────────────────────────────

    async def _upload(
        self,
        bucket: str,
        data: bytes,
        path: str,
        content_type: str,
    ) -> str | None:
        if not self._configured:
            logger.warning("Supabase не настроен — файл не загружен.")
            return None

        try:
            if len(data) > _LARGE_FILE_THRESHOLD:
                url = await self._tus_upload(bucket, data, path, content_type)
            else:
                url = await self._simple_upload(bucket, data, path, content_type)
            logger.info("Файл загружен: %s/%s", bucket, path)
            return url
        except Exception as exc:
            logger.error("Ошибка загрузки файла в Storage: %s", exc)
            raise StorageError(str(exc)) from exc

    # ─────────────────────────────────────────────────────────────────────────
    # Simple upload (≤ 6 MB)
    # ─────────────────────────────────────────────────────────────────────────

    async def _simple_upload(
        self,
        bucket: str,
        data: bytes,
        path: str,
        content_type: str,
    ) -> str:
        url = f"{self._base_url}/object/{bucket}/{path}"
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                url,
                content=data,
                headers={
                    **self._headers,
                    "Content-Type": content_type,
                    "x-upsert": "true",
                },
            )
            resp.raise_for_status()
        return self.public_url(bucket, path)

    # ─────────────────────────────────────────────────────────────────────────
    # Resumable / TUS upload (> 6 MB)
    # ─────────────────────────────────────────────────────────────────────────

    async def _tus_upload(
        self,
        bucket: str,
        data: bytes,
        path: str,
        content_type: str,
    ) -> str:
        """
        Implements TUS v1 resumable upload protocol per Supabase docs.
        Steps:
          1. POST /upload/resumable  → get Location header (upload URL)
          2. PATCH chunks until complete
        """
        import base64

        total_size = len(data)
        # Metadata must be base64-encoded key-value pairs
        meta_bucket = base64.b64encode(bucket.encode()).decode()
        meta_path = base64.b64encode(path.encode()).decode()
        meta_content_type = base64.b64encode(content_type.encode()).decode()

        upload_metadata = (
            f"bucketName {meta_bucket},"
            f"objectName {meta_path},"
            f"contentType {meta_content_type},"
            f"cacheControl {base64.b64encode(b'3600').decode()}"
        )

        tus_base = f"{self._settings.supabase_url}/storage/v1/upload/resumable"

        async with httpx.AsyncClient(timeout=120) as client:
            # Step 1 — create upload
            resp = await client.post(
                tus_base,
                headers={
                    **self._headers,
                    "Upload-Length": str(total_size),
                    "Upload-Metadata": upload_metadata,
                    "Tus-Resumable": "1.0.0",
                    "Content-Type": "application/offset+octet-stream",
                    "x-upsert": "true",
                },
            )
            resp.raise_for_status()
            upload_url = resp.headers.get("Location")
            if not upload_url:
                raise StorageError("TUS: нет заголовка Location в ответе на создание")

            # Step 2 — upload chunks
            offset = 0
            while offset < total_size:
                chunk = data[offset: offset + _TUS_CHUNK]
                patch_resp = await client.patch(
                    upload_url,
                    content=chunk,
                    headers={
                        **self._headers,
                        "Content-Type": "application/offset+octet-stream",
                        "Upload-Offset": str(offset),
                        "Tus-Resumable": "1.0.0",
                    },
                )
                patch_resp.raise_for_status()
                offset += len(chunk)
                logger.debug("TUS прогресс: %d / %d байт", offset, total_size)

        return self.public_url(bucket, path)
