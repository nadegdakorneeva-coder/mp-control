#!/usr/bin/env bash
# Перенос базы и ключей с компьютера.
# Положите config.ini и mp.sqlite в свою домашнюю папку на сервере (WinSCP) и выполните:
#   sudo bash /opt/mocheqi/dashboard/server/after_upload.sh
set -euo pipefail
DIR=/opt/mocheqi/dashboard
[ "$(id -u)" -eq 0 ] || { echo "Запустите через sudo"; exit 1; }
SRC=$(getent passwd "${SUDO_USER:-root}" | cut -d: -f6)
moved=0
if [ -f "$SRC/mp.sqlite" ]; then
  systemctl stop mocheqi.service
  [ -f "$DIR/data/mp.sqlite" ] && mv "$DIR/data/mp.sqlite" "$DIR/data/mp.sqlite.before-upload"
  rm -f "$DIR/data/mp.sqlite-wal" "$DIR/data/mp.sqlite-shm"
  mv "$SRC/mp.sqlite" "$DIR/data/mp.sqlite"; moved=1
  echo "✓ база перенесена"
fi
if [ -f "$SRC/config.ini" ]; then
  mv "$SRC/config.ini" "$DIR/config.ini"; moved=1
  # config.ini с компьютера не знает про сервер — возвращаем настройки [server], выбранные при установке
  if [ -f /opt/mocheqi/server.ini ]; then
    python3 - "$DIR/config.ini" /opt/mocheqi/server.ini <<'PY'
import re, sys
p, keep = sys.argv[1:]
s = open(p, encoding="utf-8-sig").read().replace("\r\n", "\n")
s = re.sub(r"(?ms)^\[server\].*?(?=^\[|\Z)", "", s).rstrip("\n")
s += "\n\n" + open(keep, encoding="utf-8").read().strip() + "\n"
open(p, "w", encoding="utf-8").write(s)
PY
  fi
  echo "✓ ключи (config.ini) перенесены"
fi
[ "$moved" = 1 ] || { echo "В папке $SRC нет ни config.ini, ни mp.sqlite — сначала загрузите их через WinSCP."; exit 1; }
chown -R mocheqi:mocheqi "$DIR/config.ini" "$DIR/data"
chmod 600 "$DIR/config.ini"
systemctl restart mocheqi.service
sleep 2
systemctl is-active --quiet mocheqi.service && echo "✓ дашборд перезапущен" || { echo "Дашборд не запустился:"; journalctl -u mocheqi -n 20 --no-pager; exit 1; }
echo "Готово. Откройте дашборд и войдите своим телефоном и паролем."
