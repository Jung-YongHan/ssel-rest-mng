#!/usr/bin/env python
"""OCR 엔드포인트 진단 (smoke test).

    cd backend
    python scripts/ocr_smoke.py --no-image          # 연결만 확인 (텍스트 프롬프트)
    python scripts/ocr_smoke.py path/to/receipt.jpg # 실제 영수증으로 확인

**이 스크립트가 연구실 Qwen 서버의 비전(이미지) 지원 여부를 판별하는 관문이다.**
서버가 이미지 입력을 거부하면 텍스트 전용 배포라는 뜻이고, 그때는
`.env` 의 `OCR_PROVIDER` 를 `qwen_text` 로 바꿔야 한다.

종료 코드
    0  파싱 성공 (최소 한 개 필드를 읽어냈다)
    1  실패 — 마지막에 다음에 뭘 시도할지 한국어로 안내한다
    2  사용법 오류

⚠️ 진단 출력에서 엔드포인트 주소(호스트)는 마스킹된다. 내부 IP 를 로그·이슈에
   붙여넣는 사고를 막기 위한 것이므로, 출력 전체를 공개 채널에 올려도 안전하다.
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

# ── 출력 인코딩 보정 ────────────────────────────────────────────────
# Windows 에서 stdout 이 파이프/리다이렉트되면 인코딩이 로케일(cp949)로 잡혀
# 한국어는 깨지고 ✓ ⚠️ 같은 기호는 UnicodeEncodeError 로 스크립트를 죽인다.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError, OSError):  # pragma: no cover - 환경 의존
        pass

# ── import 경로 보정: `python scripts/ocr_smoke.py` 로 실행 가능하게 ──
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings  # noqa: E402

RAW_PREVIEW_CHARS = 1200
PARSED_FIELDS = (
    "store_name",
    "business_number",
    "address",
    "phone",
    "total_amount",
    "paid_at",
)


# ──────────────────────────────────────────────────────────────────
#  마스킹 / 출력 헬퍼
# ──────────────────────────────────────────────────────────────────
def mask_url(url: str) -> str:
    """스킴·포트·경로는 남기고 호스트만 가린다 (내부 IP 유출 방지)."""
    if not url:
        return "(비어 있음)"
    parts = urlsplit(url if "//" in url else f"//{url}")
    host = parts.hostname or ""
    scheme = parts.scheme or "http"

    if host in ("localhost", "127.0.0.1", "::1"):
        masked = host  # 비밀이 아니므로 그대로 보여준다
    elif re.fullmatch(r"[0-9.]+", host):
        masked = "***.***.***.***"  # IPv4 는 통째로 가린다
    elif ":" in host:
        masked = "[***:***]"  # IPv6
    elif len(host) > 2:
        masked = f"{host[0]}***{host[-1]}"  # 호스트명은 양끝만
    else:
        masked = "***"

    port = f":{parts.port}" if parts.port else ""
    return f"{scheme}://{masked}{port}{parts.path}"


def hr(title: str = "") -> None:
    if title:
        print(f"\n── {title} " + "─" * max(0, 56 - len(title)))
    else:
        print("─" * 62)


def truncate(text: str | None, limit: int = RAW_PREVIEW_CHARS) -> str:
    if not text:
        return "(없음)"
    text = str(text)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n… (총 {len(text):,}자 중 앞 {limit:,}자만 표시)"


# ──────────────────────────────────────────────────────────────────
#  1) 설정 출력
# ──────────────────────────────────────────────────────────────────
def print_config() -> None:
    hr("설정 (.env)")
    key = settings.ocr_api_key
    print(f"  OCR_PROVIDER        : {settings.ocr_provider}")
    print(f"  OCR_BASE_URL        : {mask_url(settings.ocr_base_url)}   ← 호스트 마스킹됨")
    print(f"  OCR_MODEL           : {settings.ocr_model or '(비어 있음)'}")
    print(f"  OCR_API_KEY         : {f'설정됨 ({len(key)}자)' if key else '(비어 있음)'}")
    print(f"  OCR_TIMEOUT         : {settings.ocr_timeout}초")
    print(f"  OCR_MAX_IMAGE_PX    : {settings.ocr_max_image_px}px")
    print(f"  OCR_USE_GUIDED_JSON : {settings.ocr_use_guided_json}")
    print(f"  → ocr_enabled       : {settings.ocr_enabled}")

    if not settings.ocr_base_url:
        print("\n  ⚠️  OCR_BASE_URL 이 비어 있어 OCR 이 자동 비활성 상태입니다.")
        print("      .env 에 OpenAI 호환 베이스 URL 을 적으세요. 예: http://<주소>:<포트>/v1")
    if settings.ocr_provider == "disabled":
        print("\n  ⚠️  OCR_PROVIDER=disabled 입니다. 앱은 수동 입력으로만 동작합니다.")


# ──────────────────────────────────────────────────────────────────
#  2) 도달 가능성
# ──────────────────────────────────────────────────────────────────
def check_reachable() -> bool:
    """GET {base}/models 로 확인하고, 실패하면 TCP 연결만이라도 확인."""
    hr("엔드포인트 도달 확인")
    base = settings.ocr_base_url.rstrip("/")
    if not base:
        print("  ✗ OCR_BASE_URL 이 없어 확인을 건너뜁니다.")
        return False

    try:
        import httpx
    except ImportError:
        print("  ✗ httpx 가 설치되지 않았습니다: pip install -r requirements.txt")
        return False

    headers = {}
    if settings.ocr_api_key:
        headers["Authorization"] = f"Bearer {settings.ocr_api_key}"

    url = f"{base}/models"
    print(f"  GET {mask_url(url)}")
    try:
        started = time.perf_counter()
        resp = httpx.get(url, headers=headers, timeout=10.0)
        took = int((time.perf_counter() - started) * 1000)
        print(f"  → HTTP {resp.status_code} ({took}ms)")
        if resp.status_code == 200:
            try:
                names = [m.get("id") for m in resp.json().get("data", [])]
            except Exception:
                names = []
            if names:
                print(f"  ✓ 서버가 보고한 모델: {', '.join(str(n) for n in names[:10])}")
                if settings.ocr_model and settings.ocr_model not in names:
                    print(
                        f"  ⚠️  OCR_MODEL='{settings.ocr_model}' 이 목록에 없습니다. "
                        "이름이 정확한지 확인하세요."
                    )
            else:
                print("  ✓ 응답 성공 (모델 목록은 비어 있음)")
            return True
        if resp.status_code in (401, 403):
            print("  ⚠️  인증 거부. OCR_API_KEY 를 확인하세요.")
            return True  # 서버 자체에는 도달했다
        print(f"  ⚠️  /models 는 실패했지만 서버에는 도달했습니다: {truncate(resp.text, 200)}")
        return True
    except Exception as exc:
        print(f"  ✗ HTTP 실패: {type(exc).__name__}: {exc}")

    # TCP 만이라도 확인
    parts = urlsplit(base if "//" in base else f"//{base}")
    host, port = parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)
    if host:
        try:
            with socket.create_connection((host, port), timeout=5):
                print(f"  ⚠️  TCP {mask_url(base)} 포트 {port} 는 열려 있습니다 (HTTP 계층 문제).")
                return True
        except Exception as exc:
            print(f"  ✗ TCP 연결도 실패: {type(exc).__name__}: {exc}")
    return False


# ──────────────────────────────────────────────────────────────────
#  3-a) --no-image : 텍스트 전용 연결 확인
# ──────────────────────────────────────────────────────────────────
def run_text_probe() -> tuple[bool, str | None]:
    """이미지 없이 chat/completions 를 한 번 호출한다. (성공?, 에러문자열)"""
    hr("텍스트 전용 프롬프트 테스트 (--no-image)")
    base = settings.ocr_base_url.rstrip("/")
    if not base:
        return False, "OCR_BASE_URL 이 비어 있습니다."

    import httpx

    headers = {"Content-Type": "application/json"}
    if settings.ocr_api_key:
        headers["Authorization"] = f"Bearer {settings.ocr_api_key}"

    payload = {
        "model": settings.ocr_model,
        "messages": [
            {
                "role": "user",
                "content": 'JSON 만 출력하세요: {"ok": true}',
            }
        ],
        "temperature": 0,
        "max_tokens": 64,
    }

    url = f"{base}/chat/completions"
    print(f"  POST {mask_url(url)}  (model={settings.ocr_model})")
    started = time.perf_counter()
    try:
        resp = httpx.post(
            url, headers=headers, json=payload, timeout=float(settings.ocr_timeout)
        )
    except Exception as exc:
        took = int((time.perf_counter() - started) * 1000)
        print(f"  ✗ 요청 실패 ({took}ms): {type(exc).__name__}: {exc}")
        return False, f"{type(exc).__name__}: {exc}"

    took = int((time.perf_counter() - started) * 1000)
    print(f"  → HTTP {resp.status_code} ({took}ms)")

    if resp.status_code != 200:
        print(f"  ✗ 본문: {truncate(resp.text, 600)}")
        return False, f"HTTP {resp.status_code}: {resp.text}"

    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        print(f"  ✗ 응답 구조가 OpenAI 호환이 아닙니다: {exc}")
        print(f"    원문: {truncate(resp.text, 600)}")
        return False, f"응답 파싱 실패: {exc}"

    print("  ✓ 모델 응답:")
    print(f"    {truncate(content, 400)}")
    print("\n  ✓ 텍스트 경로는 정상입니다. 이제 이미지로도 확인하세요:")
    print("      python scripts/ocr_smoke.py <영수증 이미지 경로>")
    return True, None


# ──────────────────────────────────────────────────────────────────
#  3-b) 이미지로 실제 provider.extract() 호출
# ──────────────────────────────────────────────────────────────────
def run_image_probe(image_path: Path) -> tuple[bool, str | None]:
    hr("영수증 OCR 테스트")
    print(f"  이미지: {image_path}  ({image_path.stat().st_size:,} bytes)")

    try:
        from app.services.ocr import get_ocr_provider
    except ImportError as exc:
        print(f"  ✗ app/services/ocr.py 를 불러올 수 없습니다: {exc}")
        return False, f"ImportError: {exc}"

    try:
        provider = get_ocr_provider()
    except Exception as exc:
        print(f"  ✗ get_ocr_provider() 실패: {type(exc).__name__}: {exc}")
        return False, f"{type(exc).__name__}: {exc}"

    print(f"  provider: {type(provider).__name__}")

    started = time.perf_counter()
    try:
        result = provider.extract(image_path)
    except Exception as exc:
        # 계약상 provider 는 모든 예외를 삼켜야 한다. 여기 오면 그 자체가 버그.
        took = int((time.perf_counter() - started) * 1000)
        print(f"  ✗ extract() 가 예외를 던졌습니다 ({took}ms): {type(exc).__name__}: {exc}")
        print("    (OcrProvider 는 예외를 error 로 변환해야 합니다 — CONTRACT.md §3)")
        return False, f"{type(exc).__name__}: {exc}"

    fallback_ms = int((time.perf_counter() - started) * 1000)
    parsed = getattr(result, "parsed", None) or {}
    raw = getattr(result, "raw", None)
    error = getattr(result, "error", None)
    elapsed = getattr(result, "elapsed_ms", None) or fallback_ms

    print(f"  소요 시간: {elapsed:,} ms")
    print(f"  error    : {error or '(없음)'}")

    hr("파싱 결과 (ParsedReceipt)")
    printable = {k: parsed.get(k) if hasattr(parsed, "get") else None for k in PARSED_FIELDS}
    print(json.dumps(printable, ensure_ascii=False, indent=2, default=str))

    extra = (
        [k for k in parsed if k not in PARSED_FIELDS] if hasattr(parsed, "__iter__") else []
    )
    if extra:
        print(f"  ℹ️  계약에 없는 추가 키: {', '.join(map(str, extra))}")

    hr("모델 원문 (raw)")
    print(truncate(raw))

    filled = [k for k, v in printable.items() if v not in (None, "")]
    hr()
    if error:
        print(f"  ✗ 실패: {error}")
        return False, str(error)
    if not filled:
        print("  ✗ 에러는 없지만 읽어낸 필드가 하나도 없습니다.")
        if settings.ocr_provider == "disabled":
            return False, "OCR_PROVIDER=disabled 라서 항상 빈 값을 반환합니다."
        return False, "빈 결과 (모든 필드 None)"

    print(f"  ✓ 성공 — 읽어낸 필드 {len(filled)}/{len(PARSED_FIELDS)}: {', '.join(filled)}")
    missing = [k for k in PARSED_FIELDS if k not in filled]
    if missing:
        print(f"    (못 읽은 필드: {', '.join(missing)} — 사용자가 화면에서 보완할 수 있습니다)")
    return True, None


# ──────────────────────────────────────────────────────────────────
#  4) 한국어 진단
# ──────────────────────────────────────────────────────────────────
_IMAGE_REJECT_TOKENS = (
    "image_url",
    "image url",
    "multi_modal",
    "multimodal",
    "multi-modal",
    "vision",
    "mm_processor",
    "mm_data",
    "not a multimodal",
    "does not support image",
    "image input",
    "image is not supported",
    "unsupported content",
    "content must be a string",
    "content must be str",
    "invalid_type",
    "expected string",
    "no image",
)
_TIMEOUT_TOKENS = ("timeout", "timed out", "readtimeout", "connecttimeout", "deadline")
_CONN_TOKENS = (
    "connectionerror",
    "connecterror",
    "refused",
    "getaddrinfo",
    "name or service not known",
    "no route to host",
    "unreachable",
    "ssl",
    "certificate",
)
_AUTH_TOKENS = ("401", "403", "unauthorized", "forbidden", "api key", "api_key", "invalid key")
_MODEL_TOKENS = ("does not exist", "model not found", "unknown model", "no such model", "404")
_PARSE_TOKENS = ("json", "파싱", "parse", "decode")


def diagnose(error: str | None, *, used_image: bool) -> None:
    hr("진단 및 다음 조치")
    blob = (error or "").lower()

    def hit(tokens: tuple[str, ...]) -> bool:
        return any(t in blob for t in tokens)

    if not settings.ocr_base_url:
        print("  ▸ OCR_BASE_URL 이 비어 있습니다. .env 에 OpenAI 호환 주소를 적으세요.")
        print("      OCR_BASE_URL=http://<서버주소>:<포트>/v1")
        print("    OCR 없이 쓰려면 OCR_PROVIDER=disabled — 앱은 수동 입력으로 전부 동작합니다.")
        return

    if settings.ocr_provider == "disabled":
        print("  ▸ OCR_PROVIDER=disabled 입니다. 실제로 테스트하려면 qwen_vl 로 바꾸세요.")
        return

    if used_image and hit(_IMAGE_REJECT_TOKENS):
        print("  ▸ ⚠️  서버가 **이미지 입력을 거부**했습니다.")
        print("       이 배포는 비전(vision) 을 지원하지 않는 **텍스트 전용** 으로 보입니다.")
        print()
        print("    조치: .env 를 다음과 같이 바꾸세요")
        print("        OCR_PROVIDER=qwen_text")
        print()
        print("    qwen_text 는 이미지에서 텍스트를 먼저 뽑아(로컬 OCR) 모델에게 구조화만")
        print("    맡기는 폴백 경로입니다. 로컬 텍스트 추출기가 없으면 그것도 에러를 반환하므로,")
        print("    당장 쓰려면 OCR_PROVIDER=disabled 로 두고 수동 입력을 쓰는 편이 낫습니다.")
        print()
        print("    확인: python scripts/ocr_smoke.py --no-image  → 텍스트 경로가 살아 있는지")
        return

    if hit(_TIMEOUT_TOKENS):
        print("  ▸ 타임아웃입니다. 서버는 살아 있지만 추론이 오래 걸립니다.")
        print(f"      OCR_TIMEOUT={settings.ocr_timeout} → 300 으로 늘려보세요.")
        print(f"      OCR_MAX_IMAGE_PX={settings.ocr_max_image_px} → 1024 로 줄이면 빨라집니다.")
        return

    if hit(_CONN_TOKENS):
        print("  ▸ 서버에 도달하지 못했습니다. 순서대로 확인하세요.")
        print("      1) 주소/포트가 맞는지, 끝에 /v1 이 붙었는지")
        print("      2) 그 서버가 실제로 떠 있는지 (모델 서버 쪽 로그)")
        print("      3) 방화벽·VPN·사내망 접근 권한")
        print("      4) 컨테이너에서 실행 중이면 컨테이너 밖으로 나가는 경로가 열렸는지")
        return

    if hit(_AUTH_TOKENS):
        print("  ▸ 인증이 거부됐습니다. OCR_API_KEY 를 확인하세요.")
        print("      키를 요구하지 않는 서버라면 아예 비워두는 게 맞습니다.")
        return

    if hit(_MODEL_TOKENS):
        print("  ▸ 모델 이름이 서버에 없는 것 같습니다.")
        print(f"      OCR_MODEL={settings.ocr_model}")
        print("      위 '엔드포인트 도달 확인' 의 모델 목록과 정확히 일치시키세요.")
        return

    if hit(_PARSE_TOKENS):
        print("  ▸ 모델이 JSON 이 아닌 응답을 냈습니다 (설명 문장이 섞였을 가능성).")
        print("      OCR_USE_GUIDED_JSON=true  ← vLLM guided_json 지원 서버면 이걸로 강제")
        print("      위 '모델 원문' 을 보고 무엇을 뱉었는지 확인하세요.")
        return

    if error:
        print(f"  ▸ 분류되지 않은 오류입니다: {error}")
        print("      위 '모델 원문' 과 서버 로그를 함께 확인하세요.")
        print("      급하면 OCR_PROVIDER=disabled — 앱은 수동 입력으로 100% 동작합니다.")
        return

    print("  ▸ 에러는 없지만 결과가 비어 있습니다.")
    print("      · 사진이 흐리거나 잘렸는지 확인 (영수증 전체가 프레임에 들어와야 합니다)")
    print(f"      · OCR_MAX_IMAGE_PX={settings.ocr_max_image_px} → 2048 로 올리면 잔글씨 인식률이 오릅니다")
    print("      · OCR_USE_GUIDED_JSON=true 로 출력 형식을 강제해 보세요")


# ──────────────────────────────────────────────────────────────────
#  main
# ──────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ocr_smoke.py",
        description=(
            "OCR 엔드포인트 진단. 연구실 Qwen 서버가 비전(이미지) 입력을 "
            "지원하는지 판별합니다."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "예시:\n"
            "  python scripts/ocr_smoke.py --no-image            연결만 확인\n"
            "  python scripts/ocr_smoke.py ~/receipt.jpg         영수증으로 확인\n"
            "\n"
            "종료 코드: 0=파싱 성공 · 1=실패(한국어 진단 출력) · 2=사용법 오류\n"
            "출력의 엔드포인트 호스트는 마스킹되므로 그대로 공유해도 안전합니다.\n"
        ),
    )
    parser.add_argument(
        "image",
        nargs="?",
        help="영수증 이미지 경로 (--no-image 를 쓰면 생략 가능)",
    )
    parser.add_argument(
        "--no-image",
        action="store_true",
        help="이미지 없이 텍스트 프롬프트만 보내 연결을 확인합니다.",
    )
    args = parser.parse_args(argv)

    print("=" * 62)
    print(" OCR 엔드포인트 진단 (ocr_smoke)")
    print("=" * 62)

    if not args.image and not args.no_image:
        print("\n이미지 경로가 필요합니다. 연결만 확인하려면 --no-image 를 쓰세요.\n")
        parser.print_help()
        return 2

    print_config()
    reachable = check_reachable()

    if args.no_image:
        ok, error = run_text_probe()
        if not ok:
            diagnose(error, used_image=False)
        return 0 if ok else 1

    image_path = Path(args.image).expanduser()
    if not image_path.is_file():
        print(f"\n✗ 파일을 찾을 수 없습니다: {image_path}")
        return 2

    if not reachable:
        print("\n  ⚠️  엔드포인트에 도달하지 못했지만, 그래도 extract() 를 호출해 봅니다.")

    ok, error = run_image_probe(image_path)
    if not ok:
        diagnose(error, used_image=True)
    else:
        hr("결론")
        print("  ✓ 이 서버는 이미지 입력을 처리할 수 있습니다. OCR_PROVIDER=qwen_vl 로 두세요.")
    print("=" * 62)
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n중단했습니다.")
        raise SystemExit(130) from None
