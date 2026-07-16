import asyncio
import os
import random
import re
from pathlib import Path

import aiohttp
from py_yt import Playlist, VideosSearch

from VampireMusic import app, config, logger
from VampireMusic.core._fallen_api import FallenApi
from VampireMusic.core.lily import LilyApi, mask_key
from VampireMusic.helpers import Track, utils


class YouTube:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.cookies = []
        self.checked = False
        self.cookie_dir = "VampireMusic/cookies"
        self.warned = False
        self.regex = re.compile(
            r"(https?://)?(www\.|m\.|music\.)?"
            r"(youtube\.com/(watch\?v=|shorts/|playlist\?list=)|youtu\.be/)"
            r"([A-Za-z0-9_-]{11}|PL[A-Za-z0-9_-]+)([&?][^\s]*)?"
        )
        self.fallen = FallenApi(app)
        # Primary source: lily /search/all -> direct JioSaavn stream URL.
        # Fail fast so a slow/down provider falls through to the next source.
        self.lily = LilyApi(
            config.LILY_API_URL,
            config.LILY_API_KEY,
            name="lily",
            platform=config.LILY_PLATFORM,
            retries=1,
            timeout=15,
        )
        self.lily_fallback = LilyApi(
            config.LILY_FALLBACK_URL,
            config.LILY_FALLBACK_KEY,
            name="nexgen",
            platform=config.LILY_PLATFORM,
            retries=1,
            timeout=8,
        )

    def get_cookies(self):
        if not self.checked:
            for file in os.listdir(self.cookie_dir):
                if file.endswith(".txt"):
                    self.cookies.append(f"{self.cookie_dir}/{file}")
            self.checked = True
        if not self.cookies:
            if not self.warned:
                self.warned = True
                logger.warning("Cookies are missing; downloads might fail.")
            return None
        return random.choice(self.cookies)

    async def save_cookies(self, urls: list[str]) -> None:
        logger.info("Saving cookies from urls...")
        async with aiohttp.ClientSession() as session:
            for url in urls:
                name = url.split("/")[-1]
                link = "https://batbin.me/raw/" + name
                async with session.get(link) as resp:
                    resp.raise_for_status()
                    with open(f"{self.cookie_dir}/{name}.txt", "wb") as fw:
                        fw.write(await resp.read())
        logger.info(f"Cookies saved in {self.cookie_dir}.")

    def valid(self, url: str) -> bool:
        return bool(re.match(self.regex, url))

    def invalid(self, url: str) -> bool:
        """True only for a YouTube link that is malformed.

        Non-YouTube URLs (alt platforms, m3u8, direct media) are allowed
        through so they can be routed by the caller.
        """
        low = (url or "").lower()
        if "youtube.com" in low or "youtu.be" in low:
            return not self.valid(url)
        return False

    def _track_from_lily(self, item: dict, m_id: int) -> Track:
        """Build a Track from a lily/JioSaavn result (stream URL preset)."""
        dur = int(float(item.get("duration") or 0))
        return Track(
            id=item.get("id"),
            channel_name=item.get("artists"),
            duration=f"{dur // 60}:{dur % 60:02d}",
            duration_sec=dur,
            message_id=m_id,
            title=(item.get("title") or "")[:25],
            thumbnail=item.get("thumbnail"),
            url=item.get("url"),
            file_path=item.get("stream_url"),
            view_count=item.get("album") or "",
            video=False,
        )

    async def search(
        self,
        query: str,
        m_id: int,
        video: bool = False,
        stream_first: bool = True,
    ) -> Track | None:
        # Prefer lily/JioSaavn for audio text queries: it returns a ready
        # stream URL, so playback needs no separate download step. Skip it
        # for video (audio-only source) and for YouTube URLs.
        if stream_first and not video and not self.valid(query):
            item = await self.lily.search(query)
            source = "lily" if item else None
            if not item:
                item = await self.lily_fallback.search(query)
                if item:
                    source = "nexgen"
            if item and item.get("stream_url"):
                track = self._track_from_lily(item, m_id)
                track.source = source
                return track

        try:
            _search = VideosSearch(query, limit=1, with_live=False)
            results = await _search.next()
        except Exception:
            return None
        if results and results["result"]:
            data = results["result"][0]
            return Track(
                id=data.get("id"),
                channel_name=data.get("channel", {}).get("name"),
                duration=data.get("duration"),
                duration_sec=utils.to_seconds(data.get("duration")),
                message_id=m_id,
                title=data.get("title")[:25],
                thumbnail=data.get("thumbnails", [{}])[-1].get("url").split("?")[0],
                url=data.get("link"),
                view_count=data.get("viewCount", {}).get("short"),
                video=video,
            )
        return None

    async def search_multi(self, query: str, m_id: int, video: bool = False, limit: int = 5) -> list[Track]:
        try:
            _search = VideosSearch(query, limit=limit, with_live=False)
            results = await _search.next()
        except Exception:
            return []
        tracks = []
        if results and results["result"]:
            for data in results["result"]:
                tracks.append(
                    Track(
                        id=data.get("id"),
                        channel_name=data.get("channel", {}).get("name"),
                        duration=data.get("duration"),
                        duration_sec=utils.to_seconds(data.get("duration")),
                        message_id=m_id,
                        title=data.get("title")[:25],
                        thumbnail=data.get("thumbnails", [{}])[-1].get("url").split("?")[0],
                        url=data.get("link"),
                        view_count=data.get("viewCount", {}).get("short"),
                        video=video,
                    )
                )
        return tracks

    # Canonical watch-page URL templates for the platforms /play accepts.
    _PLATFORM_URL = {
        "youtube": "https://youtu.be/{id}",
        "soundcloud": "https://soundcloud.com/{id}",
        "dailymotion": "https://www.dailymotion.com/video/{id}",
        "vimeo": "https://vimeo.com/{id}",
        "facebook": "https://www.facebook.com/watch/?v={id}",
        "bilibili": "https://www.bilibili.com/video/{id}",
    }

    async def resolve_video(
        self, video_id: str, m_id: int = 0, platform: str = "youtube"
    ) -> Track | None:
        """Resolve a video id to a direct, streamable URL via lily ``/play``.

        Uses ``GET /play?type=video&platform=&id=`` which returns a
        ``direct_url`` (e.g. a YouTube googlevideo mp4, or a resolved
        Dailymotion/Vimeo/Facebook/Bilibili stream). Feeding that URL
        straight to PyTgCalls avoids the slow local download. Returns
        ``None`` on failure so the caller can fall back to downloading.
        """
        if not config.LILY_API_KEY:
            return None
        base = config.LILY_API_URL.rstrip("/")
        params = {
            "type": "video",
            "platform": platform,
            "id": video_id,
            "api_key": config.LILY_API_KEY,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{base}/play",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    data = await resp.json(content_type=None)
            if not (data.get("success") and data.get("direct_url")):
                logger.warning(
                    f"[VIDEO] /play returned no direct_url for {platform}:{video_id}"
                )
                return None
            dur = int(float(data.get("duration") or 0))
            url_tmpl = self._PLATFORM_URL.get(platform, "{id}")
            track = Track(
                id=video_id,
                channel_name=data.get("channel") or "",
                duration=f"{dur // 60}:{dur % 60:02d}",
                duration_sec=dur,
                message_id=m_id,
                title=(data.get("title") or "Unknown")[:25],
                thumbnail=data.get("thumbnail") or config.DEFAULT_THUMB,
                url=url_tmpl.format(id=video_id),
                file_path=data["direct_url"],
                video=True,
            )
            track.source = "lily"
            return track
        except Exception as e:
            logger.warning(
                f"[VIDEO] resolve_video({platform}:{video_id}) failed: {e}"
            )
            return None

    # Regexes to detect an alt-platform watch URL and pull its id.
    _ALT_PATTERNS = {
        "dailymotion": re.compile(r"(?:dailymotion\.com/video/|dai\.ly/)([A-Za-z0-9]+)"),
        "vimeo": re.compile(r"vimeo\.com/(?:video/)?(\d+)"),
        "facebook": re.compile(r"facebook\.com/(?:watch/?\?v=|[^/]+/videos/)(\d+)"),
        "bilibili": re.compile(r"bilibili\.com/video/([A-Za-z0-9]+)"),
    }

    def detect_platform(self, url: str) -> tuple[str, str] | None:
        """Return ``(platform, id)`` for a supported alt-platform URL, else None."""
        for platform, pat in self._ALT_PATTERNS.items():
            match = pat.search(url or "")
            if match:
                return platform, match.group(1)
        return None

    async def playlist(
        self, limit: int, user: str, url: str, video: bool
    ) -> list[Track | None]:
        tracks = []
        try:
            plist = await Playlist.get(url)
            for data in plist["videos"][:limit]:
                track = Track(
                    id=data.get("id"),
                    channel_name=data.get("channel", {}).get("name", ""),
                    duration=data.get("duration"),
                    duration_sec=utils.to_seconds(data.get("duration")),
                    title=data.get("title")[:25],
                    thumbnail=data.get("thumbnails")[-1].get("url").split("?")[0],
                    url=data.get("link").split("&list=")[0],
                    user=user,
                    view_count="",
                    video=video,
                )
                tracks.append(track)
        except Exception:
            pass
        return tracks

    async def _lily_direct_url(
        self, video_id: str, kind: str = "audio", platform: str = "youtube"
    ) -> str | None:
        """Get a direct stream URL for ``video_id`` from the lily API.

        Used as the primary download path so YouTube audio/video plays
        without depending on the (frequently key-less) teaminflex endpoint.
        Returns the ``direct_url`` or ``None`` on failure.
        """
        if not config.LILY_API_KEY:
            return None
        base = config.LILY_API_URL.rstrip("/")
        params = {
            "type": kind,
            "platform": platform,
            "id": video_id,
            "api_key": config.LILY_API_KEY,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{base}/play",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    data = await resp.json(content_type=None)
            if data.get("success") and data.get("direct_url"):
                return data["direct_url"]
            logger.warning(
                f"[LILY] /play {kind} returned no direct_url for "
                f"{platform}:{video_id} -> {data}"
            )
            return None
        except Exception as e:
            logger.warning(f"[LILY] direct_url({kind}:{video_id}) failed: {e}")
            return None

    async def _download_audio(self, video_id: str):
        # Primary path: lily direct audio URL (no local download needed).
        if config.LILY_API_KEY:
            url = await self._lily_direct_url(video_id, "audio")
            if url:
                logger.info(
                    f"🎵 [AUDIO] Resolved ID {video_id} via lily direct_url"
                )
                return url
            logger.warning(
                f"🎵 [AUDIO] lily direct_url unavailable for {video_id}; "
                f"falling back to {config.API_URL}"
            )

        if not config.API_KEY:
            logger.error(
                f"🎵 [AUDIO] Download FAILED for {video_id}: no API key set "
                f"(set LILY_API_KEY or API_KEY in .env)."
            )
            return None

        logger.info(
            f"🎵 [AUDIO] Starting download for ID {video_id} via "
            f"{config.API_URL} key={mask_key(config.API_KEY)}"
        )

        path = Path(f"downloads/{video_id}.webm")
        os.makedirs("downloads", exist_ok=True)

        if path.exists():
            logger.info(f"🎵 [LOCAL] Found existing audio for ID {video_id}")
            return str(path)

        payload = {"url": video_id, "type": "audio"}
        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": config.API_KEY,
        }

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    f"{config.API_URL}/download",
                    json=payload,
                    headers=headers,
                ) as response:
                    data = await response.json(content_type=None)

                if data and data.get("status") == "error":
                    logger.error(f"[AUDIO] API ERROR → {data}")
                    return None

                retries = 10

                if not data or not data.get("download_url"):
                    logger.warning(
                        "[AUDIO] File not ready / JSON missing → retrying..."
                    )

                    for i in range(retries):
                        await asyncio.sleep(8)

                        async with session.post(
                            f"{config.API_URL}/download",
                            json=payload,
                            headers=headers,
                        ) as response:
                            data = await response.json(content_type=None)

                        if data and data.get("status") == "error":
                            logger.error(f"[AUDIO] API ERROR during retry → {data}")
                            return None

                        if (
                            data
                            and data.get("status") == "success"
                            and data.get("download_url")
                        ):
                            logger.info(f"[AUDIO] Got URL after retry #{i + 1}")
                            break

                        logger.warning(
                            f"[AUDIO] Retry {i + 1}/{retries} → still not ready"
                        )

                if not data or not data.get("download_url"):
                    logger.error(f"[AUDIO] FAILED after all retries → {data}")
                    return None

                download_link = config.API_URL + data["download_url"]

                async with session.get(download_link) as file_response:
                    if file_response.status != 200:
                        logger.error(
                            f"[AUDIO] Download failed → {file_response.status}"
                        )
                        return None

                    with open(path, "wb") as f:
                        async for chunk in file_response.content.iter_chunked(8192):
                            f.write(chunk)

                logger.info(f"🎵 [API] Audio download completed for {video_id}")
                return str(path)

            except Exception as e:
                logger.error(f"[AUDIO] Exception: {e}")
                return None

    async def _download_video(self, video_id: str):
        # Primary path: lily direct video URL (no local download needed).
        if config.LILY_API_KEY:
            url = await self._lily_direct_url(video_id, "video")
            if url:
                logger.info(
                    f"🎥 [VIDEO] Resolved ID {video_id} via lily direct_url"
                )
                return url
            logger.warning(
                f"🎥 [VIDEO] lily direct_url unavailable for {video_id}; "
                f"falling back to {config.API_URL}"
            )

        if not config.API_KEY:
            logger.error(
                f"🎥 [VIDEO] Download FAILED for {video_id}: no API key set "
                f"(set LILY_API_KEY or API_KEY in .env)."
            )
            return None

        logger.info(
            f"🎥 [VIDEO] Starting download for ID {video_id} via "
            f"{config.API_URL} key={mask_key(config.API_KEY)}"
        )

        path = Path(f"downloads/{video_id}.mkv")
        os.makedirs("downloads", exist_ok=True)

        if path.exists():
            logger.info(f"🎥 [LOCAL] Found existing video for ID {video_id}")
            return str(path)

        payload = {"url": video_id, "type": "video"}
        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": config.API_KEY,
        }

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    f"{config.API_URL}/download",
                    json=payload,
                    headers=headers,
                ) as response:
                    data = await response.json(content_type=None)

                if data and data.get("status") == "error":
                    logger.error(f"[VIDEO] API ERROR → {data}")
                    return None

                retries = 20

                if not data or not data.get("download_url"):
                    logger.warning(
                        "[VIDEO] File not ready / JSON missing → retrying..."
                    )

                    for i in range(retries):
                        await asyncio.sleep(20)

                        async with session.post(
                            f"{config.API_URL}/download",
                            json=payload,
                            headers=headers,
                        ) as response:
                            data = await response.json(content_type=None)

                        if data and data.get("status") == "error":
                            logger.error(f"[VIDEO] API ERROR during retry → {data}")
                            return None

                        if (
                            data
                            and data.get("status") == "success"
                            and data.get("download_url")
                        ):
                            logger.info(f"[VIDEO] Got URL after retry #{i + 1}")
                            break

                        logger.warning(
                            f"[VIDEO] Retry {i + 1}/{retries} → still not ready"
                        )

                if not data or not data.get("download_url"):
                    logger.error(f"[VIDEO] FAILED after all retries → {data}")
                    return None

                download_link = config.API_URL + data["download_url"]

                async with session.get(download_link) as file_response:
                    if file_response.status != 200:
                        logger.error(
                            f"[VIDEO] Download failed → {file_response.status}"
                        )
                        return None

                    with open(path, "wb") as f:
                        async for chunk in file_response.content.iter_chunked(8192):
                            f.write(chunk)

                logger.info(f"🎥 [API] Video download completed for {video_id}")
                return str(path)

            except Exception as e:
                logger.error(f"[VIDEO] Exception: {e}")
                return None

    async def download(self, video_id: str, video: bool = False):
        # Reached only for YouTube ids (URL plays, playlists, autoplay,
        # /song). JioSaavn tracks already carry their stream URL in
        # file_path, so they never hit this download path.
        if video:
            return await self._download_video(video_id)
        return await self._download_audio(video_id)

    async def close(self):
        await self.fallen.close()
        await self.lily.close()
        await self.lily_fallback.close()
