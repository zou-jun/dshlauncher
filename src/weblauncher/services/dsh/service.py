"""dsh 服务门面：兼容旧 API，内部使用通用 Supervisor。"""

from __future__ import annotations

from ...paths import Paths
from ...state import State
from ...supervisor import Supervisor
from . import parse
from .adapter import WEB_PROFILE, DshAdapter
from .settings import Settings

is_dsh_cmdline = parse.is_dsh_cmdline
parse_url = parse.parse_url
url_port = parse.url_port
startup_failure = parse.startup_failure

__all__ = [
    "WEB_PROFILE",
    "Service",
    "State",
    "is_dsh_cmdline",
    "parse_url",
    "startup_failure",
    "url_port",
]


class Service(Supervisor):
    """绑定 dsh 适配器的 Supervisor；构造签名保持旧版可用。"""

    def __init__(
        self,
        settings: Settings,
        *,
        paths_: Paths | None = None,
        backend: object | None = None,
        other_ports=None,  # noqa: ANN001 - Callable[[], set[int]]
    ) -> None:
        resolved = paths_ or Paths.current()
        super().__init__(
            DshAdapter(settings, resolved),
            paths_=resolved,
            backend=backend,
            other_ports=other_ports,
        )
