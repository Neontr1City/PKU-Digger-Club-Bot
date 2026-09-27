#!/usr/bin/env bash
# Run once as root on a fresh Ubuntu 24.04 VM. Does not create cloud resources.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends docker.io docker-compose-v2 ca-certificates
systemctl enable --now docker
install -d -m 0750 /opt/pku-digger-club-bot
# The free 1 GiB instance benefits from a small swap file during image builds and PNG rendering.
if [ ! -e /swapfile ]; then
  fallocate -l 1G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  printf '/swapfile none swap sw 0 0\n' >> /etc/fstab
fi
