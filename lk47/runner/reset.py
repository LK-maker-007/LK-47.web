from __future__ import annotations

import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class Container:
    name: str
    image: str
    ports: tuple[tuple[int, int], ...]
    ready_url: str


# the verified images expose the site on 80 and their control API on 8877
CONTAINERS = {
    "shopping_admin": Container(
        "webarena-verified-shopping_admin",
        "am1n3e/webarena-verified-shopping_admin:0.1.0",
        ((7780, 80), (7781, 8877)),
        "http://localhost:7780/admin",
    ),
    "shopping": Container(
        "webarena-verified-shopping",
        "am1n3e/webarena-verified-shopping:0.1.0",
        ((7770, 80), (7771, 8877)),
        "http://localhost:7770/",
    ),
    "reddit": Container(
        "webarena-verified-reddit",
        "am1n3e/webarena-verified-reddit:0.1.0",
        ((9999, 80), (9998, 8877)),
        "http://localhost:9999/",
    ),
    "gitlab": Container(
        "webarena-verified-gitlab",
        "am1n3e/webarena-verified-gitlab:0.1.0",
        # gitlab's nginx listens on the external URL's port inside the container
        ((8023, 8023), (8022, 8877)),
        "http://localhost:8023/users/sign_in",
    ),
}


def recreate(site: str, timeout: float = 600.0) -> float:
    spec = CONTAINERS[site]
    subprocess.run(["docker", "rm", "-f", spec.name], check=False, capture_output=True)
    command = ["docker", "run", "-d", "--name", spec.name]
    for host, inner in spec.ports:
        command += ["-p", f"{host}:{inner}"]
    subprocess.run([*command, spec.image], check=True, capture_output=True)
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        try:
            with urllib.request.urlopen(spec.ready_url, timeout=10) as response:
                if response.status == 200:
                    return time.monotonic() - started
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            pass
        time.sleep(5)
    raise TimeoutError(f"{spec.name} did not answer on {spec.ready_url} within {timeout:.0f} s")
