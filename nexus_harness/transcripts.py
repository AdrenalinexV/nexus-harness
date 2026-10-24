"""Chat sessions on disk: close the app, open it, and the conversation is still there.

One JSON file per conversation, holding what the UI needs to repaint it (messages with roles and tool
calls) and nothing the model does not need. Written on every turn, so a crash costs at most the turn
in flight -- the alternative, an in-memory transcript, is the thing that makes a desktop chat feel
like a demo.

The directory is per project (`<root>/.nexus/harness/chat/`), so a conversation never appears in the
wrong repository, and the harness's own engine state stays out of the user's source tree.
"""
import json
import time
from pathlib import Path

PROTOCOL = "nexus.harness.chat/1"
CHAT_REL = Path(".nexus") / "harness" / "chat"
MAX_TITLE = 90


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _stamp():
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime())


class Transcripts:
    def __init__(self, root):
        self.root = Path(root)
        self.dir = self.root / CHAT_REL

    def ensure(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        return self

    def path(self, session_id):
        return self.dir / ("%s.json" % session_id)

    def new(self, title=""):
        self.ensure()
        session = {"protocol": PROTOCOL, "id": "chat-%s" % _stamp(), "title": str(title)[:MAX_TITLE],
                   "created_at": _now(), "updated_at": _now(), "messages": [], "turns": 0,
                   "exit": None}
        # Two sessions created in the same second must not overwrite each other.
        suffix = 1
        while self.path(session["id"]).exists():
            suffix += 1
            session["id"] = "chat-%s-%d" % (_stamp(), suffix)
        return self.save(session)

    def save(self, session):
        self.ensure()
        session["updated_at"] = _now()
        self.path(session["id"]).write_text(json.dumps(session, indent=2, ensure_ascii=False),
                                            encoding="utf-8")
        return session

    def load(self, session_id):
        try:
            data = json.loads(self.path(session_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) and data.get("protocol") == PROTOCOL else None

    def listing(self, limit=40):
        """Newest first, with just enough to draw a sidebar: id, title, turns, updated_at."""
        if not self.dir.is_dir():
            return []
        rows = []
        for path in self.dir.glob("chat-*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            rows.append({"id": data.get("id", path.stem), "title": data.get("title", ""),
                         "turns": data.get("turns", 0), "updated_at": data.get("updated_at", ""),
                         "exit": data.get("exit")})
        rows.sort(key=lambda row: row.get("updated_at") or "", reverse=True)
        return rows[:int(limit)]

    def delete(self, session_id):
        path = self.path(session_id)
        if not path.is_file():
            return False
        path.unlink()
        return True
