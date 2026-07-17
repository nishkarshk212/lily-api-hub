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
            if os.path.exists(self.cookie_dir):
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
        os.makedirs(self.cookie_dir, exist_ok=True)
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
        """Build a Track from a lily/JioSaavn result (stream URL preset).

        Note: only set ``file_path`` from ``stream_url`` when it is a real
        direct media URL (JioSaavn). lily's YouTube ``direct_url`` is
        IP-locked to the lily backend and 403s from this server, so it must
        NOT be used as a stream source — the download path (yt-dlp) fetches a
        fresh, IP-correct URL instead.
        """
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
            # Both music sources returned nothing (dead key / empty / error).
            # Fall through to the YouTube search below so a song-name query
            # still resolves to a YouTube video instead of failing outright.
            logger.info(
                f"[SEARCH] music sources (lily/nexgen) returned no result "
                f"for {query!r}; falling back to YouTube search."
            )

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

        Used for alt-platform links (Dailymotion/Vimeo/Facebook/Bilibili).
        NOTE: lily's ``direct_url`` is IP-locked to the lily backend and 403s
        from this server, so for ``youtube`` we return ``None`` and let the
        caller download locally via yt-dlp (which fetches an IP-correct URL).
        Returns ``None`` on failure so the caller can fall back to downloading.
        """
        if platform == "youtube":
            # yt-dlp handles YouTube locally with a correct IP-bound URL.
            return None
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

    async def _yt_dlp_download(
        self, video_id: str, video: bool
    ) -> str | None:
        """Download a YouTube id to a local file via yt-dlp and return the path.

        The bot server's egress IP is bot-flagged by YouTube, so a plain
        download hits "Sign in to confirm you're not a bot". A cookies.txt
        exported from a real YouTube account (dropped into
        ``VampireMusic/cookies/``) bypasses that — we try with cookies first,
        then without. The resulting local file is IP-correct and playable by
        PyTgCalls (unlike lily's ``direct_url``, which is IP-locked to the
        lily backend and 403s here).
        """
        from yt_dlp import YoutubeDL

        os.makedirs("downloads", exist_ok=True)
        out_tmpl = f"downloads/{video_id}.%(ext)s"
        base_opts = {
            "outtmpl": out_tmpl,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "format": (
                "bestvideo+bestaudio/best"
                if video
                else "bestaudio/best"
            ),
            "postprocessors": (
                []
                if video
                else [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "webm",
                        "preferredquality": "192",
                    }
                ]
            ),
            "merge_output_format": "mkv" if video else None,
            "ffmpeg_location": "/usr/bin",
            "retries": 3,
            "socket_timeout": 30,
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
        }
        url = f"https://www.youtube.com/watch?v={video_id}"

        # Try with cookies first (only thing that beats the bot-check here).
        cookie = self.get_cookies()
        attempts = []
        if cookie:
            attempts.append((f"{'VIDEO' if video else 'AUDIO'}", {**base_opts, "cookiefile": cookie}))
        attempts.append((f"{'VIDEO' if video else 'AUDIO'} (no cookies)", base_opts))

        last_err = None
        for label, opts in attempts:
            try:
                await asyncio.to_thread(self._run_yt_dlp, opts, url)
            except Exception as e:  # yt-dlp raises on failure
                last_err = e
                logger.warning(f"[{label}] yt-dlp failed for {video_id}: {e}")
                continue
            # Locate the produced file.
            for candidate in Path("downloads").glob(f"{video_id}.*"):
                if candidate.suffix.lstrip(".") in ("webm", "mkv", "mp4", "opus"):
                    logger.info(
                        f"🎵 [YTDLP] {'video' if video else 'audio'} "
                        f"download completed for {video_id} ({label})"
                    )
                    return str(candidate)
            logger.warning(f"[{label}] yt-dlp produced no file for {video_id}")
        if last_err:
            logger.error(
                f"[{'VIDEO' if video else 'AUDIO'}] yt-dlp error: {last_err}"
            )
        return None

    @staticmethod
    def _run_yt_dlp(ydl_opts: dict, url: str) -> None:
        from yt_dlp import YoutubeDL

        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

    async def _fetch_to_local(self, url: str, video_id: str, video: bool) -> str | None:
        """Download a known direct stream URL to a local, IP-correct file."""
        ext = "mkv" if video else "webm"
        path = Path(f"downloads/{video_id}.{ext}")
        if path.exists() and path.stat().st_size > 0:
            return str(path)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=600),
                    allow_redirects=True,
                ) as fr:
                    if fr.status != 200:
                        logger.warning(
                            f"🌐 direct fetch failed: HTTP {fr.status} for {video_id}"
                        )
                        return None
                    os.makedirs("downloads", exist_ok=True)
                    with open(path, "wb") as f:
                        async for chunk in fr.content.iter_chunked(1024 * 1024):
                            f.write(chunk)
            if path.exists() and path.stat().st_size > 0:
                logger.info(f"🌐 direct fetch completed for {video_id}")
                return str(path)
        except Exception as e:
            logger.warning(f"🌐 direct fetch error for {video_id}: {e}")
        return None

    async def _lily_download(self, video_id: str, video: bool) -> str | None:
        """Fetch a streamable URL from a lily backend and download it locally.

        The lily proxy streaming endpoints (/play/audio and /play/video/hq) are
        used directly first as they bypass YouTube IP restrictions via the API's proxy.
        If they fail or are not supported, it falls back to querying /play to get
        the proxy_url or direct_url and downloads from there.
        Tries every configured lily backend in order; returns the local path or
        None if all fail.
        """
        if not config.LILY_API_KEY and not config.LILY_FALLBACK_KEY:
            return None
        kind = "video" if video else "audio"
        ext = "mkv" if video else "webm"
        path = Path(f"downloads/{video_id}.{ext}")
        if path.exists() and path.stat().st_size > 0:
            logger.info(f"💾 [LOCAL] Found existing {kind} for ID {video_id}")
            return str(path)
        backends = [
            (config.LILY_API_URL, config.LILY_API_KEY, "lily"),
            (config.LILY_FALLBACK_URL, config.LILY_FALLBACK_KEY, "nexgen"),
        ]
        for base, key, name in backends:
            if not base or not key:
                continue

            # Strategy 1: Direct Proxy Stream Download (Most resilient)
            proxy_endpoint = f"{base.rstrip('/')}/play/{'video/hq' if video else 'audio'}"
            params = {
                "id": video_id,
                "platform": "youtube",
                "api_key": key,
            }
            if not video:
                params["format"] = "raw"

            logger.info(f"💾 [{name}] Attempting direct proxy stream download for {kind} ID {video_id}...")
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        proxy_endpoint,
                        params=params,
                        timeout=aiohttp.ClientTimeout(total=600),
                    ) as resp:
                        if resp.status == 200:
                            os.makedirs("downloads", exist_ok=True)
                            with open(path, "wb") as f:
                                async for chunk in resp.content.iter_chunked(1024 * 1024):
                                    f.write(chunk)
                            if path.exists() and path.stat().st_size > 0:
                                logger.info(
                                    f"💾 [{name.upper()}] {kind} download completed via proxy endpoint for {video_id}"
                                )
                                return str(path)
                        else:
                            logger.warning(
                                f"[{name}] Proxy endpoint returned HTTP {resp.status} for {video_id}"
                            )
            except Exception as e:
                logger.warning(
                    f"[{name}] Proxy endpoint download failed for {video_id}: {e}"
                )

            # Strategy 2: Fallback to /play resolved URLs
            params_play = {
                "type": kind,
                "platform": "youtube",
                "id": video_id,
                "api_key": key,
            }
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{base.rstrip('/')}/play",
                        params=params_play,
                        timeout=aiohttp.ClientTimeout(total=25),
                    ) as resp:
                        data = await resp.json(content_type=None)

                if not data.get("success"):
                    logger.warning(
                        f"[{name}] /play {kind} returned success=False for {video_id}"
                    )
                    continue

                du = data.get("proxy_url")
                if du:
                    # Append API key since the server-generated proxy_url lacks it
                    if "?" in du:
                        du += f"&api_key={key}"
                    else:
                        du += f"?api_key={key}"
                else:
                    du = data.get("direct_url")

                if not du:
                    logger.warning(
                        f"[{name}] /play {kind} returned no playable URL for {video_id}"
                    )
                    continue

                logger.info(
                    f"💾 [{name}] Downloading {kind} for {video_id} via resolved URL"
                )
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        du,
                        timeout=aiohttp.ClientTimeout(total=600),
                        allow_redirects=True,
                    ) as fr:
                        if fr.status != 200:
                            logger.warning(
                                f"[{name}] Stream download failed: HTTP {fr.status}"
                            )
                            continue
                        os.makedirs("downloads", exist_ok=True)
                        with open(path, "wb") as f:
                            async for chunk in fr.content.iter_chunked(1024 * 1024):
                                f.write(chunk)
                if path.exists() and path.stat().st_size > 0:
                    logger.info(
                        f"💾 [{name.upper()}] {kind} download completed for {video_id}"
                    )
                    return str(path)
            except Exception as e:
                logger.warning(
                    f"[{name}] Fallback /play download failed for {video_id}: {e}"
                )
                continue
        return None

    async def _download_audio(self, video_id: str):
        # Resilient chain: lily backend (downloads a local, IP-correct file)
        # -> yt-dlp (local, needs cookies on bot-flagged IPs) -> teaminflex.
        # lily is first because it does not depend on this server's IP.
        local = await self._lily_download(video_id, video=False)
        if local:
            return local

        path = Path(f"downloads/{video_id}.webm")
        if path.exists():
            logger.info(f"🎵 [LOCAL] Found existing audio for ID {video_id}")
            return str(path)

        logger.info(f"🎵 [AUDIO] Downloading ID {video_id} via yt-dlp")
        local = await self._yt_dlp_download(video_id, video=False)
        if local:
            return local

        if not config.API_KEY:
            logger.error(
                f"🎵 [AUDIO] Download FAILED for {video_id}: yt-dlp failed "
                f"and no API_KEY set for teaminflex fallback."
            )
            return None

        logger.warning(
            f"🎵 [AUDIO] yt-dlp failed; falling back to {config.API_URL}"
        )
        return await self._download_via_api(video_id, audio=True)

    async def _download_via_api(self, video_id: str, audio: bool) -> str | None:
        """Fallback download through the teaminflex API (requires API_KEY)."""
        kind = "audio" if audio else "video"
        path = Path(f"downloads/{video_id}.{'webm' if audio else 'mkv'}")
        os.makedirs("downloads", exist_ok=True)
        payload = {"url": video_id, "type": kind}
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
                    logger.error(f"[{kind.upper()}] API ERROR → {data}")
                    return None
                retries = 10 if audio else 20
                if not data or not data.get("download_url"):
                    for i in range(retries):
                        await asyncio.sleep(8 if audio else 20)
                        async with session.post(
                            f"{config.API_URL}/download",
                            json=payload,
                            headers=headers,
                        ) as response:
                            data = await response.json(content_type=None)
                        if data and data.get("status") == "error":
                            logger.error(f"[{kind.upper()}] API ERROR → {data}")
                            return None
                        if data and data.get("download_url"):
                            break
                if not data or not data.get("download_url"):
                    logger.error(f"[{kind.upper()}] FAILED → {data}")
                    return None
                download_link = config.API_URL + data["download_url"]
                async with session.get(download_link) as fr:
                    if fr.status != 200:
                        logger.error(f"[{kind.upper()}] download → {fr.status}")
                        return None
                    with open(path, "wb") as f:
                        async for chunk in fr.content.iter_chunked(8192):
                            f.write(chunk)
                logger.info(f"🎵 [API] {kind} download completed for {video_id}")
                return str(path)
            except Exception as e:
                logger.error(f"[{kind.upper()}] Exception: {e}")
                return None

    async def _download_video(self, video_id: str):
        # Resilient chain: lily backend (downloads a local, IP-correct file)
        # -> yt-dlp (local, needs cookies on bot-flagged IPs) -> teaminflex.
        # lily is first because it does not depend on this server's IP.
        local = await self._lily_download(video_id, video=True)
        if local:
            return local

        path = Path(f"downloads/{video_id}.mkv")
        if path.exists():
            logger.info(f"🎥 [LOCAL] Found existing video for ID {video_id}")
            return str(path)

        logger.info(f"🎥 [VIDEO] Downloading ID {video_id} via yt-dlp")
        local = await self._yt_dlp_download(video_id, video=True)
        if local:
            return local

        if not config.API_KEY:
            logger.error(
                f"🎥 [VIDEO] Download FAILED for {video_id}: yt-dlp failed "
                f"and no API_KEY set for teaminflex fallback."
            )
            return None

        logger.warning(
            f"🎥 [VIDEO] yt-dlp failed; falling back to {config.API_URL}"
        )
        return await self._download_via_api(video_id, audio=False)

    async def download(self, video_id: str, video: bool = False):
        # Reached only for YouTube ids (URL plays, playlists, autoplay,
        # /song). JioSaavn tracks already carry their stream URL in
        # file_path, so they never hit this download path.
        if config.DIRECT_STREAM and (config.LILY_API_KEY or config.LILY_FALLBACK_KEY):
            backends = [
                (config.LILY_API_URL, config.LILY_API_KEY, "lily"),
                (config.LILY_FALLBACK_URL, config.LILY_FALLBACK_KEY, "nexgen"),
            ]
            kind = "video" if video else "audio"
            for base, key, name in backends:
                if not base or not key:
                    continue
                params = {
                    "type": kind,
                    "platform": "youtube",
                    "id": video_id,
                    "api_key": key,
                }
                logger.info(f"💾 [DIRECT STREAM] [{name}] Resolving live play link for {kind} ID {video_id}...")
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            f"{base.rstrip('/')}/play",
                            params=params,
                            timeout=aiohttp.ClientTimeout(total=20),
                        ) as resp:
                            data = await resp.json(content_type=None)
                    if data.get("success"):
                        du = None
                        if not video:
                            # For audio: prefer proxy_url (with raw format to bypass transcoding latency)
                            du = data.get("proxy_url")
                            if du:
                                if "?" in du:
                                    du += f"&api_key={key}"
                                else:
                                    du += f"?api_key={key}"
                                du += "&format=raw"
                        
                        if not du:
                            # Fallback for audio or default for video (direct resolved YouTube CDN link)
                            du = data.get("direct_url")
                            
                        if du:
                            logger.info(f"💾 [DIRECT STREAM] [{name}] Successfully resolved: {du[:60]}...")
                            return du
                    else:
                        logger.warning(f"[DIRECT STREAM] [{name}] returned success=False: {data}")
                except Exception as e:
                    logger.warning(f"[DIRECT STREAM] [{name}] Failed to resolve play stream: {e}")

        if video:
            return await self._download_video(video_id)
        return await self._download_audio(video_id)

    async def close(self):
        await self.fallen.close()
        await self.lily.close()
        await self.lily_fallback.close()
