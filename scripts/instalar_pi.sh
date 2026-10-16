#!/usr/bin/env bash
# Instala/atualiza o Projeto Agenda no Raspberry Pi (pode rodar quantas vezes quiser).
#   cd ~/projeto-agenda && ./scripts/instalar_pi.sh
# Faz: venv + dependências, serviço systemd (porta 8090, só localhost), backup diário.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
USUARIO="$(whoami)"
cd "$REPO"

echo "==> Repo: $REPO (usuário $USUARIO)"

# 1. Pacotes do sistema (venv)
if ! python3 -c "import ensurepip" 2>/dev/null; then
	echo "==> Instalando python3-venv"
	sudo apt-get update -qq && sudo apt-get install -y python3-venv
fi

# 2. Ambiente virtual e dependências (só as de produção)
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install --upgrade pip -q
grep -vE '^(pytest|httpx2)' requirements.txt | grep -vE '^\s*#|^\s*$' > /tmp/agenda-req.txt
echo "==> Instalando dependências (no Pi 3 pode levar alguns minutos)"
.venv/bin/pip install -q -r /tmp/agenda-req.txt
mkdir -p data/backups

# 3. Units do systemd (copiadas com usuário e caminho preenchidos)
for unit in agenda.service agenda-backup.service agenda-backup.timer; do
	sed -e "s|__REPO__|$REPO|g" -e "s|__USUARIO__|$USUARIO|g" "deploy/$unit" | sudo tee "/etc/systemd/system/$unit" > /dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable --now agenda.service agenda-backup.timer
sudo systemctl restart agenda.service

# 4. Conferência
echo "==> Aguardando o app subir"
for _ in $(seq 1 30); do
	if curl -fsS http://127.0.0.1:8090/api/saude > /dev/null 2>&1; then
		echo "==> OK: app respondendo em http://127.0.0.1:8090"
		break
	fi
	sleep 1
done
curl -fsS http://127.0.0.1:8090/api/saude > /dev/null || { echo "!! O app não respondeu. Veja: journalctl -u agenda -n 50 --no-pager"; exit 1; }

if command -v tailscale > /dev/null; then
	echo "==> Tailscale: $(tailscale status --self --peers=false 2>/dev/null | head -1 || true)"
	echo "    Se ainda não fez: sudo tailscale serve --bg 8090"
else
	echo "==> Tailscale ainda não instalado (veja o README, seção Deploy no Pi)."
fi
