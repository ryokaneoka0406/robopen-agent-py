#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_example="${repo_root}/deploy/grafana-cloud-alloy/grafana-cloud.env.example"

robopen_env_dir="${ROBOPEN_GRAFANA_ENV_DIR:-/etc/robopen}"
robopen_env="${ROBOPEN_GRAFANA_ENV:-${robopen_env_dir}/grafana-cloud.env}"
install_url="${GRAFANA_CLOUD_ALLOY_INSTALL_URL:-https://storage.googleapis.com/cloud-onboarding/alloy/scripts/install-linux.sh}"

if [[ "${EUID}" -ne 0 ]]; then
	echo "Run with sudo: sudo $0" >&2
	exit 1
fi

apt-get update
apt-get install -y ca-certificates curl

install -d -m 0755 "${robopen_env_dir}"
if [[ ! -f "${robopen_env}" ]]; then
	install -m 0600 "${env_example}" "${robopen_env}"
	echo "Created ${robopen_env}; paste the GCLOUD_* values from Grafana Cloud, then rerun this script."
	exit 0
fi
chmod 0600 "${robopen_env}"

if grep -Eq '<[^>]+>' "${robopen_env}"; then
	echo "${robopen_env} still contains placeholders. Replace them with the values from Grafana Cloud." >&2
	exit 0
fi

set -a
# shellcheck disable=SC1090
. "${robopen_env}"
set +a

required_vars=(
	GCLOUD_HOSTED_METRICS_ID
	GCLOUD_HOSTED_METRICS_URL
	GCLOUD_HOSTED_LOGS_ID
	GCLOUD_HOSTED_LOGS_URL
	GCLOUD_RW_API_KEY
	ARCH
)

if [[ -n "${GCLOUD_FM_URL:-}" || -n "${GCLOUD_FM_HOSTED_ID:-}" || -n "${GCLOUD_FM_POLL_FREQUENCY:-}" ]]; then
	required_vars+=(GCLOUD_FM_URL GCLOUD_FM_HOSTED_ID GCLOUD_FM_POLL_FREQUENCY)
fi

missing=()
for var_name in "${required_vars[@]}"; do
	if [[ -z "${!var_name:-}" ]]; then
		missing+=("${var_name}")
	fi
done

if (( ${#missing[@]} > 0 )); then
	printf 'Missing required Grafana Cloud environment values: %s\n' "${missing[*]}" >&2
	exit 1
fi

# Remove the old robopen-specific drop-in if this host was previously configured
# with the retired custom Alloy config.
rm -f /etc/systemd/system/alloy.service.d/robopen-grafana-cloud.conf
systemctl daemon-reload

curl -fsSL "${install_url}" | /bin/sh

if id alloy >/dev/null 2>&1 && getent group adm >/dev/null 2>&1; then
	usermod -aG adm alloy
fi

systemctl restart alloy
systemctl status alloy --no-pager
