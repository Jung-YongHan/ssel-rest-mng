#!/bin/sh
# ==============================================================
#  ssel-rest-mng 백업 — app-data 볼륨 하나에 DB + 영수증 이미지가 모두 있다.
#
#  cron 에서 하루 한 번 도는 것을 전제로 한다 (DEPLOY.md 5장).
#      0 4 * * * /home/<user>/.../deploy/backup.sh >> ~/ssel-backups/backup.log 2>&1
#
#  단순히 볼륨을 tar 로 묶기만 하면 SQLite 의 WAL 때문에 스냅샷이 찢어질 수
#  있다. 그래서 컨테이너가 떠 있으면 sqlite 의 온라인 백업(.backup)으로
#  일관된 사본을 볼륨 안에 먼저 만들고, 그것까지 함께 묶는다.
#  컨테이너가 꺼져 있으면 DB 가 이미 정지 상태이므로 tar 만으로 충분하다.
#
#  ⚠️ 백업 파일에는 구성원 계정 해시와 영수증 원본이 들어 있다.
#     저장소 디렉터리 안에 두지 말고 권한을 제한할 것 (아래에서 0700/0600).
# ==============================================================
set -eu

# ── 설정 (환경변수로 덮어쓸 수 있다) ─────────────────────────
PROJECT_DIR="${PROJECT_DIR:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/ssel-backups}"
VOLUME="${VOLUME:-ssel-rest-mng_app-data}"
KEEP_DAYS="${KEEP_DAYS:-14}"

# cron 의 PATH 는 빈약하다. docker 를 못 찾는 사고가 가장 흔하다.
PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"
export PATH

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
fail() { log "ERROR: $*"; exit 1; }

command -v docker >/dev/null 2>&1 || fail "docker 를 찾을 수 없습니다 (PATH=$PATH)"
docker volume inspect "$VOLUME" >/dev/null 2>&1 || fail "볼륨이 없습니다: $VOLUME"

mkdir -p "$BACKUP_DIR"
chmod 0700 "$BACKUP_DIR"

STAMP="$(date +%Y%m%d-%H%M)"
ARCHIVE="ssel-$STAMP.tar.gz"

# ── 1) 일관된 DB 스냅샷 ──────────────────────────────────────
# 컨테이너 안에서 sqlite3.backup() 을 돌려 볼륨 안에 backup.db 를 만든다.
# 실패하거나 컨테이너가 꺼져 있으면 건너뛰고 tar 만 진행한다.
SNAPSHOT_MADE=0
if docker compose -f "$PROJECT_DIR/docker-compose.yml" ps --status running 2>/dev/null | grep -q ssel-rest-mng; then
    if docker compose -f "$PROJECT_DIR/docker-compose.yml" exec -T app python -c "
import sqlite3
src = sqlite3.connect('/app/backend/data/app.db')
dst = sqlite3.connect('/app/backend/data/backup.db')
with dst: src.backup(dst)
dst.close(); src.close()
" >/dev/null 2>&1; then
        SNAPSHOT_MADE=1
        log "DB 온라인 스냅샷 생성 (backup.db)"
    else
        log "WARN: DB 스냅샷 실패 — 볼륨 tar 만 진행합니다"
    fi
else
    log "컨테이너가 실행 중이 아님 — DB 가 정지 상태이므로 tar 만 진행합니다"
fi

# 스냅샷은 아카이브에 담긴 뒤 볼륨에서 지운다. 중간에 죽어도 남지 않도록 trap.
cleanup() {
    [ "$SNAPSHOT_MADE" = "1" ] || return 0
    docker run --rm -v "$VOLUME:/data" alpine rm -f /data/backup.db >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

# ── 2) 볼륨 통째로 묶기 ──────────────────────────────────────
# 볼륨은 uid 10001(appuser) 소유라 tar 는 root 로 읽어야 한다. 그러면 결과
# 파일도 root 소유로 생겨 호스트 사용자가 chmod 할 수 없으므로, 같은
# 컨테이너 안에서 소유권과 권한까지 정리한다.
docker run --rm \
    -v "$VOLUME:/data:ro" \
    -v "$BACKUP_DIR:/backup" \
    alpine sh -c "tar czf '/backup/$ARCHIVE' -C /data . \
        && chown $(id -u):$(id -g) '/backup/$ARCHIVE' \
        && chmod 0600 '/backup/$ARCHIVE'" \
    || fail "tar 실패"
SIZE="$(du -h "$BACKUP_DIR/$ARCHIVE" | cut -f1)"
log "백업 완료: $BACKUP_DIR/$ARCHIVE ($SIZE)"

# ── 3) 무결성 확인 ───────────────────────────────────────────
# 목록을 읽을 수 없으면 깨진 아카이브다. 조용히 쌓이는 것이 가장 위험하다.
tar tzf "$BACKUP_DIR/$ARCHIVE" >/dev/null 2>&1 || fail "아카이브가 손상되었습니다: $ARCHIVE"

# ── 4) 오래된 백업 정리 ──────────────────────────────────────
DELETED="$(find "$BACKUP_DIR" -maxdepth 1 -name 'ssel-*.tar.gz' -mtime "+$KEEP_DAYS" -print -delete | wc -l)"
[ "$DELETED" -gt 0 ] && log "오래된 백업 $DELETED 개 삭제 (${KEEP_DAYS}일 초과)"

log "보관 중인 백업: $(find "$BACKUP_DIR" -maxdepth 1 -name 'ssel-*.tar.gz' | wc -l) 개"
