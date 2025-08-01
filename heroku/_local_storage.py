"""Saves modules to disk and fetches them if remote storage is not available."""

# ©️ Dan Gazizullin, 2021-2023
# This file is a part of Hikka Userbot
# 🌐 https://github.com/hikariatama/Hikka
# You can redistribute it and/or modify it under the terms of the GNU AGPLv3
# 🔑 https://www.gnu.org/licenses/agpl-3.0.html

# ©️ Codrago, 2024-2025
# This file is a part of Heroku Userbot
# 🌐 https://github.com/coddrago/Heroku
# You can redistribute it and/or modify it under the terms of the GNU AGPLv3
# 🔑 https://www.gnu.org/licenses/agpl-3.0.html

import asyncio
import contextlib
import hashlib
import logging
import os
import typing

import requests

from . import utils
from .tl_cache import CustomTelegramClient
from .version import __version__

logger = logging.getLogger(__name__)

MAX_FILESIZE = 1024 * 1024 * 5  # 5 MB
MAX_TOTALSIZE = 1024 * 1024 * 100  # 100 MB


class LocalStorage:
    """Saves modules to disk and fetches them if remote storage is not available."""

    def __init__(self):
        self._path = os.path.join(os.path.expanduser("~"), ".heroku", "modules_cache")
        self._ensure_dirs()

    @property
    def _total_size(self) -> int:
        return sum(os.path.getsize(f.path) for f in os.scandir(self._path))

    def _ensure_dirs(self):
        """Ensures that the local storage directory exists."""
        if not os.path.isdir(self._path):
            os.makedirs(self._path)

    def _get_path(self, repo: str, module_name: str) -> str:
        return os.path.join(
            self._path,
            hashlib.sha256(f"{repo}_{module_name}".encode()).hexdigest() + ".py",
        )

    def save(self, repo: str, module_name: str, module_code: str):
        """
        Saves module to disk.
        :param repo: Repository name.
        :param module_name: Module name.
        :param module_code: Module source code.
        """
        size = len(module_code)
        if size > MAX_FILESIZE:
            logger.warning(
                "Module %s from %s is too large (%s bytes) to save to local cache.",
                module_name,
                repo,
                size,
            )
            return

        if self._total_size + size > MAX_TOTALSIZE:
            logger.warning(
                "Local storage is full, cannot save module %s from %s.",
                module_name,
                repo,
            )
            return

        with open(self._get_path(repo, module_name), "w") as f:
            f.write(module_code)

        logger.debug("Saved module %s from %s to local cache.", module_name, repo)

    def fetch(self, repo: str, module_name: str) -> typing.Optional[str]:
        """
        Fetches module from disk.
        :param repo: Repository name.
        :param module_name: Module name.
        :return: Module source code or None.
        """
        path = self._get_path(repo, module_name)
        if os.path.isfile(path):
            with open(path, "r") as f:
                return f.read()

        return None


class RemoteStorage:
    def __init__(self, client: CustomTelegramClient):
        self._local_storage = LocalStorage()
        self._client = client

    async def preload(self, urls: typing.List[str]):
        """Preloads modules from remote storage."""
        logger.debug("Preloading modules from remote storage.")
        for url in urls:
            logger.debug("Preloading module %s", url)

            with contextlib.suppress(Exception):
                await self.fetch(url)

            await asyncio.sleep(5)


    @staticmethod
    def _parse_url(url: str) -> typing.Tuple[str, str, str]:
        """
        Parses a URL into a repository and module name.
        :param url: URL to parse.
        :return: Tuple of (url, repo, module_name).
        """
        domain_name = url.split("/")[2]

        if domain_name == "raw.githubusercontent.com":
            owner, repo, branch = url.split("/")[3:6]
            module_name = url.split("/")[-1].split(".")[0]
            repo = f"git+{owner}/{repo}:{branch}"
        elif domain_name == "github.com":
            owner, repo, _, branch = url.split("/")[3:7]
            module_name = url.split("/")[-1].split(".")[0]
            repo = f"git+{owner}/{repo}:{branch}"
        else:
            repo, module_name = url.rsplit("/", maxsplit=1)
            repo = repo.strip("/")

        return url, repo, module_name

    async def fetch(self, url: str, auth: typing.Optional[str] = None) -> str:
        """
        Fetches the module from the remote storage.
        :param url: URL to the module.
        :param auth: Optional authentication string in the format "username:password".
        :return: Module source code.
        """
        url, repo, module_name = self._parse_url(url)
        try:
            r = await utils.run_sync(
                requests.get,
                url,
                auth=(tuple(auth.split(":", 1)) if auth else None),
                headers={
                    "User-Agent": "Chrome"
                    #"X-Heroku-Version": ".".join(map(str, __version__)),
                    #"X-Heroku-Commit-SHA": utils.get_git_hash(),
                    #"X-Heroku-User": str(self._client.tg_id),
                },
            )
            r.raise_for_status()
        except Exception:
            logger.debug(
                "Can't load module from remote storage. Trying local storage.",
                exc_info=True,
            )
            if module := self._local_storage.fetch(repo, module_name):
                logger.debug("Module source loaded from local storage.")
                return module

            raise

        self._local_storage.save(repo, module_name, r.text)

        return r.text
