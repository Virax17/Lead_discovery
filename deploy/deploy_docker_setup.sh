#!/usr/bin/env bash
# One-time prep of the EC2 host (Ubuntu 24.04) for Docker-based deploys.
# Run:  scp -i <key>.pem deploy/deploy_docker_setup.sh ubuntu@<EIP>:~/
#       ssh -i <key>.pem ubuntu@<EIP> "sudo bash ~/deploy_docker_setup.sh"
#
# It does NOT stop the old systemd service and writes no secrets. The first
# GitHub Actions deploy hands port 8001 over from systemd to the container.
set -euo pipefail

APP_DIR=/opt/lead-discovery

echo "== 2 GB swap (t3.micro has 1 GB RAM) =="
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "== Docker Engine + compose plugin =="
if ! command -v docker >/dev/null; then
  apt-get update
  apt-get install -y ca-certificates curl
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker
usermod -aG docker ubuntu

echo "== App directory =="
mkdir -p "$APP_DIR/exports"
# the container runs as uid 1000 and writes exports here
chown -R 1000:1000 "$APP_DIR/exports"

if [ ! -f "$APP_DIR/.env" ]; then
  echo "!! $APP_DIR/.env is missing - create it (see backend/.env.example) before the first deploy" >&2
fi

echo "== Next steps =="
cat <<'EOF'
1. Make sure /opt/lead-discovery/.env has every key in backend/.env.example
   (incl. GROQ_API_KEY / SERPER_API_KEY once the enrichment PR is merged).
2. Add GitHub repo secrets: EC2_HOST (Elastic IP), EC2_USER (ubuntu), EC2_SSH_KEY (.pem contents).
3. Push to master (or run the "Deploy backend" workflow). The first run stops
   lead-discovery.service and starts the container on 127.0.0.1:8001.
4. Rollback: sudo systemctl enable --now lead-discovery  (after `docker compose down`).
EOF
