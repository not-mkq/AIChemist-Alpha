class RunFailure(Exception):
    """Raised to indicate a tool/meta run failed and should trigger rollback."""

    def __init__(self, payload):
        super().__init__(str(payload))
        self.payload = payload
