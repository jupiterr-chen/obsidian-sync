"""Bounded dashboard ingestion; never starts knowledge/OCR workers.

The existing Ingestor owns the cross-process ingest/render lock. This
controller coalesces browser clicks and returns immediately while that
same first-layer operation runs. Durable results remain in ingest_runs.
"""

import math
import threading
import time
import uuid

from .ingest import Ingestor
from .runtime import utc_now


class ManualIngest:
    COOLDOWN_SECONDS = 30

    def __init__(self, config):
        self.config = config
        self._lock = threading.Lock()
        self._thread = None
        self._last_requested = None
        self._state = {"state": "idle", "message": "可立即检查已下载资料并更新卡片。"}

    def _snapshot(self):
        result = dict(self._state)
        result["retry_after_seconds"] = max(0, math.ceil(
            self.COOLDOWN_SECONDS - (time.monotonic() - self._last_requested)
        )) if self._last_requested is not None else 0
        return result

    def snapshot(self):
        with self._lock:
            return self._snapshot()

    def request(self):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return 202, self._snapshot()
            if self._snapshot()["retry_after_seconds"]:
                return 429, self._snapshot()
            self._last_requested = time.monotonic()
            self._state = {
                "state": "running", "request_id": "ingest-" + uuid.uuid4().hex[:16],
                "started_at": utc_now(),
                "message": "正在检查来源索引并更新资料卡片；正文解析仍按原队列执行。",
            }
            self._thread = threading.Thread(target=self._run, daemon=True,
                                            name="manual-library-ingest")
            try:
                self._thread.start()
            except RuntimeError:
                self._state.update(state="failed", finished_at=utc_now(),
                                   message="任务启动失败，请稍后重试。")
                return 503, self._snapshot()
            return 202, self._snapshot()

    def _run(self):
        ingestor = None
        try:
            ingestor = Ingestor(self.config)
            result = ingestor.run()
            if result.get("skipped"):
                outcome = {"state": "busy", "message": "已有资料接入任务正在运行，本次未重复启动。"}
            elif result.get("ok"):
                changes = sum(int(s.get("changes", 0)) for s in result.get("sources", {}).values())
                outcome = {
                    "state": "succeeded", "changes": changes,
                    "message": "资料检查完成，发现 %d 项变化。卡片已更新；Windows 同步进度请看下方 Syncthing 状态。" % changes,
                }
            else:
                outcome = {"state": "failed", "message": "资料接入或卡片生成存在失败，请查看来源状态及最近入库记录。"}
        except Exception:
            # Never return raw exceptions, paths or source contents to browsers.
            outcome = {"state": "failed", "message": "资料接入失败，请查看服务日志及最近入库记录。"}
        finally:
            if ingestor is not None:
                try:
                    ingestor.close()
                except Exception:
                    pass
        with self._lock:
            self._state.update(outcome, finished_at=utc_now())
