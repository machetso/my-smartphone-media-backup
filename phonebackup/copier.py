"""Stream one source into several destination files at the same time and verify each copy.

The source is read only once; every destination has its own writer thread, so two
HDDs are written in parallel. After writing, each copy is flushed to disk (fsync)
and read back to compute its SHA-256.
"""

import hashlib
import os
import queue
import threading

CHUNK = 1024 * 1024
_END = object()


class Cancelled(Exception):
    """Raised when the user presses Cancel."""


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(CHUNK)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


class WriteResult:
    def __init__(self, path):
        self.path = path
        self.error = None
        self.sha256 = None
        self.bytes = 0


def _writer(q, res, fsync):
    f = None
    got_end = False
    try:
        os.makedirs(os.path.dirname(res.path), exist_ok=True)
        f = open(res.path, "wb")
        while True:
            chunk = q.get()
            if chunk is _END:
                got_end = True
                break
            f.write(chunk)
            res.bytes += len(chunk)
        f.flush()
        if fsync:
            os.fsync(f.fileno())
        f.close()
        f = None
        res.sha256 = sha256_file(res.path)      # read back = verification of the written copy
    except Exception as e:  # noqa: BLE001 - every failure must be reported, not crash the run
        res.error = f"{type(e).__name__}: {e}"
        # keep draining so the reader never blocks on a dead writer
        if not got_end:
            while q.get() is not _END:
                pass
    finally:
        if f is not None:
            try:
                f.close()
            except OSError:
                pass


def stream_copy(chunks, dest_paths, fsync=True, on_bytes=None, cancel=None):
    """Write the iterable `chunks` to all dest_paths in parallel.

    Returns (sha256_of_stream, bytes_read, [WriteResult, ...]).
    Exceptions raised by the source iterator propagate after writers are stopped.
    """
    results = [WriteResult(p) for p in dest_paths]
    queues = [queue.Queue(maxsize=16) for _ in dest_paths]
    threads = [threading.Thread(target=_writer, args=(q, r, fsync), daemon=True)
               for q, r in zip(queues, results)]
    for t in threads:
        t.start()
    h = hashlib.sha256()
    total = 0
    try:
        for chunk in chunks:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            if not chunk:
                continue
            h.update(chunk)
            total += len(chunk)
            for q, r in zip(queues, results):
                if r.error is None:
                    q.put(chunk)
            if on_bytes:
                on_bytes(len(chunk))
    finally:
        for q in queues:
            q.put(_END)
        for t in threads:
            t.join()
    return h.hexdigest(), total, results


def file_chunks(path):
    with open(path, "rb") as f:
        while True:
            b = f.read(CHUNK)
            if not b:
                return
            yield b
