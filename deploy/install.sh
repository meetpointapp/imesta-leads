#!/usr/bin/env bash
# Kakao CRM (imesta-leads) — sunucu kurulumu / güncellemesi
# Kullanım (root olarak):  bash /opt/kakaocrm/deploy/install.sh
# Tekrar çalıştırmak güvenlidir: kodu GitHub'dan günceller, verilere ve şifreye dokunmaz.
# Yerel verileri ilk kez taşımak için /root/kakaocrm-leads.db ve /root/kakaocrm-config.json dosyalarını önceden yükleyin.
set -euo pipefail

APP="kakaocrm"
APP_DIR="/opt/${APP}"
DATA_DIR="/var/lib/${APP}"
ENV_FILE="/etc/${APP}.env"
APP_USER="${APP}"
PORT="${PORT:-3080}"
BASE_PATH="/kakaocrm"
REPO="https://github.com/meetpointapp/imesta-leads.git"
NEIGHBOR="imesta-operasyon-proxy.conf"   # kahveotoritesi.com sitesinde zaten olan panelin parçası

c_ok(){ printf "\e[32m✔ %s\e[0m\n" "$*"; }
c_info(){ printf "\e[36m➜ %s\e[0m\n" "$*"; }
c_warn(){ printf "\e[33m⚠ %s\e[0m\n" "$*"; }
die(){ printf "\e[31m✘ %s\e[0m\n" "$*"; exit 1; }

[ "$(id -u)" -eq 0 ] || die "root olarak çalıştırın."

# ---------- 1) Python ve git ----------
command -v git >/dev/null 2>&1 || { c_info "git kuruluyor…"; apt-get install -y git >/dev/null; }
command -v python3 >/dev/null 2>&1 || { c_info "python3 kuruluyor…"; apt-get install -y python3 >/dev/null; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || die "Python 3.10 veya üstü gerekli. Mevcut: $(python3 -V)"
c_ok "$(python3 -V) uygun"

# ---------- 2) Kod ----------
if [ -d "${APP_DIR}/.git" ]; then
  c_info "Kod güncelleniyor…"; git -C "$APP_DIR" pull --ff-only -q
else
  c_info "Kod indiriliyor…"; git clone -q "$REPO" "$APP_DIR"
fi
c_ok "Sürüm: $(git -C "$APP_DIR" log -1 --format='%h %s' | cut -c1-70)"

# ---------- 3) Kullanıcı, veri, ayarlar ----------
id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin "$APP_USER"
mkdir -p "$DATA_DIR/backups"
if [ -f /root/kakaocrm-leads.db ]; then
  if [ -f "$DATA_DIR/leads.db" ]; then
    cp "$DATA_DIR/leads.db" "$DATA_DIR/backups/leads-sunucu-oncesi-$(date +%Y%m%d-%H%M%S).db"
    c_warn "Sunucudaki eski veritabanı yedeklendi, yüklediğiniz dosyayla değiştiriliyor."
  fi
  mv /root/kakaocrm-leads.db "$DATA_DIR/leads.db"; c_ok "Veritabanı yüklendi"
fi
if [ -f /root/kakaocrm-config.json ]; then mv /root/kakaocrm-config.json "$DATA_DIR/config.json"; c_ok "Firma/imza ayarları yüklendi"; fi
[ -f "$DATA_DIR/config.json" ] || cp "$APP_DIR/config.json" "$DATA_DIR/config.json"
chown -R "$APP_USER:$APP_USER" "$DATA_DIR"; chmod 750 "$DATA_DIR"

FIRST=0
if [ ! -f "$ENV_FILE" ]; then
  FIRST=1
  PW="$(python3 -c 'import secrets; print(secrets.token_urlsafe(12))')"
  cat > "$ENV_FILE" <<EOF
BASE_PATH=${BASE_PATH}
WEB_PASSWORD=${PW}
LEADS_DB=${DATA_DIR}/leads.db
LEADS_CONFIG=${DATA_DIR}/config.json
LEADS_SECRETS=${DATA_DIR}/secrets.json
PYTHONUTF8=1
TZ=Europe/Istanbul
PORT=${PORT}
EOF
  chmod 600 "$ENV_FILE"
fi
PORT="$(grep -E '^PORT=' "$ENV_FILE" | cut -d= -f2)"
PW="$(grep -E '^WEB_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)"

owner="$(ss -ltnp 2>/dev/null | awk -v p=":${PORT}\$" '$4 ~ p {print $NF}' | head -1 || true)"
if [ -n "$owner" ] && ! echo "$owner" | grep -q python; then die "${PORT} portu başka bir programda (${owner}). PORT=başka_port ile tekrar çalıştırın."; fi

# ---------- 4) systemd servisi ----------
cat > /etc/systemd/system/${APP}.service <<EOF
[Unit]
Description=Kakao CRM (imesta-leads)
After=network.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${DATA_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=$(command -v python3) ${APP_DIR}/web.py --port ${PORT}
Restart=always
RestartSec=3
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=true
PrivateTmp=true
ReadWritePaths=${DATA_DIR}

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable ${APP} >/dev/null 2>&1
systemctl restart ${APP}
sleep 3
code="$(curl -s -o /dev/null -w '%{http_code}' -u "imesta:${PW}" "http://127.0.0.1:${PORT}${BASE_PATH}/" || true)"
if [ "$code" = "200" ]; then c_ok "Servis çalışıyor (port ${PORT})"
else journalctl -u ${APP} -n 30 --no-pager; die "Servis başlatılamadı (HTTP ${code}); yukarıdaki kayıtlara bakın."; fi

# ---------- 5) nginx: /kakaocrm yolunu kahveotoritesi.com sitesine ekle ----------
cat > /etc/nginx/snippets/${APP}-proxy.conf <<EOF
# Kakao CRM → http://127.0.0.1:${PORT}
location = ${BASE_PATH} { return 301 ${BASE_PATH}/; }
location ${BASE_PATH}/ {
    proxy_pass http://127.0.0.1:${PORT};
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Forwarded-For \$remote_addr;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_read_timeout 120s;
    client_max_body_size 20m;
}
EOF
FILES="$(grep -rlsF "snippets/${NEIGHBOR}" /etc/nginx/sites-enabled /etc/nginx/conf.d 2>/dev/null || true)"
[ -n "$FILES" ] || die "kahveotoritesi.com nginx sitesi bulunamadı (${NEIGHBOR} içeren dosya yok). Değişiklik yapılmadı."
declare -A BAKS=()
for f in $FILES; do
  real="$(readlink -f "$f")"
  if grep -qsF "snippets/${APP}-proxy.conf" "$real"; then c_ok "nginx: ${real} zaten ekli"; continue; fi
  bak="${DATA_DIR}/backups/nginx-$(basename "$real")-$(date +%s).bak"; cp "$real" "$bak"; BAKS["$real"]="$bak"
  # Operasyon panelinin include satırının hemen altına aynı girintiyle ekle (80 ve 443 blokları)
  awk -v n="snippets/${NEIGHBOR}" -v a="snippets/${APP}-proxy.conf" '{print} index($0, n){sub(/include.*/, "include /etc/nginx/" a ";"); print}' "$bak" > "$real"
  c_ok "nginx: ${real} dosyasına /kakaocrm eklendi (eski hali: ${bak})"
done
if nginx -t >/dev/null 2>&1; then
  systemctl reload nginx; c_ok "nginx yeniden yüklendi"
else
  nginx -t || true
  for real in "${!BAKS[@]}"; do cp "${BAKS[$real]}" "$real"; done
  nginx -t >/dev/null 2>&1 && systemctl reload nginx || true
  die "nginx testi başarısız; değişiklik geri alındı. Diğer sitelere (vibeupme, operasyon paneli) dokunulmadı."
fi

# ---------- 6) Günlük yedek (son 14 gün) ----------
cat > /etc/cron.daily/${APP}-yedek <<EOF
#!/bin/sh
# Kakao CRM: günlük veritabanı yedeği → ${DATA_DIR}/backups
cd ${APP_DIR} && runuser -u ${APP_USER} -- env LEADS_DB=${DATA_DIR}/leads.db $(command -v python3) -c 'import leads; leads.backup_db()'
EOF
chmod 755 /etc/cron.daily/${APP}-yedek
c_ok "Günlük otomatik yedek ayarlandı"

# ---------- 7) Özet ----------
echo
echo "═══════════════════════════════════════════════════════════"
echo "  Kakao CRM hazır:  https://kahveotoritesi.com${BASE_PATH}/"
echo "  Kullanıcı adı:    imesta"
if [ "$FIRST" = "1" ]; then echo "  Şifre:            ${PW}   (bir yere not edin)"
else echo "  Şifre:            değişmedi (görmek için: grep WEB_PASSWORD ${ENV_FILE})"; fi
echo "  Veriler:          ${DATA_DIR}  (günlük yedek: ${DATA_DIR}/backups)"
echo "  Servis:           systemctl status ${APP}  |  Kayıtlar: journalctl -u ${APP} -f"
echo "═══════════════════════════════════════════════════════════"
