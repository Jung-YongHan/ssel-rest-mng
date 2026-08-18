"""정적 서빙 — 캐시 헤더와 정규 주소 리다이렉트.

`frontend/dist` 가 없는 환경(CI)에서도 돌아야 하므로, 임시 dist 를 만들어
`mount_frontend()` 를 **새 앱**에 붙여서 검증한다. 운영 앱(`app.main:app`)은
빌드 산출물이 있을 때만 같은 함수를 호출하므로 동작은 동일하다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import CACHE_IMMUTABLE, CACHE_REVALIDATE, CACHE_SHORT, mount_frontend

CANONICAL = "https://app.example.test"
# TestClient 가 기본으로 보내는 Host (= 정규 주소가 아닌 접속)
OTHER_HOST = "testserver"
# 브라우저 내비게이션 흉내
NAV_HEADERS = {"accept": "text/html,application/xhtml+xml", "sec-fetch-mode": "navigate"}


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    """vite 빌드 결과물의 최소 형태."""
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>앱</title>", encoding="utf-8")
    (root / "sw.js").write_text("// service worker", encoding="utf-8")
    (root / "manifest.webmanifest").write_text('{"name":"앱"}', encoding="utf-8")
    (root / "workbox-35e397ac.js").write_text("// workbox 런타임", encoding="utf-8")
    (root / "favicon.ico").write_bytes(b"\x00\x00\x01\x00")
    (root / "assets" / "index-AbCdEf12.js").write_text("export default 1", encoding="utf-8")
    return root


@pytest.fixture
def client(dist: Path) -> TestClient:
    app = FastAPI()
    mount_frontend(app, dist)
    # 리다이렉트는 각 테스트가 명시적으로 켠다 (기본값은 '끔')
    with TestClient(app, follow_redirects=False) as c:
        yield c


@pytest.fixture
def canonical(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(settings, "public_origin", CANONICAL)
    return CANONICAL


# ── 캐시 헤더 ───────────────────────────────────────────────────


def test_해시_에셋은_영구캐시(client: TestClient) -> None:
    resp = client.get("/assets/index-AbCdEf12.js")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == CACHE_IMMUTABLE


def test_해시가_붙은_workbox_런타임도_영구캐시(client: TestClient) -> None:
    resp = client.get("/workbox-35e397ac.js")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == CACHE_IMMUTABLE


@pytest.mark.parametrize("path", ["/", "/index.html", "/sw.js", "/manifest.webmanifest"])
def test_셸은_매번_재검증(client: TestClient, path: str) -> None:
    """옛 셸에 갇히면 앱이 통째로 뜨지 않으므로 절대 캐시하지 않는다."""
    resp = client.get(path)
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == CACHE_REVALIDATE


def test_SPA_라우트는_셸을_돌려주고_재검증(client: TestClient) -> None:
    resp = client.get("/restaurants/3")
    assert resp.status_code == 200
    assert "<!doctype html>" in resp.text
    assert resp.headers["cache-control"] == CACHE_REVALIDATE


def test_아이콘은_짧게만_캐시(client: TestClient) -> None:
    resp = client.get("/favicon.ico")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == CACHE_SHORT


# ── 기존 규약이 깨지지 않았는지 ────────────────────────────────


def test_없는_정적파일은_404(client: TestClient) -> None:
    """확장자가 있는데 파일이 없으면 index.html 을 200 으로 주지 않는다."""
    resp = client.get("/apple-touch-icon-precomposed.png")
    assert resp.status_code == 404


def test_api_경로는_404_JSON(client: TestClient) -> None:
    resp = client.get("/api/없는것")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Not Found"}


def test_HEAD_도_받는다(client: TestClient) -> None:
    resp = client.head("/sw.js")
    assert resp.status_code == 200


# ── 정규 주소 리다이렉트 ────────────────────────────────────────


def test_다른_Host_의_화면요청은_정규주소로(client: TestClient, canonical: str) -> None:
    resp = client.get("/ledger", params={"q": "국수"}, headers=NAV_HEADERS)
    assert resp.status_code == 307
    assert resp.headers["location"] == f"{canonical}/ledger?q=%EA%B5%AD%EC%88%98"


def test_루트_내비게이션도_정규주소로(client: TestClient, canonical: str) -> None:
    resp = client.get("/", headers=NAV_HEADERS)
    assert resp.status_code == 307
    assert resp.headers["location"] == f"{canonical}/"


def test_XHR_과_정적파일은_리다이렉트하지_않는다(client: TestClient, canonical: str) -> None:
    """크로스오리진으로 돌리면 CORS 로 조용히 실패하고 프리캐시도 깨진다."""
    assert client.get("/sw.js", headers={"accept": "*/*"}).status_code == 200
    assert client.get("/assets/index-AbCdEf12.js", headers={"accept": "*/*"}).status_code == 200


def test_정규_Host_로_들어오면_그대로_서빙(client: TestClient, canonical: str) -> None:
    host = canonical.removeprefix("https://")
    resp = client.get("/", headers={**NAV_HEADERS, "host": host})
    assert resp.status_code == 200


def test_로컬호스트는_예외(client: TestClient, canonical: str) -> None:
    """서버에서 직접 확인할 때 방해하지 않는다."""
    resp = client.get("/", headers={**NAV_HEADERS, "host": "localhost:8000"})
    assert resp.status_code == 200


def test_PUBLIC_ORIGIN_이_비면_리다이렉트하지_않는다(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "public_origin", "")
    assert client.get("/", headers=NAV_HEADERS).status_code == 200


def test_형식이_틀린_PUBLIC_ORIGIN_은_무시(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """스킴이 없으면 어디로 보낼지 알 수 없다 — 서비스를 죽이지 말고 그냥 서빙한다."""
    monkeypatch.setattr(settings, "public_origin", "app.example.test")
    assert client.get("/", headers=NAV_HEADERS).status_code == 200
