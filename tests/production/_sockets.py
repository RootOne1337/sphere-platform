class FakeSocket:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.sent = []
        self.closed = []

    async def accept(self):
        pass

    async def close(self, code=1000, reason=""):
        self.closed.append((code, reason))

    async def send_json(self, data):
        self.sent.append(data)

    async def send_bytes(self, data):
        self.sent.append(data)

    async def receive_json(self):
        from starlette.websockets import WebSocketDisconnect

        try:
            return next(self.messages)
        except StopIteration:
            raise WebSocketDisconnect()

    async def receive(self):
        from starlette.websockets import WebSocketDisconnect

        raise WebSocketDisconnect()
