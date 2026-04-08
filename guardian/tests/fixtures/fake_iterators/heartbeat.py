"""Fake heartbeat iterator."""


class HeartbeatIterator:
    name = "heartbeat"
    interval_sec = 60

    def run(self, ctx):
        return {"status": "ok"}
