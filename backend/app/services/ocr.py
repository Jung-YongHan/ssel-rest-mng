"""영수증 OCR — CONTRACT.md §3.

핵심 원칙: **절대 예외를 던지지 않는다.** 모든 실패는 `OcrResult.error` 로 바꾼다.
OCR 이 앱을 죽이면 안 되고, 실패해도 사용자는 수동 입력으로 계속 진행해야 한다.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import httpx
from dateutil import parser as date_parser
from PIL import Image, ImageOps

from app.core.config import settings
from app.core.timeutil import to_utc_naive

log = logging.getLogger("ssel.ocr")

PARSED_KEYS = (
    "store_name",
    "business_number",
    "address",
    "phone",
    "total_amount",
    "paid_at",
)


def empty_parsed() -> dict[str, Any]:
    return dict.fromkeys(PARSED_KEYS, None)


@dataclass
class OcrResult:
    parsed: dict[str, Any] = field(default_factory=empty_parsed)
    raw: str | None = None
    elapsed_ms: int = 0
    error: str | None = None  # None 이면 성공


@runtime_checkable
class OcrProvider(Protocol):
    def extract(self, image_path: Path) -> OcrResult: ...


# ── 프롬프트 ───────────────────────────────────────────────────────

PROMPT = """당신은 한국 음식점 영수증(연구실 선결제 영수증) 이미지에서 정보를 추출하는 도우미입니다.

아래 키를 가진 JSON 객체 **하나만** 출력하세요. 설명, 코드펜스(```), 그 외 어떤 텍스트도 쓰지 마세요.

{
  "store_name": "상호명 (예: 한밭식당)",
  "business_number": "사업자등록번호 숫자 10자리 (하이픈 없이)",
  "address": "사업장 주소",
  "phone": "전화번호",
  "total_amount": 합계금액 정수,
  "paid_at": "결제일시 (YYYY-MM-DD HH:MM, 시간이 안 보이면 YYYY-MM-DD)"
}

규칙:
- total_amount 는 영수증의 **합계금액(부가세 포함 총액)** 입니다.
  공급가액·부가세(세액)·과세물품가액·받은금액·거스름돈·할인금액이 아닙니다.
  '합계', '총액', '결제금액', '승인금액' 항목의 값을 쓰세요.
- 금액은 숫자만 씁니다. "12,000원" → 12000, "₩12,000" → 12000.
- business_number 는 '사업자등록번호', '등록번호', '사업자번호' 옆의 숫자 10자리입니다.
  (전화번호나 승인번호, 카드번호와 혼동하지 마세요.)
- 흐릿하거나 잘려서 **읽을 수 없는 값은 반드시 null** 로 쓰세요. 절대 추측하거나 만들어내지 마세요.
- JSON 이외의 문자는 출력하지 마세요."""

# vLLM 등에서 구조화 출력을 강제할 때 쓰는 스키마 (OCR_USE_GUIDED_JSON=true)
GUIDED_JSON: dict[str, Any] = {
    "type": "object",
    "properties": {
        "store_name": {"type": ["string", "null"]},
        "business_number": {"type": ["string", "null"]},
        "address": {"type": ["string", "null"]},
        "phone": {"type": ["string", "null"]},
        "total_amount": {"type": ["integer", "null"]},
        "paid_at": {"type": ["string", "null"]},
    },
    "required": list(PARSED_KEYS),
    "additionalProperties": False,
}


def _add_guided_json(payload: dict[str, Any]) -> None:
    """구조화 출력(JSON 스키마 강제)을 요청 본문에 넣는다.

    ⚠️ `extra_body` 로 감싸면 안 된다. 그것은 **OpenAI Python SDK** 가 최상위로
    펼쳐주는 규약이고, 여기서는 httpx 로 본문을 직접 만들기 때문에 서버가
    `extra_body` 키를 그냥 무시한다(= 조용히 효과 없음).

    서버 구현이 갈리므로 둘 다 넣는다. 모르는 키는 무시되므로 안전하다.
      - vLLM 확장:      guided_json
      - OpenAI 표준:    response_format={"type": "json_schema", ...}
    """
    payload["guided_json"] = GUIDED_JSON
    payload["response_format"] = {
        "type": "json_schema",
        "json_schema": {"name": "receipt", "schema": GUIDED_JSON, "strict": True},
    }


# ── 이미지 전처리 ─────────────────────────────────────────────────


def prepare_image_bytes(raw: bytes, max_px: int | None = None) -> bytes:
    """EXIF 회전 보정(폰 사진 필수) + 긴 변 축소 후 JPEG 바이트로.

    실패하면 `ValueError` — 호출자(업로드 라우터)가 400 으로 바꾼다.
    """
    limit = max_px or settings.ocr_max_image_px
    try:
        with Image.open(BytesIO(raw)) as im:
            im = ImageOps.exif_transpose(im)
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            width, height = im.size
            longest = max(width, height)
            if limit and longest > limit:
                scale = limit / float(longest)
                im = im.resize(
                    (max(1, int(width * scale)), max(1, int(height * scale))),
                    Image.LANCZOS,
                )
            buffer = BytesIO()
            im.convert("RGB").save(buffer, format="JPEG", quality=88, optimize=True)
            return buffer.getvalue()
    except Exception as exc:  # noqa: BLE001 - Pillow 는 다양한 예외를 던진다
        raise ValueError("이미지를 읽을 수 없습니다.") from exc


def prepare_image_file(image_path: Path, max_px: int | None = None) -> bytes:
    return prepare_image_bytes(Path(image_path).read_bytes(), max_px)


# ── 응답 파싱 ─────────────────────────────────────────────────────

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)
_DIGITS_RE = re.compile(r"\D+")
_DECIMAL_RE = re.compile(r"^-?\d+\.\d{1,2}$")


def strip_json(text: str | None) -> str | None:
    """코드펜스/앞뒤 잡텍스트를 벗기고 가장 바깥 `{...}` 만 남긴다."""
    if not text:
        return None
    cleaned = _FENCE_RE.sub("", text.strip())
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return cleaned[start : end + 1]


def parse_amount(value: Any) -> int | None:
    """`"12,000원"`, `"₩12000"`, `"12.000"` → 12000. 실패하면 None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        return int(round(value)) if value > 0 else None

    text = re.sub(r"[^\d.,\-]", "", str(value))  # 원, ₩, KRW, 공백 제거
    text = text.replace(",", "")
    if not text or text in ("-", "."):
        return None
    try:
        # 소수점 1~2자리면 실수(12000.00), 그 외의 '.' 은 천단위 구분자(12.000)
        number = int(round(float(text))) if _DECIMAL_RE.match(text) else int(text.replace(".", ""))
    except ValueError:
        return None
    return number if number > 0 else None


def parse_datetime(value: Any) -> datetime | None:
    """관용적 날짜 파싱 → naive UTC (naive 입력은 KST 벽시계로 간주)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return to_utc_naive(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        # "26.08.04" 처럼 앞이 연도인 표기를 우선한다 (한국 영수증 관례)
        dt = date_parser.parse(text, yearfirst=True)
    except (ValueError, OverflowError, TypeError):
        return None
    if not (2000 <= dt.year <= 2100):  # 오독으로 나온 엉뚱한 연도 방어
        return None
    return to_utc_naive(dt)


def _clean_text(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text or text.lower() in ("null", "none", "n/a", "-"):
        return None
    return text[:limit]


def normalize_parsed(obj: Any) -> dict[str, Any]:
    """모델이 준 dict 를 ParsedReceipt 규약에 맞게 정규화한다."""
    parsed = empty_parsed()
    if not isinstance(obj, dict):
        return parsed
    parsed["store_name"] = _clean_text(obj.get("store_name"), 200)
    bn = _clean_text(obj.get("business_number"), 40)
    if bn:
        digits = _DIGITS_RE.sub("", bn)
        parsed["business_number"] = digits if len(digits) == 10 else None
    parsed["address"] = _clean_text(obj.get("address"), 300)
    parsed["phone"] = _clean_text(obj.get("phone"), 40)
    parsed["total_amount"] = parse_amount(obj.get("total_amount"))
    parsed["paid_at"] = parse_datetime(obj.get("paid_at"))
    return parsed


def parse_model_output(text: str | None) -> tuple[dict[str, Any], str | None]:
    """모델 원문 → (parsed, error)."""
    snippet = strip_json(text)
    if snippet is None:
        return empty_parsed(), "OCR 응답에서 JSON 을 찾지 못했습니다."
    try:
        obj = json.loads(snippet)
    except json.JSONDecodeError as exc:
        return empty_parsed(), f"OCR 응답 JSON 파싱에 실패했습니다. ({exc.msg})"
    if not isinstance(obj, dict):
        return empty_parsed(), "OCR 응답이 JSON 객체가 아닙니다."
    return normalize_parsed(obj), None


# ── Provider 구현 ─────────────────────────────────────────────────


class QwenVisionProvider:
    """OpenAI 호환 비전 엔드포인트(`/chat/completions`)에 이미지를 직접 보낸다."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.base_url = (base_url if base_url is not None else settings.ocr_base_url).rstrip("/")
        self.model = model or settings.ocr_model
        self.api_key = api_key if api_key is not None else settings.ocr_api_key
        self.timeout = timeout or settings.ocr_timeout

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _payload(self, image_b64: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                        },
                    ],
                }
            ],
            "temperature": 0,
            "max_tokens": 800,
        }
        if settings.ocr_use_guided_json:
            _add_guided_json(payload)
        return payload

    def extract(self, image_path: Path) -> OcrResult:
        started = time.perf_counter()

        def elapsed() -> int:
            return int((time.perf_counter() - started) * 1000)

        if not self.base_url:
            return OcrResult(elapsed_ms=elapsed(), error="OCR 서버(OCR_BASE_URL)가 설정되지 않았습니다.")

        try:
            image_bytes = prepare_image_file(image_path)
            image_b64 = base64.b64encode(image_bytes).decode("ascii")
        except Exception as exc:  # noqa: BLE001
            log.warning("OCR 이미지 전처리 실패: %s", exc)
            return OcrResult(elapsed_ms=elapsed(), error="이미지를 읽을 수 없습니다.")

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=self._payload(image_b64),
                )
            if response.status_code >= 400:
                return OcrResult(
                    raw=response.text[:4000],
                    elapsed_ms=elapsed(),
                    error=f"OCR 서버 오류 ({response.status_code})",
                )
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            if isinstance(content, list):  # 일부 서버는 content 를 파트 배열로 준다
                content = "".join(
                    part.get("text", "") for part in content if isinstance(part, dict)
                )
        except httpx.TimeoutException:
            return OcrResult(elapsed_ms=elapsed(), error="OCR 서버 응답이 시간 초과되었습니다.")
        except httpx.HTTPError as exc:
            return OcrResult(elapsed_ms=elapsed(), error=f"OCR 서버에 연결할 수 없습니다. ({exc})")
        except Exception as exc:  # noqa: BLE001 - 어떤 예외도 앱을 죽이지 않는다
            log.exception("OCR 호출 중 예기치 못한 오류")
            return OcrResult(elapsed_ms=elapsed(), error=f"OCR 처리에 실패했습니다. ({exc})")

        raw = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        parsed, error = parse_model_output(raw)
        return OcrResult(parsed=parsed, raw=(raw or "")[:8000], elapsed_ms=elapsed(), error=error)


class QwenTextProvider:
    """비전 미지원 폴백. 이미지→텍스트 추출기(PaddleOCR 등)가 붙어야 동작한다."""

    def __init__(self, text_extractor: Any | None = None) -> None:
        self.text_extractor = text_extractor
        self.vision = QwenVisionProvider()

    def extract(self, image_path: Path) -> OcrResult:
        started = time.perf_counter()
        if self.text_extractor is None:
            return OcrResult(
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                error="비전 미지원 폴백에 로컬 OCR 이 필요합니다",
            )
        try:
            text = self.text_extractor(Path(image_path))
        except Exception as exc:  # noqa: BLE001
            return OcrResult(
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                error=f"로컬 OCR 텍스트 추출에 실패했습니다. ({exc})",
            )
        return self._structure(text, started)

    def _structure(self, text: str, started: float) -> OcrResult:
        """추출된 텍스트를 Qwen(텍스트)에게 JSON 으로 구조화시킨다."""

        def elapsed() -> int:
            return int((time.perf_counter() - started) * 1000)

        if not self.vision.base_url:
            return OcrResult(elapsed_ms=elapsed(), error="OCR 서버(OCR_BASE_URL)가 설정되지 않았습니다.")
        payload: dict[str, Any] = {
            "model": self.vision.model,
            "messages": [
                {"role": "user", "content": f"{PROMPT}\n\n[영수증 텍스트]\n{text}"},
            ],
            "temperature": 0,
            "max_tokens": 800,
        }
        if settings.ocr_use_guided_json:
            _add_guided_json(payload)
        try:
            with httpx.Client(timeout=self.vision.timeout) as client:
                response = client.post(
                    f"{self.vision.base_url}/chat/completions",
                    headers=self.vision._headers(),
                    json=payload,
                )
            if response.status_code >= 400:
                return OcrResult(
                    raw=response.text[:4000],
                    elapsed_ms=elapsed(),
                    error=f"OCR 서버 오류 ({response.status_code})",
                )
            raw = response.json()["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001
            return OcrResult(elapsed_ms=elapsed(), error=f"OCR 처리에 실패했습니다. ({exc})")
        parsed, error = parse_model_output(raw)
        return OcrResult(parsed=parsed, raw=(raw or "")[:8000], elapsed_ms=elapsed(), error=error)


class DisabledProvider:
    """OCR 끔 — 조용히 전부 null 을 돌려주고 수동 입력을 유도한다 (error 없음)."""

    def extract(self, image_path: Path) -> OcrResult:
        return OcrResult(parsed=empty_parsed(), raw=None, elapsed_ms=0, error=None)


def get_ocr_provider() -> OcrProvider:
    """`settings.ocr_provider` 로 분기. base_url 이 없으면 자동으로 disabled."""
    provider = (settings.ocr_provider or "").strip().lower()
    if provider == "disabled" or not settings.ocr_base_url:
        return DisabledProvider()
    if provider == "qwen_text":
        return QwenTextProvider()
    return QwenVisionProvider()


__all__ = [
    "DisabledProvider",
    "GUIDED_JSON",
    "OcrProvider",
    "OcrResult",
    "PARSED_KEYS",
    "PROMPT",
    "QwenTextProvider",
    "QwenVisionProvider",
    "empty_parsed",
    "get_ocr_provider",
    "normalize_parsed",
    "parse_amount",
    "parse_datetime",
    "parse_model_output",
    "prepare_image_bytes",
    "prepare_image_file",
    "strip_json",
]
