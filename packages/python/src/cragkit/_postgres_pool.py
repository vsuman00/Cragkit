from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import importlib
import math
import os
from pathlib import Path
import re
import stat
import sys
from typing import AsyncIterator, Callable, Protocol, Self, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .errors import DeadlineExceeded, InvalidRequest, ProviderUnavailable, UnsupportedCapability


class PoolConfig(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid", allow_inf_nan=False,
                              hide_input_in_errors=True)
    host: str = Field(repr=False)
    port: int = Field(default=5432, ge=1, le=65535)
    dbname: str = Field(repr=False)
    user: str = Field(repr=False)
    sslrootcert: Path = Field(repr=False)
    passfile: Path = Field(repr=False)
    max_size: int = Field(default=2, ge=1, le=2)
    max_waiting: int = Field(default=4, ge=0, le=16)
    startup_timeout: float = Field(default=5.0, gt=0, le=30)
    acquire_timeout: float = Field(default=2.0, gt=0, le=30)
    close_timeout: float = Field(default=2.0, gt=0, le=10)
    release_timeout: float = Field(default=1.0, gt=0, le=5)

    @field_validator("host")
    @classmethod
    def scalar_host(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", value):
            raise ValueError("Expected one DNS host or IPv4 address")
        return value

    @field_validator("dbname", "user")
    @classmethod
    def scalar_identity(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_.@-]+", value):
            raise ValueError("Expected a scalar database identity")
        return value

    @field_validator("sslrootcert", "passfile")
    @classmethod
    def absolute_path(cls, value: Path) -> Path:
        if not value.is_absolute() or any(char in str(value) for char in "\x00\r\n"):
            raise ValueError("Expected an absolute file path")
        return value

    @model_validator(mode="after")
    def release_budget(self) -> Self:
        if self.release_timeout > self.close_timeout:
            raise ValueError("Release timeout exceeds close timeout")
        return self


def parse_pool_config(value: object) -> PoolConfig:
    try:
        return PoolConfig.model_validate(value)
    except (ValueError, TypeError):
        pass
    raise InvalidRequest() from None


class ConnectionProtocol(Protocol):
    async def close(self) -> None: ...


class PoolProtocol(Protocol):
    async def open(self, wait: bool = False, timeout: float = 30.0) -> None: ...
    async def wait(self, timeout: float = 30.0) -> None: ...
    async def getconn(self, timeout: float | None = None) -> ConnectionProtocol: ...
    async def putconn(self, conn: ConnectionProtocol) -> None: ...
    async def close(self, timeout: float = 5.0) -> None: ...


def _owned_pool(config: PoolConfig) -> PoolProtocol:
    try:
        module = importlib.import_module("psycopg_pool")
    except ImportError:
        module = None
    if module is None:
        raise UnsupportedCapability() from None
    return cast(PoolProtocol, module.AsyncConnectionPool(
        conninfo="", open=False, min_size=1, max_size=config.max_size,
        max_waiting=max(1, config.max_waiting), timeout=config.acquire_timeout,
        reconnect_timeout=0.0, num_workers=1, name="cragkit-resource",
        kwargs={"host": config.host, "port": config.port, "dbname": config.dbname,
                "user": config.user, "sslmode": "verify-full",
                "sslrootcert": str(config.sslrootcert), "passfile": str(config.passfile),
                "connect_timeout": math.ceil(config.startup_timeout),
                "application_name": "cragkit-resource"},
    ))


class PoolResource:
    def __init__(self, config: PoolConfig, *, pool: PoolProtocol | None = None,
                 factory: Callable[[PoolConfig], PoolProtocol] | None = None) -> None:
        if pool is not None and factory is not None:
            raise InvalidRequest()
        self.config = config
        self._pool = pool
        self._owned = pool is None
        self._factory = factory or _owned_pool
        self._state = "new" if self._owned else "open"
        self._opening = asyncio.Lock()
        self._users: set[asyncio.Task[object]] = set()
        self._leases: dict[asyncio.Task[object], ConnectionProtocol] = {}
        self._closing: asyncio.Task[None] | None = None
        self._driver_closed = False
        self._driver_close_ok = True
        self._startup: asyncio.Task[object] | None = None

    def _check_owned_configuration(self) -> None:
        if any(key.startswith("PG") and value for key, value in os.environ.items()):
            raise InvalidRequest()
        try:
            if not self.config.sslrootcert.is_file():
                raise InvalidRequest()
            info = self.config.passfile.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise InvalidRequest()
        except OSError:
            pass
        else:
            return
        raise InvalidRequest() from None

    async def open(self) -> None:
        async with self._opening:
            if self._state == "open":
                return
            if self._state != "new":
                raise ProviderUnavailable()
            self._check_owned_configuration()
            self._startup = asyncio.current_task()
            failure = False
            unsupported = False
            try:
                self._pool = self._factory(self.config)
                async with asyncio.timeout(self.config.startup_timeout):
                    await self._pool.open(wait=False, timeout=self.config.startup_timeout)
                    await self._pool.wait(timeout=self.config.startup_timeout)
                if self._state != "new":
                    failure = True
                else:
                    self._state = "open"
            except asyncio.CancelledError:
                self._state = "closed"
                if self._closing is None:
                    await self._close_driver()
                raise
            except UnsupportedCapability:
                unsupported = True
            except Exception:
                failure = True
            finally:
                self._startup = None
            if unsupported or failure:
                self._state = "closed"
                if self._closing is None:
                    await self._close_driver()
                if unsupported:
                    raise UnsupportedCapability() from None
                raise ProviderUnavailable() from None

    async def _close_driver(self, budget: float | None = None) -> bool:
        if self._owned and self._pool is not None and not self._driver_closed:
            self._driver_closed = True
            timeout = budget if budget is not None else self.config.close_timeout
            try:
                async with asyncio.timeout(timeout):
                    await self._pool.close(timeout=timeout)
            except asyncio.CancelledError:
                self._driver_close_ok = False
                raise
            except Exception:
                self._driver_close_ok = False
        return self._driver_close_ok

    async def _release(self, connection: ConnectionProtocol) -> bool:
        assert self._pool is not None
        try:
            async with asyncio.timeout(self.config.release_timeout):
                await self._pool.putconn(connection)
            return True
        except Exception:
            try:
                async with asyncio.timeout(self.config.release_timeout):
                    await connection.close()
            except Exception:
                pass
            return False

    @asynccontextmanager
    async def lease(self, *, deadline: float) -> AsyncIterator[ConnectionProtocol]:
        """Bound acquisition by an absolute loop deadline; the caller bounds body work."""
        loop = asyncio.get_running_loop()
        if (isinstance(deadline, bool) or not isinstance(deadline, (int, float))
                or abs(deadline) > sys.float_info.max or not math.isfinite(deadline)):
            raise InvalidRequest()
        if deadline <= loop.time():
            raise DeadlineExceeded()
        if self._state != "open" or self._pool is None:
            raise ProviderUnavailable()
        task = asyncio.current_task()
        assert task is not None
        if task in self._users:
            raise InvalidRequest()
        if len(self._users) >= self.config.max_size + self.config.max_waiting:
            raise ProviderUnavailable()
        self._users.add(task)
        connection: ConnectionProtocol | None = None
        body_failed = False
        try:
            acquire_deadline = min(deadline, loop.time() + self.config.acquire_timeout)
            budget = acquire_deadline - loop.time()
            failed = False
            try:
                async with asyncio.timeout_at(acquire_deadline):
                    connection = await self._pool.getconn(timeout=budget)
            except asyncio.CancelledError:
                raise
            except Exception:
                failed = True
            if failed or loop.time() >= acquire_deadline:
                if loop.time() >= deadline:
                    raise DeadlineExceeded() from None
                raise ProviderUnavailable() from None
            assert connection is not None
            self._leases[task] = connection
            if self._state != "open":
                raise ProviderUnavailable()
            try:
                yield connection
            except BaseException:
                body_failed = True
                raise
        finally:
            try:
                if connection is not None:
                    cleanup = asyncio.create_task(self._release(connection))
                    try:
                        released = await asyncio.shield(cleanup)
                    except asyncio.CancelledError:
                        await asyncio.shield(cleanup)
                        raise
                    if not released and not body_failed:
                        raise ProviderUnavailable() from None
            finally:
                self._leases.pop(task, None)
                self._users.discard(task)

    async def _finish_close(self) -> None:
        loop = asyncio.get_running_loop()
        end = loop.time() + self.config.close_timeout
        users = set(self._users)
        if self._startup is not None:
            users.add(self._startup)
        for task in users:
            task.cancel()
        pending: set[asyncio.Task[object]] = set()
        if users:
            _, pending = await asyncio.wait(users, timeout=self.config.close_timeout / 2)
        if pending:
            async def force_release() -> None:
                for task in pending:
                    connection = self._leases.get(task)
                    if connection is not None:
                        await connection.close()
            try:
                async with asyncio.timeout(max(0.0, end - loop.time()) / 2):
                    await force_release()
            except Exception:
                pass
        closed = await self._close_driver(max(0.0, end - loop.time()))
        self._state = "closed"
        if pending or not closed:
            raise ProviderUnavailable() from None

    async def close(self) -> None:
        task = asyncio.current_task()
        if task in self._users:
            raise InvalidRequest()
        if self._closing is None:
            self._state = "closing"
            self._closing = asyncio.create_task(self._finish_close())
        await asyncio.shield(self._closing)
