"""操作审计（开发桩）。"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def write_audit(*args: Any, **kwargs: Any) -> None:
    logger.info("ops_audit(dev-stub): args=%s kwargs=%s", args, kwargs)
