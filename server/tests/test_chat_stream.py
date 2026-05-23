import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app


def test_chat_stream_returns_sse_events():
    client = TestClient(app)
    response = client.post("/api/chat/stream", json={"message": "推荐油皮洗面奶"})

    assert response.status_code == 200
    body = response.text
    assert "event: delta" in body
    assert "event: product_cards" in body
    assert "event: done" in body
