"""控制台路由表：方法 + 路径模式 -> handler 方法名。"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Route:
    pattern: re.Pattern[str]
    method: str
    handler: str


def _route(pattern: str, method: str, handler: str) -> Route:
    return Route(re.compile(pattern), method, handler)


ROUTES: tuple[Route, ...] = (
    _route(r"/", "GET", "_index"),
    _route(r"/index\.html", "GET", "_index"),
    _route(r"/app\.js", "GET", "_app_js"),
    _route(r"/core\.js", "GET", "_core_js"),
    _route(r"/pages/(?P<name>.+\.js)", "GET", "_page_js"),
    _route(r"/styles\.css", "GET", "_styles"),
    _route(r"/favicon\.ico", "GET", "_favicon"),
    _route(r"/api/meta", "GET", "_meta_route"),
    _route(r"/api/services", "GET", "_services"),
    _route(r"/api/services/(?P<service>[^/]+)/logs", "GET", "_service_logs"),
    _route(r"/api/services/(?P<service>[^/]+)", "GET", "_service"),
    _route(r"/api/jobs", "GET", "_jobs"),
    _route(r"/api/jobs/(?P<job_id>[^/]+)", "GET", "_job"),
    _route(r"/api/doctor", "GET", "_doctor_get"),
    _route(r"/api/config", "GET", "_config_get"),
    _route(r"/api/jupyter/kernels", "GET", "_kernels"),
    _route(r"/api/jupyter/kernels/(?P<name>[^/]+)", "GET", "_kernel"),
    _route(r"/api/jupyter/workdirs", "GET", "_workdirs"),
    _route(r"/api/updates", "GET", "_updates_get"),
    _route(r"/api/upgrade-job", "GET", "_upgrade_job"),
    _route(r"/api/fs", "GET", "_fs"),
    _route(r"/api/about", "GET", "_about"),
    _route(r"/api/actions", "POST", "_actions_post"),
    _route(r"/api/agent/quit", "POST", "_quit_post"),
    _route(r"/api/doctor", "POST", "_doctor_post"),
    _route(r"/api/updates", "POST", "_updates_post"),
    _route(r"/api/config", "POST", "_config_post"),
    _route(r"/api/config/value", "PUT", "_config_value_put"),
    _route(r"/api/config/value", "POST", "_config_value_put"),
    _route(r"/api/config/value", "DELETE", "_config_value_delete"),
    _route(r"/api/jupyter/kernels", "POST", "_kernels_post"),
    _route(r"/api/jupyter/kernels/(?P<name>[^/]+)/use", "POST", "_kernel_use"),
    _route(r"/api/jupyter/kernels/(?P<name>[^/]+)", "PATCH", "_kernel_patch"),
    _route(r"/api/jupyter/kernels/(?P<name>[^/]+)", "DELETE", "_kernel_delete"),
    _route(r"/api/jupyter/workdirs", "POST", "_workdirs_post"),
    _route(r"/api/upgrades", "POST", "_upgrades_post"),
    _route(r"/api/install", "POST", "_install_post"),
    _route(r"/api/uninstall", "POST", "_uninstall_post"),
)


__all__ = ["ROUTES", "Route"]
