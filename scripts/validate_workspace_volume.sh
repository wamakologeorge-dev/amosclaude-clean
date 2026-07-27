#!/usr/bin/env bash
set -Eeuo pipefail

MOUNT_DIR="${1:-/mnt/amosclaud-volumes/amosclaud-20tb}"
EXPECTED_GIB="${2:-20480}"
TEST_GIB="${3:-10}"
TEST_FILE="${MOUNT_DIR}/.amosclaud-volume-validation.fio"

cleanup() {
  rm -f -- "$TEST_FILE"
}
trap cleanup EXIT INT TERM

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ "$MOUNT_DIR" = /* ]] || fail "mount point must be an absolute path"
[[ "$EXPECTED_GIB" =~ ^[0-9]+$ ]] || fail "expected capacity must be an integer GiB value"
[[ "$TEST_GIB" =~ ^[0-9]+$ ]] || fail "test size must be an integer GiB value"
(( EXPECTED_GIB >= 10 && EXPECTED_GIB <= 65536 )) || fail "expected capacity must be between 10 and 65536 GiB"
(( TEST_GIB >= 1 && TEST_GIB <= 100 )) || fail "fio validation size must be between 1 and 100 GiB"

for command in findmnt lsblk df fio sync; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is unavailable: $command"
done

findmnt --mountpoint "$MOUNT_DIR" >/dev/null 2>&1 || fail "$MOUNT_DIR is not a mounted filesystem"
SOURCE="$(findmnt --noheadings --output SOURCE --target "$MOUNT_DIR" | xargs)"
FSTYPE="$(findmnt --noheadings --output FSTYPE --target "$MOUNT_DIR" | xargs)"
[[ "$SOURCE" = /dev/* ]] || fail "mount source is not a directly attached block device"
[[ "$FSTYPE" = "ext4" || "$FSTYPE" = "xfs" ]] || fail "unsupported filesystem: $FSTYPE"

ACTUAL_BYTES="$(df --block-size=1 --output=size "$MOUNT_DIR" | tail -n 1 | xargs)"
[[ "$ACTUAL_BYTES" =~ ^[0-9]+$ ]] || fail "unable to determine mounted filesystem capacity"
EXPECTED_BYTES=$((EXPECTED_GIB * 1024 * 1024 * 1024))
MINIMUM_BYTES=$((EXPECTED_BYTES * 97 / 100))
(( ACTUAL_BYTES >= MINIMUM_BYTES )) || fail "filesystem exposes ${ACTUAL_BYTES} bytes; expected at least ${MINIMUM_BYTES}"

printf '=== Amosclaud large-volume validation ===\n'
printf 'Mount point: %s\n' "$MOUNT_DIR"
printf 'Source: %s\n' "$SOURCE"
printf 'Filesystem: %s\n' "$FSTYPE"
printf 'Expected capacity: %s GiB\n' "$EXPECTED_GIB"
printf 'Visible capacity: %s bytes\n' "$ACTUAL_BYTES"
findmnt --target "$MOUNT_DIR"
lsblk --bytes --output NAME,PATH,SIZE,TYPE,FSTYPE,MOUNTPOINTS "$SOURCE"
df -hT "$MOUNT_DIR"

FREE_BYTES="$(df --block-size=1 --output=avail "$MOUNT_DIR" | tail -n 1 | xargs)"
TEST_BYTES=$((TEST_GIB * 1024 * 1024 * 1024))
(( FREE_BYTES > TEST_BYTES + 1073741824 )) || fail "not enough free space for a ${TEST_GIB} GiB validation file"

printf '\n=== fio direct-I/O integrity and throughput test (%s GiB) ===\n' "$TEST_GIB"
fio \
  --name=amosclaud-integrity \
  --filename="$TEST_FILE" \
  --size="${TEST_GIB}G" \
  --rw=write \
  --bs=1M \
  --iodepth=16 \
  --direct=1 \
  --verify=sha256 \
  --do_verify=1 \
  --verify_fatal=1 \
  --fsync_on_close=1 \
  --group_reporting

sync
printf '\n=== Validation completed ===\n'
printf 'The filesystem capacity, direct writes, read-back verification, and cleanup all completed successfully.\n'
