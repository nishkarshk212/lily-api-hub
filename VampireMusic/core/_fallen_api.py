import asyncio
import os
import re
import urllib.parse
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import aiohttp
from pyrogram import Client, errors

from VampireMusic import config, logger


@dataclass
class MusicTrack:
    cdnurl: str
    url: str
    id: str
    key: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "MusicTrack":
        return cls(
            cdnurl=data.get("cdnurl", ""),
            url=data.get("url", ""),
            id=data.get("id", ""),
            key=data.get("key"),
        )


_TG_URL_RE = re.compile(r"https?://t\.me/([^/]+)/(\d+)")
_CD_FILENAME_RE = re.compile(
    r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\r\n]+)["\']?', re.IGNORECASE
)


class FallenApi:
    def __init__(
        self,
        app: Client,
        *,
        retries: int = 3,
        timeout: int = 15,
        download_dir: Path = Path("downloads"),
    ):
        self.app = app
        self.api_url = config.API_URL.rstrip("/")
        self.api_key = config.API_KEY
        self.retries = retries
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.download_dir = download_dir
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> "FallenApi":
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()

    def _headers(self) -> Dict[str, str]:
        return {
            "X-API-Key": self.api_key,
            "Accept": "application/json",
        }

    async def _retry(self, coro_fn, *args, label: str = "request") -> Optional[object]:
        """Run an async callable with retries and exponential back-off."""
        for attempt in range(1, self.retries + 1):
            try:
                return await coro_fn(*args)
            except aiohttp.ClientError as exc:
                logger.warning(
                    f"[NETWORK] {label} attempt {attempt}/{self.retries}: {exc}"
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"[TIMEOUT] {label} attempt {attempt}/{self.retries} exceeded {self.timeout.total}s"
                )
            except Exception as exc:
                logger.warning(f"[ERROR] {label}: {exc}")
                return None
            if attempt < self.retries:
                await asyncio.sleep(2 ** (attempt - 1))
        logger.warning(f"[FAILED] {label}: all {self.retries} attempts exhausted.")
        return None

    async def get_track(self, url: str) -> Optional[MusicTrack]:
        endpoint = f"{self.api_url}/api/track?url={urllib.parse.quote(url, safe='')}"

        async def _fetch() -> Optional[MusicTrack]:
            session = await self._get_session()
            async with session.get(endpoint, headers=self._headers()) as resp:
                data = await resp.json(content_type=None)
                if resp.status == 200 and isinstance(data, dict):
                    return MusicTrack.from_dict(data)
                error_msg = (
                    data.get("message") if isinstance(data, dict) else "Unknown error"
                )
                status = (
                    data.get("status", resp.status)
                    if isinstance(data, dict)
                    else resp.status
                )
                logger.warning(f"[API] {error_msg} (HTTP {status})")
                return None

        return await self._retry(_fetch, label=f"get_track({url})")

    async def download_cdn(self, cdn_url: str) -> Optional[str]:
        async def _download() -> Optional[str]:
            session = await self._get_session()
            async with session.get(cdn_url) as resp:
                if resp.status != 200:
                    logger.warning(
                        f"[HTTP {resp.status}] CDN download failed: {cdn_url}"
                    )
                    return None
                filename = _extract_filename(
                    resp.headers.get("Content-Disposition"), cdn_url
                )
                save_path = self.download_dir / filename
                async with aiofiles.open(save_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(16 * 1024):
                        if chunk:
                            await f.write(chunk)
                return str(save_path)

        return await self._retry(_download, label=f"download_cdn({cdn_url})")

    async def download_track(self, url: str) -> Optional[str]:
        track = await self.get_track(url)
        if not track:
            logger.warning("[❌] No track metadata found.")
            return None
        tg_match = _TG_URL_RE.match(track.cdnurl)
        if tg_match:
            return await self._download_from_telegram(track.cdnurl)
        return await self.download_cdn(track.cdnurl)

    async def _download_from_telegram(self, tg_url: str) -> Optional[str]:
        """
        match = _TG_URL_RE.match(tg_url)
        if not match:
            logger.warning(f'[TG] Malformed Telegram URL: {tg_url}')
            return None
        channel, message_id = match.group(1), int(match.group(2))
        """
        try:
            # msg = await self.app.get_messages(channel, message_id)
            msg = await self.app.get_messages(message_ids=tg_url)
            if not msg:
                logger.warning(f"[TG] Message ({tg_url} has no downloadable media.")
                return None
            return await msg.download(file_name=str(self.download_dir / ""))
        except errors.FloodWait as exc:
            logger.warning(f"[FLOODWAIT] Sleeping {exc.value}s…")
            await asyncio.sleep(exc.value + 1)
            return await self._download_from_telegram(tg_url)
        except Exception as exc:
            logger.warning(f"[TG DOWNLOAD ERROR] {exc}")
            return None


def _extract_filename(content_disposition: Optional[str], fallback_url: str) -> str:
    if content_disposition:
        match = _CD_FILENAME_RE.search(content_disposition)
        if match:
            return match.group(1).strip()
    basename = os.path.basename(fallback_url.split("?")[0])
    return basename or f"{uuid.uuid4().hex[:8]}.mp3"
