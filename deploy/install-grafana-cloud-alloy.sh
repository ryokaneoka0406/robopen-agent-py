#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
alloy_src="${repo_root}/deploy/grafana-cloud-alloy/config.alloy"
env_example="${repo_root}/deploy/grafana-cloud-alloy/grafana-cloud.env.example"

alloy_config="${ALLOY_CONFIG:-/etc/alloy/config.alloy}"
robopen_env_dir="${ROBOPEN_GRAFANA_ENV_DIR:-/etc/robopen}"
robopen_env="${ROBOPEN_GRAFANA_ENV:-${robopen_env_dir}/grafana-cloud.env}"
dropin_dir="/etc/systemd/system/alloy.service.d"
dropin_file="${dropin_dir}/robopen-grafana-cloud.conf"

if [[ "${EUID}" -ne 0 ]]; then
	echo "Run with sudo: sudo $0" >&2
	exit 1
fi

if [[ ! -f "${alloy_src}" ]]; then
	echo "Missing Alloy config template: ${alloy_src}" >&2
	exit 1
fi

apt-get update
apt-get install -y gpg wget

mkdir -p /etc/apt/keyrings
wget -O /etc/apt/keyrings/grafana.asc https://apt.grafana.com/gpg-full.key
chmod 0644 /etc/apt/keyrings/grafana.asc
echo "deb [signed-by=/etc/apt/keyrings/grafana.asc] https://apt.grafana.com stable main" \
	> /etc/apt/sources.list.d/grafana.list

apt-get update
apt-get install -y alloy

install -d -m 0755 /etc/alloy
install -m 0644 "${alloy_src}" "${alloy_config}"

install -d -m 0755 "${robopen_env_dir}"
if [[ ! -f "${robopen_env}" ]]; then
	install -m 0600 "${env_example}" "${robopen_env}"
	echo "Created ${robopen_env}; edit it with your Grafana Cloud URLs, user IDs, and token."
fi
chmod 0600 "${robopen_env}"

install -d -m 0755 "${dropin_dir}"
cat > "${dropin_file}" <<EOF
[Service]
EnvironmentFile=${robopen_env}
EOF

systemctl daemon-reload
alloy fmt --test "${alloy_config}"

if grep -q "<grafana-cloud-access-policy-token>" "${robopen_env}"; then
	echo "Alloy is installed, but ${robopen_env} still contains placeholders."
	echo "Edit ${robopen_env}, then run: sudo systemctl enable --now alloy"
	exit 0
fi

set -a
# shellcheck disable=SC1090
. "${robopen_env}"
set +a

alloy validate "${alloy_config}"
systemctl enable --now alloy
systemctl status alloy --no-pager
