#!/usr/bin/python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT

DOCUMENTATION = r"""
module: wait_for_apt_lock
short_description: Wait until APT/dpkg is no longer used by anything else
description:
  - Waits while the dpkg/APT locks are held, or while unattended-upgrades,
    apt.systemd.daily, the apt-daily systemd units or cloud-init package
    stages are running.
  - Lock holders are read from /proc/locks (fcntl and OFD locks, the kind dpkg
    and APT take), so neither fuser nor lsof is needed.
  - Once APT has been seen busy, it must stay idle for I(settle) seconds before
    it counts as free. That covers the short gaps between C(apt-get update) and
    C(apt-get upgrade) inside apt.systemd.daily and cloud-init.
  - Optionally runs C(dpkg --configure -a) when an earlier dpkg run was
    interrupted, for example by a reboot in the middle of unattended-upgrades.
  - Never reports changed for waiting, only for the dpkg repair.
options:
  timeout:
    description: Seconds to wait at most. 0 checks once without waiting.
    type: int
    default: 1800
  settle:
    description: Seconds APT must stay idle after it was seen busy.
    type: int
    default: 15
  interval:
    description: Seconds between checks.
    type: int
    default: 5
  fail_on_timeout:
    description: Fail on timeout. When false, return C(busy=true) instead.
    type: bool
    default: true
  cloud_init:
    description: Also treat running cloud-init config/final stages as busy.
    type: bool
    default: true
  repair:
    description: Run C(dpkg --configure -a) when dpkg was interrupted.
    type: bool
    default: true
"""

RETURN = r"""
busy:
  description: True when APT was still busy at the end (timeout).
  type: bool
reasons:
  description: Why APT was busy at the last busy check.
  type: list
waited:
  description: Seconds spent waiting.
  type: float
repaired:
  description: True when C(dpkg --configure -a) was run.
  type: bool
"""

import os
import time

from ansible.module_utils.basic import AnsibleModule

DPKG_DIR = "/var/lib/dpkg"
LOCK_FILES = (
    "/var/lib/dpkg/lock-frontend",
    "/var/lib/dpkg/lock",
    "/var/lib/apt/lists/lock",
    "/var/cache/apt/archives/lock",
)
# Exact basenames: unattended-upgrade-shutdown (the always-running
# unattended-upgrades.service helper) must not match
BUSY_PROGRAMS = ("unattended-upgrade", "apt.systemd.daily")
APT_UNITS = ("apt-daily.service", "apt-daily-upgrade.service")


def _read(path):
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except (IOError, OSError):
        return None


def _comm(pid):
    data = _read("/proc/%s/comm" % pid)
    return data.decode("utf-8", "replace").strip() if data else "?"


def lock_holders():
    """Return 'path held by comm[pid]' for every held APT/dpkg lock."""
    wanted = {}
    for path in LOCK_FILES:
        try:
            st = os.stat(path)
        except OSError:
            continue
        wanted[(os.major(st.st_dev), os.minor(st.st_dev), st.st_ino)] = path

    data = _read("/proc/locks")
    if not wanted or data is None:
        return []

    found = []
    for line in data.decode("utf-8", "replace").splitlines():
        # "1: POSIX  ADVISORY  WRITE 1234 08:01:5678 0 EOF"; blocked waiters
        # carry an extra "->" and are not holders
        fields = line.split()
        if len(fields) < 6 or fields[1] == "->":
            continue
        try:
            major, minor, inode = fields[5].split(":")
            key = (int(major, 16), int(minor, 16), int(inode))
        except ValueError:
            continue
        if key in wanted:
            pid = fields[4]
            who = "%s[%s]" % (_comm(pid), pid) if pid.isdigit() else "an open file description"
            found.append("%s held by %s" % (wanted[key], who))
    return sorted(set(found))


def busy_processes(cloud_init):
    found = []
    me = str(os.getpid())
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or pid == me:
            continue
        raw = _read("/proc/%s/cmdline" % pid)
        if not raw:
            continue
        argv = [arg.decode("utf-8", "replace") for arg in raw.split(b"\0") if arg]
        names = [os.path.basename(arg) for arg in argv[:2]]
        for program in BUSY_PROGRAMS:
            if program in names:
                found.append("%s[%s] is running" % (program, pid))
        # The config and final stages are the ones that install packages
        if cloud_init and "cloud-init" in names and "modules" in argv:
            found.append("cloud-init[%s] (%s) is running" % (pid, " ".join(argv[-2:])))
    return sorted(set(found))


def busy_units(module):
    systemctl = module.get_bin_path("systemctl")
    if not systemctl:
        return []
    found = []
    rc, out, _ = module.run_command(
        [systemctl, "show", "--property=Id,ActiveState,Job"] + list(APT_UNITS)
    )
    if rc != 0:
        return []
    # One block of key=value lines per unit, separated by blank lines
    for block in out.strip().split("\n\n"):
        props = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
        unit = props.get("Id", "?")
        state = props.get("ActiveState", "")
        if state in ("active", "activating", "deactivating", "reloading"):
            found.append("%s is %s" % (unit, state))
        elif props.get("Job"):
            found.append("%s has a queued job" % unit)
    return found


def probe(module):
    return (
        lock_holders()
        + busy_processes(module.params["cloud_init"])
        + busy_units(module)
    )


def dpkg_interrupted():
    try:
        entries = os.listdir(os.path.join(DPKG_DIR, "updates"))
    except OSError:
        return False
    return any(name.isdigit() for name in entries)


def main():
    module = AnsibleModule(
        argument_spec=dict(
            timeout=dict(type="int", default=1800),
            settle=dict(type="int", default=15),
            interval=dict(type="int", default=5),
            fail_on_timeout=dict(type="bool", default=True),
            cloud_init=dict(type="bool", default=True),
            repair=dict(type="bool", default=True),
        ),
        supports_check_mode=True,
    )
    params = module.params
    result = dict(changed=False, busy=False, reasons=[], waited=0.0, repaired=False)

    if not os.path.isdir(DPKG_DIR):
        result["msg"] = "Not a dpkg-based system, nothing to wait for"
        module.exit_json(**result)

    start = time.monotonic()
    interval = max(1, params["interval"])
    seen_busy = False
    idle_since = None

    while True:
        reasons = probe(module)
        now = time.monotonic()
        if reasons:
            seen_busy = True
            idle_since = None
            result["reasons"] = reasons
        else:
            if idle_since is None:
                idle_since = now
            # Idle right away needs no settling; after a busy spell it does
            if not seen_busy or now - idle_since >= params["settle"]:
                break
        if now - start >= params["timeout"]:
            result["busy"] = True
            result["waited"] = round(now - start, 1)
            result["msg"] = "APT/dpkg is still busy after %ss: %s" % (
                params["timeout"],
                "; ".join(result["reasons"]) or "settling",
            )
            if params["fail_on_timeout"]:
                module.fail_json(**result)
            module.exit_json(**result)
        time.sleep(interval)

    result["waited"] = round(time.monotonic() - start, 1)

    if params["repair"] and dpkg_interrupted():
        result["changed"] = True
        result["repaired"] = True
        if not module.check_mode:
            rc, out, err = module.run_command(
                ["dpkg", "--force-confdef", "--force-confold", "--configure", "-a"],
                environ_update=dict(DEBIAN_FRONTEND="noninteractive"),
            )
            result.update(repair_stdout=out, repair_stderr=err)
            if rc != 0:
                module.fail_json(msg="dpkg --configure -a failed (rc=%s)" % rc, **result)

    result["msg"] = (
        "APT/dpkg is free after waiting %ss" % result["waited"]
        if seen_busy
        else "APT/dpkg is free"
    )
    module.exit_json(**result)


if __name__ == "__main__":
    main()
