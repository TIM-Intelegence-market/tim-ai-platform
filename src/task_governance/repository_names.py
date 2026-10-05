"""One spelling per repository: case, URL and `.git` forms, and the transfer alias (see `legacy.TRANSFERRED_REPOSITORIES`)."""
from .legacy import TRANSFERRED_REPOSITORIES

PRODUCTION_REPOSITORY = 'tim-intelegence-market/tim-ai-platform'      # normalised; the pre-transfer name maps onto it


def normalize_repository(repo) -> str:
    text = str(repo).strip().lower().rstrip('/')
    for prefix in ('https://github.com/', 'http://github.com/', 'github.com/', 'git@github.com:'):
        if text.startswith(prefix):
            text = text[len(prefix):]
    text = text.removesuffix('.git').rstrip('/')
    return TRANSFERRED_REPOSITORIES.get(text, text)
