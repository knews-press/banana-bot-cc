"""Download files from Telegram and save to local storage."""

import os
import uuid
from pathlib import Path

import aiofiles
import structlog
from telegram import Bot, File

logger = structlog.get_logger()


async def download_telegram_file(
    bot: Bot,
    file_id: str,
    uploads_dir: str,
    filename: str | None = None,
    extension: str | None = None,
) -> tuple[str, str, int]:
    """Download a Telegram file to disk.

    Returns:
        (upload_id, local_path, file_size)
    """
    upload_id = str(uuid.uuid4())

    # Determine filename
    if filename:
        safe_name = "".join(c for c in filename if c.isalnum() or c in "._- ")
        local_name = f"{upload_id}_{safe_name}"
    elif extension:
        local_name = f"{upload_id}{extension}"
    else:
        local_name = upload_id

    Path(uploads_dir).mkdir(parents=True, exist_ok=True)
    local_path = os.path.join(uploads_dir, local_name)

    tg_file: File = await bot.get_file(file_id)
    await tg_file.download_to_drive(local_path)

    file_size = os.path.getsize(local_path)
    logger.info("Downloaded Telegram file", upload_id=upload_id, path=local_path, size=file_size)
    return upload_id, local_path, file_size


async def read_file_bytes(path: str) -> bytes:
    async with aiofiles.open(path, "rb") as f:
        return await f.read()
