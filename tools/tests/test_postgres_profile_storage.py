"""Native harness bounds are tested without starting a database or child process."""
import asyncio
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_postgres_profile_storage import read_bounded


def test_output_limit_is_cumulative_across_partial_pipe_reads():
    async def run():
        stream = asyncio.StreamReader()
        task = asyncio.create_task(read_bounded(stream, 4))
        stream.feed_data(b'abc')
        await asyncio.sleep(0)
        stream.feed_data(b'de')
        stream.feed_eof()
        with pytest.raises(RuntimeError, match='profile_child_output_limit'):
            await task
    asyncio.run(run())


def test_exact_output_limit_preserves_all_chunks_until_eof():
    async def run():
        stream = asyncio.StreamReader()
        task = asyncio.create_task(read_bounded(stream, 4))
        stream.feed_data(b'ab')
        await asyncio.sleep(0)
        assert not task.done()
        stream.feed_data(b'cd')
        stream.feed_eof()
        assert await task == b'abcd'
    asyncio.run(run())
