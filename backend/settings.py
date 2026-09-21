import json
import os
from pathlib import Path
import secrets


def load_keys(data_dir):
    path = Path(data_dir) / "access.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "w") as file:
            json.dump({"observer": secrets.token_urlsafe(32), "learner": secrets.token_urlsafe(32)}, file)
    with path.open() as file:
        return json.load(file)
