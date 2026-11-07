#!/usr/bin/env bash
# Каждые 5 минут (таймер mocheqi-update): если на GitHub новая версия — скачать и перезапустить дашборд.
#   update.sh            — обычная проверка
#   update.sh --rollback — вернуть предыдущую версию и остановить автообновление
#   update.sh --resume   — снова включить автообновление (и сразу обновиться)
set -uo pipefail
DIR=/opt/mocheqi/dashboard
LOG=$DIR/data/update_log.txt
PIN=$DIR/data/UPDATES_PAUSED
G() { sudo -u mocheqi git -C "$DIR" "$@"; }
log() { echo "$(date '+%d.%m %H:%M:%S') $*" >> "$LOG"; }

case "${1:-}" in
  --rollback)
    PREV=$(G rev-parse HEAD~1 2>/dev/null) || { echo "Нет предыдущей версии"; exit 1; }
    G reset -q --hard "$PREV"; touch "$PIN"; chown mocheqi:mocheqi "$PIN"
    systemctl restart mocheqi.service
    log "ОТКАТ на $(G log -1 --format='%h %s')"; echo "Откат выполнен, автообновление остановлено. Включить: $0 --resume"; exit 0 ;;
  --resume) rm -f "$PIN"; log "автообновление включено" ;;
esac
[ -f "$PIN" ] && exit 0

G fetch -q origin main 2>>"$LOG" || { log "fetch не удался"; exit 0; }
[ "$(G rev-parse HEAD)" = "$(G rev-parse origin/main)" ] && exit 0
OLD=$(G rev-parse --short HEAD)
G reset -q --hard origin/main
chmod +x "$DIR/server/"*.sh
# проверка синтаксиса перед перезапуском; при ошибке — назад
if ! sudo -u mocheqi python3 -m py_compile "$DIR"/app/*.py 2>>"$LOG"; then
  G reset -q --hard "$OLD"; log "новая версия не прошла проверку — оставлена $OLD"; exit 1
fi
systemctl restart mocheqi.service
log "обновлено $OLD → $(G log -1 --format='%h %s')"
