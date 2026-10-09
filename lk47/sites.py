import os

# the harness reads site roots from these variables; the agent reads the same ones so a run
# against a different host needs no code change
SITE_VARS = ("SHOPPING", "SHOPPING_ADMIN", "REDDIT", "GITLAB", "MAP", "WIKIPEDIA", "HOMEPAGE")


def site_url(name: str) -> str:
    return os.environ[name].rstrip("/")
