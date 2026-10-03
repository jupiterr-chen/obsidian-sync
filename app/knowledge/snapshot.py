"""Immutable content-addressed snapshot store (ADR0003).

A snapshot copies a source version's bytes into ``<root>/<sha256[:2]>/<sha256>``
exactly once. The copy is produced from the *same open file descriptor* that
was hashed, then re-hashed from disk before an atomic rename, so the stored
blob provably equals the verified bytes. Existing blobs are never overwritten;
identical content across sources/documents shares one physical blob.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
from typing import BinaryIO, Optional, Tuple

from .store import IntegrityError, KnowledgeStore, utc_now

CHUNK = 1 << 20
STAGE_CONFIG = {"store": "content-addressed", "format": 1}


class SnapshotError(Exception):
    """Base class for snapshot failures."""


class SourceConflict(SnapshotError):
    """Upstream bytes do not match the version identity (fail closed)."""


class SourceUnstable(SnapshotError):
    """The source file changed while being read."""


def _fstat(handle: BinaryIO):
    return os.fstat(handle.fileno())


def _verify_stable(handle: BinaryIO, before, after) -> None:
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise SourceUnstable("source file changed during read")


class SnapshotStore:
    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        os.makedirs(os.path.join(self.root, "tmp"), exist_ok=True)

    def blob_rel_path(self, sha256: str) -> str:
        return "%s%s%s" % (sha256[:2], os.sep, sha256)

    def blob_abs_path(self, sha256: str) -> str:
        return os.path.join(self.root, self.blob_rel_path(sha256))

    def blob_state(self, sha256: str, expected_bytes: Optional[int]) -> Optional[bool]:
        """None when absent; True when present and consistent; False on corruption."""
        path = self.blob_abs_path(sha256)
        if not os.path.isfile(path):
            return None
        size = os.path.getsize(path)
        if expected_bytes is not None and size != expected_bytes:
            return False
        return True

    def cleanup_tmp(self, max_age_seconds: float = 3600.0) -> int:
        """Remove leftover temp files from interrupted runs (own tmp dir only)."""
        tmp_dir = os.path.join(self.root, "tmp")
        removed = 0
        cutoff = time.time() - max_age_seconds
        try:
            names = os.listdir(tmp_dir)
        except OSError:
            return 0
        for name in names:
            path = os.path.join(tmp_dir, name)
            try:
                if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                    os.unlink(path)
                    removed += 1
            except OSError:
                continue
        return removed

    def ingest_stream(self, handle: BinaryIO) -> Tuple[str, int]:
        """Stream *handle* into a temp file while hashing it.

        Returns (temp_path, sha256, size). Caller must unlink the temp file
        unless :meth:`promote` consumed it.
        """
        digest = hashlib.sha256()
        total = 0
        fd, temp_path = tempfile.mkstemp(prefix="snap-", dir=os.path.join(self.root, "tmp"))
        try:
            with os.fdopen(fd, "wb") as out:
                handle.seek(0)
                while True:
                    block = handle.read(CHUNK)
                    if not block:
                        break
                    digest.update(block)
                    out.write(block)
                    total += len(block)
                out.flush()
                os.fsync(out.fileno())
        except Exception:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise
        return temp_path, digest.hexdigest(), total

    def verify_temp(self, temp_path: str, expected_sha256: str, expected_size: int) -> None:
        digest = hashlib.sha256()
        total = 0
        with open(temp_path, "rb") as handle:
            while True:
                block = handle.read(CHUNK)
                if not block:
                    break
                digest.update(block)
                total += len(block)
        if digest.hexdigest() != expected_sha256 or total != expected_size:
            raise IntegrityError("temp snapshot failed re-verification")

    def promote(self, temp_path: str, sha256: str, size: int) -> str:
        """Atomically place a verified temp file at its content-addressed path.

        R04: placement uses hard-link creation, which fails atomically when
        another writer already created the blob - os.replace would silently
        clobber a concurrent/differing file. The existing blob is never
        modified either way.
        """
        final = self.blob_abs_path(sha256)
        os.makedirs(os.path.dirname(final), exist_ok=True)
        if os.path.exists(final):
            # Content-addressed path already present: dedup. A size disagreement
            # means the store is corrupted; never overwrite the existing blob.
            if os.path.getsize(final) != size:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
                raise IntegrityError("existing blob %s has unexpected size" % sha256)
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            return final
        try:
            os.link(temp_path, final)  # atomic create; fails if final exists
        except FileExistsError:
            if os.path.getsize(final) != size:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
                raise IntegrityError("existing blob %s has unexpected size" % sha256)
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            return final
        except OSError:
            # filesystems without hard links: guarded rename fallback
            os.rename(temp_path, final)
        finally:
            try:
                os.unlink(temp_path)  # no-op when already moved/removed
            except OSError:
                pass
        return final

    def verify_blob(self, store_path: str, expected_sha256: str,
                    expected_bytes: int) -> Optional[bool]:
        """Hash the stored bytes against the recorded identity.

        None when the blob is absent, False on any mismatch, True on match.
        """
        path = os.path.join(self.root, *store_path.split("/"))
        if not os.path.isfile(path):
            return None
        if os.path.getsize(path) != expected_bytes:
            return False
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            while True:
                block = handle.read(CHUNK)
                if not block:
                    break
                digest.update(block)
        return digest.hexdigest() == expected_sha256


def snapshot_version(store: KnowledgeStore, blobs: SnapshotStore,
                     open_source: BinaryIO, source: str, doc_id: str, version_id: str,
                     expected_sha256: Optional[str], expected_bytes: Optional[int]) -> str:
    """Snapshot one version from an already-open source descriptor.

    The descriptor is hashed and copied in one pass, the copy is re-hashed
    from disk, and only then is it promoted and bound to the version.
    """
    before = _fstat(open_source)
    temp_path, computed_sha, copied_bytes = blobs.ingest_stream(open_source)
    try:
        after = _fstat(open_source)
        _verify_stable(open_source, before, after)
        if expected_bytes is not None and copied_bytes != expected_bytes:
            raise SourceConflict(
                "source size %d != catalog bytes %s" % (copied_bytes, expected_bytes))
        if expected_sha256 and computed_sha != expected_sha256:
            raise SourceConflict("source hash mismatch for version identity")
        rel = blobs.blob_rel_path(computed_sha).replace("\\", "/")
        state = blobs.verify_blob(rel, computed_sha, copied_bytes)
        if state is False:
            raise IntegrityError("blob store corruption at %s" % computed_sha)
        if state is None:
            blobs.verify_temp(temp_path, computed_sha, copied_bytes)
            blobs.promote(temp_path, computed_sha, copied_bytes)
        else:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise
    now = utc_now()
    rel = blobs.blob_rel_path(computed_sha).replace("\\", "/")
    store.record_blob(computed_sha, copied_bytes, rel, now)
    store.record_snapshot(source, doc_id, version_id, computed_sha, copied_bytes, rel, now)
    return computed_sha
