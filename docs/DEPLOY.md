# 배포 가이드 (원격 서버)

연구실 서버(또는 아무 리눅스 호스트)에 Docker 로 배포하는 절차입니다.
필요한 건 **Docker 와 Docker Compose v2 이상**뿐입니다.
프론트엔드는 이미지 안에서 함께 빌드되어 백엔드와 **같은 포트**로 서빙되므로
nginx 같은 별도 웹서버가 없어도 동작합니다.

> ⚠️ **이 저장소는 공개입니다.** 아래 어느 단계에서도 내부 IP·시크릿을
> 저장소에 커밋하지 마세요. 모든 환경별 값은 서버의 `.env` 파일에만 존재해야 합니다.

---

## 0. 사전 준비

```bash
docker --version          # 20.10+ 권장
docker compose version    # v2 이상 (v1 의 `docker-compose` 는 지원하지 않음)
```

서버에서 다음이 되는지 확인합니다.

- 노출할 포트(기본 `8000`)가 방화벽에서 열려 있는지
- 연구실 Qwen 서버(`OCR_BASE_URL`)에 이 서버에서 **네트워크로 도달 가능**한지

---

## 1. 저장소 클론

```bash
git clone <이 저장소 URL> ssel-rest-mng
cd ssel-rest-mng
```

---

## 2. `.env` 만들기

```bash
cp .env.example .env
```

`.env` 는 `.gitignore` 에 들어 있어 커밋되지 않습니다. **절대 커밋하지 마세요.**

### 2-1. `JWT_SECRET` 생성

```bash
openssl rand -hex 32
```

출력된 64자 hex 문자열을 `.env` 의 `JWT_SECRET` 에 붙여넣습니다.
기본값(`change-me-please-openssl-rand-hex-32`)을 그대로 두면 **누구나 로그인 토큰을
위조할 수 있습니다.**

한 줄로 처리하고 싶으면:

```bash
sed -i "s|^JWT_SECRET=.*|JWT_SECRET=$(openssl rand -hex 32)|" .env
grep '^JWT_SECRET=' .env      # 값이 바뀌었는지만 확인
```

### 2-2. 나머지 필수 항목

```bash
nano .env      # 또는 vim
```

| 키 | 채울 값 |
|---|---|
| `ENVIRONMENT` | `production` |
| `JWT_SECRET` | 위에서 만든 64자 hex |
| `INVITE_CODE` | 연구실 구성원에게만 공유할 가입 코드 (추측 어렵게) |
| `OCR_BASE_URL` | 자체 호스팅 Qwen 서버의 OpenAI 호환 주소, `/v1` 까지 포함 |
| `OCR_MODEL` | 그 서버에 로드된 모델 이름 |
| `OCR_API_KEY` | 서버가 키를 요구하면 입력, 아니면 비워둠 |
| `ADMIN_EMAIL` | 최초 관리자 이메일 |
| `ADMIN_PASSWORD` | 최초 관리자 비밀번호 (8자 이상, 반드시 변경) |
| `ADMIN_NAME` | 최초 관리자 표시 이름 |
| `COOKIE_SECURE` | HTTPS 를 붙일 예정이면 `true`, HTTP 로 운영하면 **`false`** |
| `PUBLIC_ORIGIN` | HTTPS 로 공개할 때만. 공개 주소를 스킴까지 (`https://ssel.example.com`). HTTP 내부망 전용이면 비워둠 |
| `PORT` | (선택) 호스트에 노출할 포트. 기본 `8000` |

OCR 서버가 아직 준비되지 않았다면 일단 `OCR_PROVIDER=disabled` 로 두고 배포하세요.
앱은 수동 입력만으로 완전히 동작하며, 나중에 값만 채우고 재시작하면 됩니다.

### 2-3. 값 확인

```bash
docker compose config | grep -E 'ENVIRONMENT|COOKIE_SECURE|OCR_PROVIDER'
```

> `docker compose config` 는 `.env` 의 값을 **평문으로 출력**합니다.
> 공유 터미널이나 로그에 전체 출력을 남기지 마세요.

---

## 3. 기동

```bash
docker compose up -d --build
docker compose logs -f app
```

로그에서 다음이 보이면 정상입니다.

```
[entrypoint] DB 마이그레이션 실행: alembic upgrade head
[entrypoint] ✅ 마이그레이션 완료. 서버를 시작합니다.
... INFO  ssel: DB: sqlite:////app/backend/data/app.db
... INFO  ssel: OCR: provider=qwen_vl model=...
... INFO  Uvicorn running on http://0.0.0.0:8000
```

**컨테이너는 기동할 때마다 `alembic upgrade head` 를 실행합니다.**
새 서버든 업데이트든 마이그레이션을 손으로 돌릴 필요가 없습니다.

확인:

```bash
curl -s http://localhost:8000/api/health
# {"status":"ok","environment":"production","ocr_enabled":true,"low_balance_threshold":30000}

docker compose ps            # STATUS 가 (healthy) 로 바뀌는지 확인
```

브라우저에서 `http://<서버주소>:8000` 을 엽니다.

---

## 4. 최초 관리자 계정 만들기

두 가지 방법이 있고, **아무거나 하나만** 하면 됩니다.

### 방법 A — 웹에서 가입 (권장)

`http://<서버주소>:8000/login` → **가입** 탭 →
이메일·이름·비밀번호 + `INVITE_CODE` 입력.

> **첫 번째로 가입한 사용자는 자동으로 관리자(`admin`)** 가 됩니다.
> 연구실 초기 세팅 편의를 위한 동작이므로, **배포 직후 가장 먼저 본인이 가입하세요.**
> 두 번째부터 가입하는 사람은 일반 구성원(`member`) 이고,
> 관리자가 `/admin` 화면에서 권한을 올려줄 수 있습니다.

### 방법 B — `scripts/seed.py`

`.env` 의 `ADMIN_EMAIL` / `ADMIN_PASSWORD` / `ADMIN_NAME` 으로 계정을 만듭니다.

```bash
docker compose exec app python scripts/seed.py
```

```
✅ 관리자 계정을 생성했습니다: admin@example.com (관리자)
   비밀번호는 .env 의 ADMIN_PASSWORD 값입니다. 로그인 후 바로 변경하세요.
```

멱등(idempotent) 하므로 여러 번 실행해도 안전합니다.
**이미 있는 계정의 비밀번호는 덮어쓰지 않습니다** (비밀번호를 잊었다면
`.env` 를 바꾸는 게 아니라 다른 관리자 계정으로 `/admin` 에서 재설정하세요).

화면에 예시 데이터를 넣어보고 싶다면 (**운영 데이터에는 쓰지 마세요**):

```bash
docker compose exec app python scripts/seed.py --demo
```

---

## 5. 백업

백업해야 할 것은 **`app-data` 볼륨 하나**입니다.
그 안에 SQLite DB(`app.db`)와 영수증 이미지(`uploads/`)가 모두 들어 있습니다.

> ⚠️ 백업 파일에는 구성원 계정과 영수증 원본이 들어 있습니다.
> 저장소 디렉터리 안에 두지 말고, 접근 권한을 제한하세요.

### 5-1. 전체 볼륨 백업 (권장)

```bash
mkdir -p ~/ssel-backups

docker run --rm \
  -v ssel-rest-mng_app-data:/data:ro \
  -v ~/ssel-backups:/backup \
  alpine tar czf /backup/ssel-$(date +%Y%m%d-%H%M).tar.gz -C /data .

ls -lh ~/ssel-backups
```

볼륨 이름은 `<compose project name>_app-data` 입니다.
`docker volume ls | grep app-data` 로 정확한 이름을 확인하세요.

### 5-2. DB 만 온라인 백업 (`sqlite3 .backup`)

서버를 멈추지 않고 **일관된 스냅샷**을 뜨는 방법입니다.
단순 파일 복사는 WAL 때문에 깨질 수 있으므로 이 방식을 쓰세요.

```bash
# 컨테이너 안에서 (sqlite3 CLI 가 없으면 아래 파이썬 방식을 사용)
docker compose exec app \
  sqlite3 /app/backend/data/app.db ".backup '/app/backend/data/backup.db'"

# 호스트로 꺼내기
docker compose cp app:/app/backend/data/backup.db ./ssel-$(date +%Y%m%d).db
docker compose exec app rm /app/backend/data/backup.db
```

슬림 이미지에는 `sqlite3` CLI 가 없습니다. 표준 라이브러리로 같은 일을 합니다:

```bash
docker compose exec app python -c "
import sqlite3
src = sqlite3.connect('/app/backend/data/app.db')
dst = sqlite3.connect('/app/backend/data/backup.db')
with dst: src.backup(dst)
dst.close(); src.close()
print('백업 완료: data/backup.db')
"
docker compose cp app:/app/backend/data/backup.db ./ssel-$(date +%Y%m%d).db
docker compose exec app rm /app/backend/data/backup.db
```

### 5-3. 복원

```bash
docker compose down

docker run --rm \
  -v ssel-rest-mng_app-data:/data \
  -v ~/ssel-backups:/backup \
  alpine sh -c "rm -rf /data/* && tar xzf /backup/ssel-20260804-1200.tar.gz -C /data"

docker compose up -d
```

### 5-4. 자동 백업 (cron 예시)

```bash
crontab -e
```

```cron
# 매일 새벽 4시 볼륨 백업, 14일치 보관
0 4 * * * docker run --rm -v ssel-rest-mng_app-data:/data:ro -v /home/lab/ssel-backups:/backup alpine tar czf /backup/ssel-$(date +\%Y\%m\%d).tar.gz -C /data . && find /home/lab/ssel-backups -name 'ssel-*.tar.gz' -mtime +14 -delete
```

---

## 6. 업데이트

```bash
cd ssel-rest-mng
git pull
docker compose up -d --build
docker compose logs -f app
```

- **마이그레이션은 엔트리포인트가 자동으로 실행합니다.** (`alembic upgrade head`)
- 데이터는 `app-data` 볼륨에 있으므로 재빌드로 사라지지 않습니다
- 스키마가 바뀌는 업데이트 전에는 **5장의 백업을 먼저** 하세요

옛 이미지 정리:

```bash
docker image prune -f
```

`.env.example` 에 새 키가 추가됐을 수 있으니 업데이트 후 한 번 비교하세요.

```bash
diff <(grep -oE '^[A-Z_]+=' .env.example | sort) <(grep -oE '^[A-Z_]+=' .env | sort)
```

> `docker compose down -v` 는 **볼륨까지 삭제**합니다. 되돌릴 수 없습니다.
> 정지만 하려면 `docker compose down` 또는 `docker compose stop` 을 쓰세요.

---

## 7. (선택) HTTPS 붙이기 — Caddy

도메인이 있다면 Caddy 가 Let's Encrypt 인증서를 자동으로 발급·갱신합니다.

`/etc/caddy/Caddyfile`:

```caddy
ssel.example.com {
    encode zstd gzip
    reverse_proxy 127.0.0.1:8000
}
```

```bash
sudo systemctl reload caddy
```

그다음 `.env` 를 고치고 재시작합니다.

```bash
# HTTPS 로 서비스하므로
COOKIE_SECURE=true
# 정규 주소 — 다른 Host(예: http://<서버IP>:8000)로 들어온 화면 요청을 여기로 보낸다.
# 그 주소로 홈 화면에 PWA 를 추가해 버리는 사고를 막는다 (§8 참고).
PUBLIC_ORIGIN=https://ssel.example.com
```

```bash
docker compose up -d
```

컨테이너는 `--proxy-headers --forwarded-allow-ips=*` 로 실행되므로
`X-Forwarded-For` / `X-Forwarded-Proto` 를 그대로 인식합니다.
리버스 프록시를 쓸 때는 `ports` 를 `"127.0.0.1:${PORT:-8000}:8000"` 으로 바꿔
컨테이너를 외부에 직접 노출하지 않는 편이 안전합니다.

### HTTPS 가 필요한 이유와 필요 없는 이유

| 기능 | HTTP | HTTPS |
|---|---|---|
| 영수증 **카메라 촬영** (`<input type="file" accept="image/*" capture>`) | ✅ 동작 | ✅ 동작 |
| 로그인·모든 API | ✅ 동작 (`COOKIE_SECURE=false` 필요) | ✅ 동작 |
| **PWA "홈 화면에 추가"** (앱처럼 설치) | ❌ **불가** | ✅ 가능 |
| Service Worker / 오프라인 캐시 | ❌ 불가 | ✅ 가능 |

`<input capture>` 는 파일 선택 UI 를 카메라로 여는 방식이라 **보안 컨텍스트를
요구하지 않습니다.** 그래서 HTTP 배포에서도 영수증 촬영은 잘 됩니다.
반면 **PWA 설치와 Service Worker 는 HTTPS(또는 `localhost`)에서만** 동작합니다.

즉 연구실 내부망에서 브라우저로만 쓸 거면 HTTP 로도 충분하고,
**폰 홈 화면에 앱처럼 설치해서 쓰고 싶다면 HTTPS 가 필요합니다.**

---

## 7-2. (선택) HTTPS 붙이기 — 이미 있는 쿠버네티스 ingress-nginx 에 얹기

배포할 서버가 **이미 쿠버네티스 노드**이고 80/443 을 클러스터의 ingress-nginx 가
쓰고 있다면, 7장의 Caddy 대신 이 방법을 씁니다. 포트를 뺏지 않고 **호스트 이름으로
나눠 쓰는** 방식이라 기존 서비스에 영향이 없습니다.

먼저 정말 그 상황인지 확인합니다.

```bash
kubectl get svc -A | grep LoadBalancer      # ingress-nginx 가 80:xxxxx/443:xxxxx 를 잡고 있는지
kubectl get ingressclass                    # nginx 클래스가 있는지
kubectl get clusterissuer                   # cert-manager 발급자가 Ready 인지
```

> `ss -tlnp` 에 80/443 이 **안 보여도** 점유 중일 수 있습니다. kube-proxy 가 IPVS
> 모드면 LoadBalancer VIP 가 `kube-ipvs0` 에 붙어 커널에서 처리되므로 리스닝 소켓이
> 없습니다. `ip addr show kube-ipvs0` 로 VIP 를 확인하세요.

### 절차

**1) DNS** — 공개할 호스트명의 A 레코드를 **공인 IP** 로 등록합니다.
cert-manager 가 HTTP-01 챌린지를 쓰므로, 이 레코드가 없으면 인증서 발급이 실패합니다.

**2) `.env`** — HTTPS 로 서비스하므로 반드시 아래 세 개를 맞춥니다.

```bash
ENVIRONMENT=production
COOKIE_SECURE=true
PUBLIC_ORIGIN=https://<공개할 호스트명>
```

`PUBLIC_ORIGIN` 을 넣으면 이 주소가 아닌 Host 로 들어온 **화면 요청**이 정규 주소로
307 리다이렉트됩니다. 이 구성에서는 8000 포트가 노드에 열려 있어 누군가
`http://<서버IP>:8000` 을 그대로 열거나 **그 주소로 홈 화면에 PWA 를 추가**하기
쉬운데, 그렇게 설치된 앱은 사내망을 벗어나면 아무 요청도 닿지 않으면서 화면만
서비스워커 캐시로 떠서 "로그인만 안 되는 앱"이 됩니다(§8 참고). API 요청과 정적
파일은 옮기지 않으므로 ingress·healthcheck 에는 영향이 없습니다.

**3) compose 기동** — 3장과 동일합니다.

```bash
docker compose up -d --build
curl -s http://localhost:8000/api/health
```

> ⚠️ **이 구성에서는 7장의 `127.0.0.1:8000` 바인딩을 쓰면 안 됩니다.**
> 프록시(ingress-nginx 파드)가 **다른 노드**에 있을 수 있어서, 루프백에 묶으면
> 도달하지 못합니다. 기본값(`0.0.0.0`) 그대로 두고, 대신 방화벽에서 8000 포트를
> 클러스터 노드 IP 로만 제한하세요.
>
> ```bash
> sudo ufw allow from <노드IP> to any port 8000 proto tcp   # 노드마다 한 줄
> sudo ufw deny 8000/tcp
> ```

**4) 매니페스트 적용**

```bash
cp deploy/k8s/ssel-rest-mng.yaml.example deploy/k8s/ssel-rest-mng.yaml
# __APP_HOST__ / __APP_NODE_IP__ 를 실제 값으로 치환 (채운 파일은 .gitignore 됨)
kubectl apply -f deploy/k8s/ssel-rest-mng.yaml --dry-run=server   # 먼저 검증
kubectl apply -f deploy/k8s/ssel-rest-mng.yaml
```

**5) 확인**

```bash
kubectl get ingress ssel-rest-mng-ingress
kubectl get endpointslice -l kubernetes.io/service-name=ssel-rest-mng
kubectl get certificate ssel-rest-mng-tls -w      # READY=True 까지 보통 1~2분
```

### 이 방식에서 꼭 필요한 두 가지 애노테이션

ingress-nginx 의 기본값을 그대로 두면 **두 군데서 터집니다.** 매니페스트에 이미
들어 있지만, 왜 필요한지 알고 있어야 나중에 지우지 않습니다.

| 애노테이션 | 기본값 | 없으면 |
|---|---|---|
| `proxy-body-size: "20m"` | 1m | 영수증 업로드가 **413** (`MAX_UPLOAD_MB=15`) |
| `proxy-read-timeout: "180"` | 60s | OCR 이 느릴 때 **504** (`OCR_TIMEOUT=120`) |

`proxy-read-timeout` 이 필요한 이유는 업로드 요청 **안에서** OCR 을 동기로 돌리기
때문입니다(`api/receipts.py` 의 `_run_ocr`). 즉 업로드 HTTP 요청 자체가 최대
`OCR_TIMEOUT` 만큼 걸릴 수 있습니다.

**전역 ConfigMap(`ingress-nginx-controller`)이 아니라 이 Ingress 에만** 걸어야
같은 컨트롤러를 쓰는 다른 서비스에 영향이 없습니다.

### 앱을 아예 파드로 옮기지 않는 이유

이 앱은 SQLite 단일 인스턴스입니다. 클러스터의 StorageClass 가 NFS 기반뿐이라면
**SQLite 를 NFS 에 올리면 안 됩니다** — 파일 락이 신뢰할 수 없고 WAL 모드에서 DB 가
깨질 수 있습니다. 굳이 파드로 옮기려면 local PV 로 노드에 고정하거나 PostgreSQL 로
전환해야 하고(`docker-compose.yml` 하단 주석), `replicas: 1` + `strategy: Recreate`
가 필수입니다. 5장의 볼륨 백업 절차도 전부 다시 써야 합니다.

---

## 8. 트러블슈팅

### 로그인이 안 됨 — 아이디/비번은 맞는데 계속 로그인 화면으로 돌아온다

**가장 흔한 원인: HTTP 배포인데 `COOKIE_SECURE=true`.**

인증은 httpOnly 쿠키(`ssel_token`)로 하는데, `Secure` 플래그가 붙은 쿠키는
브라우저가 **HTTPS 가 아닌 연결에서 저장하지 않습니다.** 그래서 로그인 요청은
200 으로 성공하는데 다음 요청에 쿠키가 실리지 않아 `/api/auth/me` 가 401 이 됩니다.

```bash
grep COOKIE_SECURE .env      # HTTP 배포라면 false 여야 한다
sed -i 's|^COOKIE_SECURE=.*|COOKIE_SECURE=false|' .env
docker compose up -d
```

브라우저 개발자도구 → Application → Cookies 에 `ssel_token` 이 **없으면** 이 문제입니다.

그 외 확인할 것

- `JWT_SECRET` 을 바꿨다 → 기존 토큰이 모두 무효화됩니다. 다시 로그인하면 됩니다
- 계정이 비활성화됨 → 401 `"계정을 사용할 수 없습니다."` (관리자가 `/admin` 에서 활성화)
- 초대코드 오류 → 403 `"초대코드가 올바르지 않습니다."` (`.env` 의 `INVITE_CODE` 확인)
- 비밀번호가 8자 미만 → 422. 가입 자체가 안 됩니다

### 홈 화면에 추가한 웹앱(PWA)만 "서버에 연결하지 못했습니다"

**원인: 그 웹앱이 지금 닿지 않는 주소로 설치되어 있습니다.** 거의 항상
`http://<서버 LAN IP>:8000` 으로 홈 화면에 추가한 경우입니다.

브라우저에서는 잘 되는데 홈 화면 앱만 안 되는 이유는 두 가지가 겹쳐서입니다.

- 서비스워커가 셸(`index.html` + JS/CSS)을 프리캐시하므로 **서버에 못 닿아도
  로그인 화면까지는 정상적으로 그려집니다.** 반대로 `/api/*` 는 캐시 대상이
  아니어서(`navigateFallbackDenylist`) 반드시 네트워크로 나갑니다 → 화면은
  멀쩡한데 로그인만 실패하는 모습이 됩니다.
- iOS 16.4+ 는 홈 화면 웹앱에 **사파리와 분리된 저장소**를 줍니다. 그래서 사파리
  쪽이 멀쩡해도 웹앱만 옛 주소·옛 캐시에 갇혀 있을 수 있습니다.

진단 — 폰에서 사파리로 `/api/health` 를 직접 엽니다. `/api` 는 절대 캐시되지
않으므로 순수하게 네트워크만 봅니다.

```
https://<공개 호스트명>/api/health     → JSON 이 뜨면 네트워크는 정상
```

JSON 이 뜨는데 웹앱만 안 되면 **설치된 주소가 문제**입니다.

1. 웹앱 안에서 공유 버튼 → 시트 맨 위 주소 확인 (사설 IP + `:8000` 이면 확정)
2. 홈 화면 아이콘 길게 눌러 **앱 제거** (아이콘에 주소가 박혀 있어 수정 불가)
3. 사파리에서 `https://<공개 호스트명>` 접속 → 로그인 확인
4. 공유 → **홈 화면에 추가**

서버 로그로 교차 확인할 수 있습니다. 웹앱이 부팅되면 `/api/health` 와
`/api/auth/me` 가 **반드시** 찍히므로, 그 두 줄이 없다면 요청이 서버까지 오지
않은 것입니다(= 로그인 로직 문제가 아님).

```bash
docker compose logs app | grep -E 'auth/(me|login)' | tail
```

재발 방지: `.env` 에 `PUBLIC_ORIGIN` 을 설정하세요. LAN 주소로 들어온 화면
요청이 정규 주소로 307 리다이렉트되어 잘못된 주소로는 설치 자체가 되지 않습니다.
평문 HTTP 주소로 설치된 앱은 `COOKIE_SECURE=true` 쿠키가 저장되지 않아 사내망
안에서도 로그인을 끝낼 수 없으므로, 되살리려 하지 말고 다시 설치해야 합니다.

### 배포했는데 폰·PC 에서 옛 화면이 그대로 보인다

`Cache-Control` 을 지웠는지 확인하세요. `backend/app/main.py` 는 셸
(`index.html`·`sw.js`·`manifest.webmanifest`)에 `no-cache`, 해시가 붙은
`assets/*` 에 `immutable` 을 붙입니다. 셸에 헤더가 없으면 브라우저가 휴리스틱
캐싱으로 옛 셸을 계속 쓰고, 그 셸이 이미 사라진 청크를 가리키면 **앱이 통째로
뜨지 않습니다**(흰 화면).

```bash
curl -sI https://<공개 호스트명>/ | grep -i cache-control        # no-cache
curl -sI https://<공개 호스트명>/sw.js | grep -i cache-control   # no-cache
```

사용자 쪽 즉시 해결은 앱 안에서 뜨는 `새 버전이 있습니다 → 업데이트` 이고,
그것도 안 되면 홈 화면 앱을 제거하고 다시 추가하면 됩니다.

### OCR 이 타임아웃 / 응답이 없음

먼저 진단 스크립트를 돌립니다.

```bash
docker compose exec app python scripts/ocr_smoke.py --no-image
docker compose exec app python scripts/ocr_smoke.py /app/backend/data/uploads/2026/08/<파일>.jpg
```

| 증상 | 조치 |
|---|---|
| 도달 자체 실패 | 주소·포트·`/v1` 경로 확인. 컨테이너에서 나가는 경로가 막혔을 수 있음 (`docker compose exec app python -c "import socket;print(socket.gethostbyname('<host>'))"`) |
| 응답이 오는데 느림 → 타임아웃 | `OCR_TIMEOUT` 을 늘린다 (`120` → `300`). 큰 모델·CPU 추론이면 정상적으로 오래 걸린다 |
| 큰 사진에서만 타임아웃 | `OCR_MAX_IMAGE_PX` 를 줄인다 (`1600` → `1024`). 전송량과 토큰 수가 함께 줄어든다 |
| 잔글씨(사업자번호)를 못 읽음 | 반대로 `OCR_MAX_IMAGE_PX` 를 올린다 (`1600` → `2048`). 대신 느려진다 |
| **이미지 입력을 거부** (`image_url` 미지원 등의 에러) | 텍스트 전용 배포입니다. `OCR_PROVIDER=qwen_text` 로 바꾸세요 |
| JSON 파싱 실패 | 서버가 `guided_json` 을 지원하면 `OCR_USE_GUIDED_JSON=true` 로 켜서 구조화 출력을 강제 |
| 그래도 안 됨 | `OCR_PROVIDER=disabled` — 앱은 수동 입력으로 100% 동작합니다. OCR 은 나중에 붙여도 됩니다 |

`.env` 를 고친 뒤에는 반드시 재시작해야 반영됩니다.

```bash
docker compose up -d
```

OCR 이 실패해도 업로드는 **201 을 반환**하고 사용자는 수동 입력으로 진행합니다.
즉 OCR 장애로 앱이 멈추는 일은 없습니다. 실패 사유는 `ocr_error` 에 남습니다.

### 마이그레이션 충돌 / 컨테이너가 계속 재시작됨

```bash
docker compose logs app | tail -50
```

**증상별 조치**

| 로그 | 원인 / 조치 |
|---|---|
| `Can't locate revision identified by '<hash>'` | DB 의 `alembic_version` 이 코드에 없는 리비전을 가리킴 (다운그레이드했거나 다른 브랜치의 DB). `git pull` 로 최신 코드를 받거나, **백업 후** `docker compose exec app alembic stamp head` |
| `Multiple heads` / `Multiple head revisions` | 마이그레이션 브랜치가 갈라짐. `docker compose exec app alembic heads` 로 확인 후 개발 환경에서 `alembic merge heads` 로 병합해 커밋 |
| `Target database is not up to date` | `docker compose exec app alembic upgrade head` 를 수동 실행하고 에러를 확인 |
| `table ... already exists` | 이전에 `create_all` 로 만든 DB 에 alembic 을 얹으려는 상황. **백업 후** `docker compose exec app alembic stamp head` 로 현재 상태를 최신으로 표시 |
| `attempt to write a readonly database` / `unable to open database file` | 볼륨 권한 문제. 이미지가 uid `10001`(appuser) 로 실행되므로 볼륨 소유권을 맞춘다:<br>`docker compose down` → `docker run --rm -v ssel-rest-mng_app-data:/data alpine chown -R 10001:10001 /data` → `docker compose up -d` |
| `no such table: users` | 마이그레이션이 아예 돌지 않았음. 위 로그에서 alembic 단계의 에러를 먼저 찾는다 |

현재 상태 확인:

```bash
docker compose exec app alembic current
docker compose exec app alembic history --verbose | head -30
```

**중요:** 마이그레이션 문제를 만졌다면 **먼저 5장의 백업**을 하세요.
`alembic stamp` 는 스키마를 바꾸지 않고 버전 표시만 바꾸므로,
실제 스키마와 어긋나면 나중에 더 이상한 에러로 돌아옵니다.

### 그 밖에

| 증상 | 조치 |
|---|---|
| 포트 충돌 (`address already in use`) | `.env` 에 `PORT=9000` 등으로 변경 후 `docker compose up -d` |
| 프론트엔드 대신 JSON 안내 메시지가 보임 | 이미지에 `frontend/dist` 가 안 들어갔음. `docker compose build --no-cache` 로 재빌드 |
| 영수증 업로드 413 | `MAX_UPLOAD_MB` 를 늘린다 (기본 15) |
| 이미지 빌드가 `npm ci` 에서 실패 | `frontend/package-lock.json` 이 `package.json` 과 어긋남. 로컬에서 `npm install` 후 lockfile 을 커밋 |
| 이미지 빌드가 `vue-tsc` 에서 실패 | 프론트엔드 `build` 스크립트가 타입 검사를 포함하므로 TS 에러가 있으면 빌드가 멈춘다. 로컬에서 `cd frontend && npm run build` 로 먼저 통과시킨 뒤 커밋 |
| 디스크가 찬다 | 영수증 이미지가 쌓인 것. `docker compose exec app du -sh /app/backend/data/uploads` 로 확인 |
| 컨테이너 상태가 `unhealthy` | `docker compose exec app python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/api/health').read())"` 로 직접 확인 |

로그 실시간 확인 / 컨테이너 접속:

```bash
docker compose logs -f app
docker compose exec app sh
```
