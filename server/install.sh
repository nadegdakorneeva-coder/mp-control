#!/usr/bin/env bash
# Установка дашборда Mocheqi на сервер Ubuntu (22.04 / 24.04).
# Запуск:  sudo bash install.sh
# Повторный запуск безопасен: уже сделанные шаги пропускаются, база и config.ini не трогаются.
set -euo pipefail

REPO_SSH="git@github.com:nadegdakorneeva-coder/mocheqi.git"
APP_USER="mocheqi"
HOME_DIR="/opt/mocheqi"
DIR="$HOME_DIR/dashboard"
PORT_DEFAULT=8765
TZ_NAME="Europe/Moscow"

say()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[0;32m    ✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[0;33m    ! %s\033[0m\n' "$*"; }
ask()  { local a; read -r -p "    $1 " a </dev/tty; echo "$a"; }

[ "$(id -u)" -eq 0 ] || { echo "Запустите через sudo: sudo bash install.sh"; exit 1; }

say "1/8. Пакеты"
apt-get update -qq
apt-get install -y -qq git python3 python3-openpyxl ca-certificates openssh-client >/dev/null
ok "git, python3, openpyxl"

say "2/8. Пользователь $APP_USER и папка $HOME_DIR"
if ! id "$APP_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$HOME_DIR" --create-home --shell /usr/sbin/nologin "$APP_USER"
  ok "создан системный пользователь $APP_USER (без входа по паролю)"
else ok "уже есть"; fi
install -d -o "$APP_USER" -g "$APP_USER" -m 700 "$HOME_DIR/.ssh"

say "3/8. Ключ доступа к GitHub (только чтение)"
KEY="$HOME_DIR/.ssh/id_ed25519"
if [ ! -f "$KEY" ]; then
  sudo -u "$APP_USER" ssh-keygen -q -t ed25519 -N "" -C "mocheqi-server" -f "$KEY"
fi
sudo -u "$APP_USER" bash -c "ssh-keyscan -t ed25519 github.com >> $HOME_DIR/.ssh/known_hosts 2>/dev/null; sort -u -o $HOME_DIR/.ssh/known_hosts $HOME_DIR/.ssh/known_hosts"
until sudo -u "$APP_USER" git ls-remote "$REPO_SSH" >/dev/null 2>&1; do
  echo
  echo "    Добавьте этот ключ в GitHub: репозиторий mocheqi → Settings → Deploy keys → Add deploy key"
  echo "    Title: server, галочку «Allow write access» НЕ ставить."
  echo
  echo "    ----------8<----------"
  cat "$KEY.pub"
  echo "    ----------8<----------"
  ask "Добавили? Нажмите Enter, чтобы проверить…" >/dev/null
done
ok "сервер видит репозиторий"

say "4/8. Программа"
if [ ! -d "$DIR/.git" ]; then
  sudo -u "$APP_USER" git clone -q "$REPO_SSH" "$DIR"
  ok "скачана в $DIR"
else
  sudo -u "$APP_USER" git -C "$DIR" pull -q --ff-only || true
  ok "уже скачана, обновлена"
fi
install -d -o "$APP_USER" -g "$APP_USER" -m 750 "$DIR/data"
chmod +x "$DIR/server/"*.sh

say "5/8. Адрес дашборда"
PORT=$PORT_DEFAULT
while ss -ltnH "sport = :$PORT" | grep -q . && ! systemctl is-active --quiet mocheqi 2>/dev/null; do PORT=$((PORT+1)); done
[ "$PORT" != "$PORT_DEFAULT" ] && warn "порт $PORT_DEFAULT занят другой программой — дашборд будет на порту $PORT"
DOMAIN=$(ask "Домен для дашборда (например dash.mocheqi.ru). Нет домена — просто Enter:")
NETWORK=1; MODE="ip"
if [ -n "$DOMAIN" ]; then
  if command -v nginx >/dev/null; then MODE="nginx"; NETWORK=0
  elif ! ss -ltnH '( sport = :80 or sport = :443 )' | grep -q .; then MODE="caddy"; NETWORK=0
  else warn "порты 80/443 заняты не nginx — https настроим вручную, пока открываю по IP"; fi
fi

say "6/8. Настройки (config.ini)"
CFG="$DIR/config.ini"
if [ ! -f "$CFG" ]; then
  cp "$DIR/config.example.ini" "$CFG"
  warn "config.ini создан из образца. Ключи WB/Ozon впишутся, когда вы загрузите config.ini со своего компьютера (см. инструкцию)."
fi
python3 - "$CFG" "$NETWORK" "$PORT" <<'PY'
import re, sys
p, net, port = sys.argv[1:]
s = open(p, encoding="utf-8-sig").read().replace("\r\n", "\n")
if "[server]" not in s:
    s = s.rstrip("\n") + "\n\n[server]\n"
def setv(s, k, v):
    head, sep, tail = s.partition("[server]")
    m = re.search(r"(?m)^\s*" + k + r"\s*=.*$", tail.split("\n[", 1)[0])
    if m:
        tail = tail[:m.start()] + f"{k} = {v}" + tail[m.end():]
    else:
        tail = f"\n{k} = {v}" + tail
    return head + sep + tail
s = setv(setv(s, "network", net), "port", port)
open(p, "w", encoding="utf-8").write(s)
PY
printf '[server]\nnetwork = %s\nport = %s\n' "$NETWORK" "$PORT" > "$HOME_DIR/server.ini"
chown "$APP_USER:$APP_USER" "$CFG"; chmod 600 "$CFG"
ok "network=$NETWORK, port=$PORT"

say "7/8. Службы и расписание"
SYS=/etc/systemd/system
cat > $SYS/mocheqi.service <<UNIT
[Unit]
Description=Mocheqi dashboard (WB + Ozon)
After=network-online.target
Wants=network-online.target
[Service]
User=$APP_USER
WorkingDirectory=$DIR/app
Environment=TZ=$TZ_NAME PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 server.py --no-browser
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT

job() {  # имя, описание, команда, расписание (OnCalendar, можно несколько через ;), [от root]
  local name=$1 desc=$2 cmd=$3 cal=$4 user=${5:-$APP_USER}
  cat > $SYS/mocheqi-$name.service <<UNIT
[Unit]
Description=Mocheqi: $desc
[Service]
Type=oneshot
User=$user
WorkingDirectory=$DIR
Environment=TZ=$TZ_NAME PYTHONUNBUFFERED=1
ExecStart=/usr/bin/flock -n /tmp/mocheqi-$name.lock $cmd
TimeoutStartSec=3h
UNIT
  { echo "[Unit]"; echo "Description=Mocheqi: $desc (расписание)"; echo "[Timer]"
    IFS=';' read -ra C <<< "$cal"; for c in "${C[@]}"; do echo "OnCalendar=$c $TZ_NAME"; done
    echo "Persistent=false"; echo "[Install]"; echo "WantedBy=timers.target"; } > $SYS/mocheqi-$name.timer
}
job daily   "ночная загрузка данных"            "/usr/bin/python3 app/collector.py"            "*-*-* 05:00:00"
job prices  "цены и статусы поставок"          "/usr/bin/python3 app/collector.py --prices"   "*-*-* 10:00:00;*-*-* 14:00:00;*-*-* 18:00:00"
job today   "заказы за сегодня"                "/usr/bin/python3 app/collector.py --today"    "*-*-* 07..23:00,30:00"
job backup  "резервная копия базы"             "/usr/bin/python3 server/backup.py"            "*-*-* 03:30:00"
job update  "проверка обновлений на GitHub"    "$DIR/server/update.sh"                         "*:0/5" root

systemctl daemon-reload
systemctl enable --now mocheqi.service >/dev/null
for t in daily prices today backup update; do systemctl enable --now mocheqi-$t.timer >/dev/null; done
ok "дашборд запущен; загрузки 05:00, цены/поставки 10/14/18, заказы каждые 30 мин 07–23:30, копия базы 03:30, обновления каждые 5 мин"

say "8/8. Доступ из интернета"
URL="http://$(hostname -I | awk '{print $1}'):$PORT/"
case $MODE in
  nginx)
    cat > /etc/nginx/sites-available/mocheqi <<NG
server {
    listen 80;
    server_name $DOMAIN;
    client_max_body_size 20m;
    location / {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$remote_addr;
        proxy_read_timeout 300s;
    }
}
NG
    ln -sf /etc/nginx/sites-available/mocheqi /etc/nginx/sites-enabled/mocheqi
    nginx -t && systemctl reload nginx
    if ! command -v certbot >/dev/null; then apt-get install -y -qq certbot python3-certbot-nginx >/dev/null; fi
    certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email --redirect \
      && URL="https://$DOMAIN/" || { warn "https не получен (домен уже указывает на этот сервер?). Пока работает http://$DOMAIN/"; URL="http://$DOMAIN/"; }
    ;;
  caddy)
    apt-get install -y -qq caddy >/dev/null
    printf '%s {\n    reverse_proxy 127.0.0.1:%s\n}\n' "$DOMAIN" "$PORT" > /etc/caddy/Caddyfile
    systemctl restart caddy
    URL="https://$DOMAIN/"
    ;;
  ip)
    if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then ufw allow "$PORT/tcp" >/dev/null; ok "порт $PORT открыт в ufw"; fi
    warn "без домена дашборд работает по http (без шифрования). Для постоянной работы лучше подключить домен."
    ;;
esac
systemctl restart mocheqi.service

cat <<DONE

==================================================================
  Готово.  Дашборд:  $URL
  Вход — телефон и пароль, как на компьютере (после переноса базы).

  Дальше: загрузите через WinSCP в свою домашнюю папку на сервере
  два файла с компьютера (D:\\MP\\dashboard):  config.ini  и  data\\mp.sqlite
  и выполните:  sudo bash $DIR/server/after_upload.sh
==================================================================
DONE
