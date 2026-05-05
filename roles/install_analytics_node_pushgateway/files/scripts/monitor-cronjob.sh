#!/bin/bash
#===============================================================================
#
#  monitor-job.sh - A universal monitoring wrapper for cron/batch jobs.
#
#  This script runs a given command, measures its execution time and exit status,
#  then pushes metrics to a Prometheus PushGateway.
#
#  It reports:
#    - job_status (1 for success, 0 for failure)
#    - job_duration_seconds (runtime in seconds)
#    - job_last_run_timestamp (Unix timestamp when the job started)
#
#  Environment variables can be loaded from a Bash config file via the
#  --config-file flag (or from a default monitor-cronjob.conf if it exists).
#  The config file is sourced natively by Bash, so it must use shell syntax
#  (e.g. KEY=value, with quoting as needed). Values loaded from the config
#  file are used as defaults, but any flags provided on the command line
#  will override them.
#
#  Usage:
#    ./monitor-job.sh [options] -- <command>
#
#  Options:
#    -c, --config-file FILE  Path to a Bash config file (default: monitor-cronjob.conf if exists)
#    -p, --pushgateway URL   Set the PushGateway URL (default: http://localhost:9091)
#    -u, --user USER         Set the basic auth username (optional)
#    -w, --pass PASS         Set the basic auth password (optional)
#    -n, --job-name NAME     Set the job name (default: default_job)
#    -i, --instance NAME     Set the instance name (default: hostname)
#    -t, --timeout SECONDS   Set a timeout for the command (optional)
#    -h, --help              Display this help message
#
#===============================================================================

set -euo pipefail

# Resolve the directory of this script so the default config is found
# next to the script itself, regardless of the current working directory.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
DEFAULT_CONFIG_FILE="${SCRIPT_DIR}/monitor-cronjob.conf"

# --- Function to load variables from a Bash config file ---
load_config() {
  local filePath="${1:-$DEFAULT_CONFIG_FILE}"

  if [ ! -f "$filePath" ]; then
    echo "Error: missing ${filePath}"
    exit 1
  fi

  echo "Sourcing ${filePath}"
  # shellcheck disable=SC1090
  source "$filePath"
}

# --- Manually extract the config-file option ---
CONFIG_FILE_ARG=""
ARGS=()
SKIP=0
for arg in "$@"; do
  if [ $SKIP -eq 1 ]; then
    CONFIG_FILE_ARG="$arg"
    SKIP=0
    continue
  fi
  case "$arg" in
    -c|--config-file)
      SKIP=1
      ;;
    *)
      ARGS+=("$arg")
      ;;
  esac
done

# Load the config file if provided, or use the default config next to the
# script if it exists.
if [ -n "$CONFIG_FILE_ARG" ]; then
  load_config "$CONFIG_FILE_ARG"
elif [ -f "$DEFAULT_CONFIG_FILE" ]; then
  load_config "$DEFAULT_CONFIG_FILE"
fi

# Reset positional parameters without the config-file option.
set -- "${ARGS[@]}"

# --- Set default variables using any values loaded from the env file ---
: "${PUSHGATEWAY_URL:=http://localhost:9091}"
: "${PUSHGATEWAY_USER:=}"
: "${PUSHGATEWAY_PASS:=}"
: "${JOB_NAME:=default_job}"
: "${INSTANCE:=$(hostname)}"
: "${TIMEOUT:=}"
: "${METRIC_PREFIX:=job}"

# --- Now use getopt to parse the remaining flags (override defaults) ---
TEMP=$(getopt -o p:u:w:n:i:t:h -l pushgateway:,user:,pass:,job-name:,instance:,timeout:,help -n "$0" -- "$@")
if [ $? != 0 ]; then
  echo "Error in command line arguments." >&2
  exit 1
fi
eval set -- "$TEMP"

# Parse remaining command-line options; these override the defaults.
while true; do
  case "$1" in
    -p|--pushgateway)
      PUSHGATEWAY_URL="$2"
      shift 2 ;;
    -u|--user)
      PUSHGATEWAY_USER="$2"
      shift 2 ;;
    -w|--pass)
      PUSHGATEWAY_PASS="$2"
      shift 2 ;;
    -n|--job-name)
      JOB_NAME="$2"
      shift 2 ;;
    -i|--instance)
      INSTANCE="$2"
      shift 2 ;;
    -t|--timeout)
      TIMEOUT="$2"
      shift 2 ;;
    -h|--help)
      cat <<EOF
Usage: $0 [options] -- <command>
Options:
  -c, --config-file FILE  Path to a Bash config file (default: monitor-cronjob.conf if exists)
  -p, --pushgateway URL   Set the PushGateway URL (default: ${PUSHGATEWAY_URL})
  -u, --user USER         Set basic auth username for PushGateway (optional)
  -w, --pass PASS         Set basic auth password for PushGateway (optional)
  -n, --job-name NAME     Set the job name (default: ${JOB_NAME})
  -i, --instance NAME     Set the instance name (default: ${INSTANCE})
  -t, --timeout SECONDS   Set timeout (in seconds) for the command (optional)
  -h, --help              Display this help message
EOF
      exit 0 ;;
    --)
      shift
      break ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1 ;;
  esac
done

# Ensure a command is provided after the "--"
if [ "$#" -eq 0 ]; then
  echo "Error: No command provided to execute."
  exit 1
fi

# The command to run is all the remaining arguments.
CMD=("$@")

# Record the start time (high resolution) and the Unix timestamp.
START_TIME=$(date +%s.%N)
START_TIME_INT=$(date +%s)

# Execute the command (with timeout if specified)
if [ -n "$TIMEOUT" ]; then
  timeout "$TIMEOUT" "${CMD[@]}"
  EXIT_CODE=$?
else
  "${CMD[@]}"
  EXIT_CODE=$?
fi

# Record the end time and calculate the duration.
END_TIME=$(date +%s.%N)
DURATION=$(echo "$END_TIME - $START_TIME" | bc)

# Set job_status: 1 if success, 0 otherwise.
if [ "$EXIT_CODE" -eq 0 ]; then
  JOB_STATUS=1
else
  JOB_STATUS=0
fi

# Prepare the metrics in Prometheus text exposition format.
METRICS=$(cat <<EOF
# TYPE ${METRIC_PREFIX}_status gauge
${METRIC_PREFIX}_status{job="${JOB_NAME}",instance="${INSTANCE}"} ${JOB_STATUS}
# TYPE ${METRIC_PREFIX}_duration_seconds gauge
${METRIC_PREFIX}_duration_seconds{job="${JOB_NAME}",instance="${INSTANCE}"} ${DURATION}
# TYPE ${METRIC_PREFIX}_last_run_timestamp gauge
${METRIC_PREFIX}_last_run_timestamp{job="${JOB_NAME}",instance="${INSTANCE}"} ${START_TIME_INT}
EOF
)

# URL-encode label values so spaces and special characters in JOB_NAME or
# INSTANCE don't produce a malformed PushGateway URL.
url_encode() {
  local s="$1" out="" i c
  for (( i=0; i<${#s}; i++ )); do
    c="${s:i:1}"
    case "$c" in
      [a-zA-Z0-9.~_-]) out+="$c" ;;
      *) printf -v c '%%%02X' "'$c"; out+="$c" ;;
    esac
  done
  printf '%s' "$out"
}
JOB_NAME_ENC=$(url_encode "$JOB_NAME")
INSTANCE_ENC=$(url_encode "$INSTANCE")
PUSH_URL="${PUSHGATEWAY_URL}/metrics/job/${JOB_NAME_ENC}/instance/${INSTANCE_ENC}"

# Optionally, print the metrics for debugging.
echo "Pushing the following metrics to ${PUSH_URL}:"
echo "$METRICS"

# Build the curl command to push metrics.
CURL_CMD=(curl --silent --show-error --fail --data-binary @- "${PUSH_URL}")

# Add basic auth if provided.
if [ -n "$PUSHGATEWAY_USER" ] && [ -n "$PUSHGATEWAY_PASS" ]; then
  CURL_CMD+=(--user "${PUSHGATEWAY_USER}:${PUSHGATEWAY_PASS}")
fi

# Push the metrics to the PushGateway.
echo "$METRICS" | "${CURL_CMD[@]}"

# Exit with the same status as the executed command.
exit $EXIT_CODE
