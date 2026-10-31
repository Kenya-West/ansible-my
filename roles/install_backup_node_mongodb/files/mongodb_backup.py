#!/usr/bin/env python3
"""Validate persistent declarations and atomically dump MongoDB targets."""
import argparse
import copy
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager

IDENTIFIER = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def safe_relative(value):
    return (isinstance(value, str) and bool(value) and
            not Path(value).is_absolute() and
            all(part not in ("", ".", "..") for part in value.split("/")))


def load_targets(directory, output_root):
    targets = []
    owners = set()
    for path in sorted(Path(directory).glob("*.json")):
        with path.open() as stream:
            manifest = json.load(stream)
        require(isinstance(manifest, dict), f"{path}: expected an object")
        require(manifest.get("schema_version") == 1, f"{path}: unsupported schema_version")
        owner = manifest.get("owner", "")
        require(isinstance(owner, str) and IDENTIFIER.fullmatch(owner), f"{path}: invalid owner")
        require(owner not in owners, f"duplicate owner: {owner}")
        owners.add(owner)
        require(isinstance(manifest.get("targets"), list), f"{path}: targets must be a list")
        targets.extend(manifest["targets"])
    return validate_targets(targets, output_root)


def validate_targets(targets, output_root, resolve_paths=True):
    require(isinstance(targets, list), "targets must be a list")
    ids, outputs = set(), set()
    for target in targets:
        validate_target(target, output_root, resolve_paths=resolve_paths)
        identity = target["id"]
        output = str(Path(output_root) / target["output"]["subdirectory"] / target["output"]["filename"])
        require(identity not in ids, f"duplicate target id: {identity}")
        require(output not in outputs, f"duplicate output: {output}")
        ids.add(identity)
        outputs.add(output)
    return targets


def validate_target(target, output_root, resolve_paths=True):
    require(isinstance(target, dict), "target must be an object")
    identity = target.get("id", "")
    require(isinstance(identity, str) and IDENTIFIER.fullmatch(identity), "invalid target id")
    require(len(identity) <= 120, f"{identity}: id too long")
    execution = target.get("execution", {})
    connection = target.get("connection", {})
    dump = target.get("dump", {})
    output = target.get("output", {})
    require(all(isinstance(item, dict) for item in (execution, connection, dump, output)),
            f"{identity}: execution, connection, dump and output must be objects")
    schedule = target.get("schedule", {})
    require(isinstance(schedule, dict), f"{identity}: schedule must be an object")
    for key in ("calendar", "randomized_delay"):
        require(key not in schedule or (isinstance(schedule[key], str) and bool(schedule[key]) and
                                       "\n" not in schedule[key]), f"{identity}: invalid schedule {key}")
    for key in ("docker_bin", "docker_host", "docker_context", "mongodump_bin"):
        require(key not in execution or (isinstance(execution[key], str) and bool(execution[key]) and
                                        "\x00" not in execution[key]), f"{identity}: invalid {key}")
    require(not (execution.get('docker_host') and execution.get('docker_context')),
            f"{identity}: select docker_host or docker_context, not both")
    require(isinstance(execution.get("skip_if_unavailable", True), bool),
            f"{identity}: skip_if_unavailable must be a boolean")
    docker_unit = execution.get("docker_unit", "")
    require(isinstance(docker_unit, str) and
            (not docker_unit or re.fullmatch(r"[a-zA-Z0-9_.@-]+\.(service|socket)", docker_unit)),
            f"{identity}: docker_unit must be empty or a user service/socket unit name")
    driver = execution.get("driver")
    require(driver in ("compose_exec", "direct"), f"{identity}: unsupported execution driver")
    if driver == "compose_exec":
        require(isinstance(target.get("project_path"), str) and
                Path(target["project_path"]).is_absolute(), f"{identity}: absolute project_path required")
        require(isinstance(execution.get("service"), str) and IDENTIFIER.fullmatch(execution["service"]),
                f"{identity}: invalid Compose service")
        for key in ("project_name",):
            require(key not in execution or (isinstance(execution[key], str) and IDENTIFIER.fullmatch(execution[key])),
                    f"{identity}: invalid {key}")
        source = connection.get("source", "url_file" if connection.get("url_file") else "container_environment")
        require(source in ("container_environment", "config_file", "url_file"),
                f"{identity}: Compose connection source must be container_environment, config_file or url_file")
    else:
        source = connection.get("source", "url_file" if connection.get("url_file") else "config_file")
        require(source in ("config_file", "url_file"), f"{identity}: direct connections require config_file or url_file")
    if source in ("config_file", "url_file"):
        require(isinstance(connection.get(source), str) and Path(connection[source]).is_absolute(),
                f"{identity}: connection requires an absolute {source}")
    require('uri' not in connection and 'password' not in connection,
            f"{identity}: credentials must use a private connection file, not inline uri/password")
    for key in ("database", "auth_database", "host"):
        require(key not in connection or (isinstance(connection[key], str) and bool(connection[key]) and
                                         "\x00" not in connection[key] and "\n" not in connection[key]),
                f"{identity}: invalid {key}")
    require(isinstance(dump.get("gzip", True), bool), f"{identity}: gzip must be a boolean")
    require(isinstance(dump.get("oplog", False), bool), f"{identity}: oplog must be a boolean")
    require(not (dump.get("oplog") and connection.get("database")),
            f"{identity}: oplog requires a full-instance dump (no database filter)")
    require(safe_relative(output.get("subdirectory")), f"{identity}: invalid output subdirectory")
    require(safe_relative(output.get("filename")) and "/" not in output["filename"],
            f"{identity}: invalid output filename")
    if resolve_paths:
        root = Path(output_root).resolve()
        destination = root / output["subdirectory"] / output["filename"]
        require(root in destination.resolve().parents, f"{identity}: output escapes root (possibly a symlink)")


def read_connection_config(connection):
    # MongoDB Database Tools --config accepts YAML uri/password fields. Keep
    # credentials out of argv, process errors and persistent shell scripts.
    is_url = connection.get("source") == "url_file" or ("url_file" in connection and "config_file" not in connection)
    path = Path(connection["url_file" if is_url else "config_file"])
    require(path.is_file() and path.stat().st_mode & 0o077 == 0,
            "MongoDB config file must be a private regular file (0600 or stricter)")
    content = path.read_text()
    require(bool(content.strip()), "MongoDB connection file is empty")
    if is_url:
        uri = content.strip()
        require(uri.startswith(("mongodb://", "mongodb+srv://")), "Connection file must contain a MongoDB URI")
        return json.dumps({"uri": uri}) + "\n"
    return content


def compose_command(target):
    execution = target["execution"]
    command = [execution.get("docker_bin", "docker"), "compose", "--project-directory", target["project_path"],
               "--file", str(Path(target["project_path"]) / "docker-compose.yml")]
    if execution.get("project_name"):
        command += ["--project-name", execution["project_name"]]
    env = os.environ.copy()
    # Follow Docker's persisted current context and inherited CLI environment
    # unless the manifest explicitly pins an endpoint. Never guess a socket or
    # retry another daemon: that could dump the wrong project's data.
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    if execution.get("docker_host"):
        env.pop("DOCKER_CONTEXT", None)  # DOCKER_CONTEXT overrides DOCKER_HOST.
        env["DOCKER_HOST"] = execution["docker_host"]
    elif execution.get("docker_context"):
        env.pop("DOCKER_HOST", None)
        env["DOCKER_CONTEXT"] = execution["docker_context"]
    return command, env, target["project_path"]


def skip_unavailable_container(target):
    execution = target["execution"]
    if execution["driver"] != "compose_exec" or not execution.get("skip_if_unavailable", True):
        return False
    command, env, cwd = compose_command(target)
    # A successful empty query means absent/stopped. Daemon/configuration errors
    # must propagate, not masquerade as an unavailable database container.
    result = subprocess.run(command + ["ps", "--status", "running", "--quiet", execution["service"]],
                            env=env, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    if not result.stdout.strip():
        print(f"Backup skipped: {target['id']} (database container is absent or not running)")
        return True
    return False


@contextmanager
def dump_command(target):
    execution, connection, dump = (target.get(key, {}) for key in ("execution", "connection", "dump"))
    args = [execution.get("mongodump_bin", "mongodump"), "--archive"]
    if dump.get("gzip", True):
        args.append("--gzip")
    if dump.get("oplog", False):
        args.append("--oplog")
    if connection.get("database"):
        args += ["--db", connection["database"]]
    if execution["driver"] == "direct":
        config = read_connection_config(connection)
        # Use a private ephemeral config for either YAML config_file or url_file.
        # URI contents never appear in process argv and are removed on errors.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml") as config_stream:
            config_stream.write(config)
            config_stream.flush()
            yield args + ["--config", config_stream.name], os.environ.copy(), None, None
        return
    command, env, cwd = compose_command(target)
    source = connection.get("source", "url_file" if connection.get("url_file") else "container_environment")
    if source in ("config_file", "url_file"):
        # Stream a private config into an ephemeral container file, not argv/env.
        # No -T stdin suppression: Compose exec -T keeps stdin open by default.
        config = read_connection_config(connection).encode()
        script = ('set -eu; umask 077; config="$(mktemp)"; '
                  'trap \'rm -f "$config"\' EXIT HUP INT TERM; '
                  'cat > "$config"; "$@" --config "$config"')
    else:
        config = None
        # Build mongodump's YAML config with JSON-escaped strings using mongosh.
        # This handles special password characters without exporting credentials
        # to mongodump argv. mongosh is required in the selected DB container.
        script = ('set -eu; umask 077; config="$(mktemp)"; '
                  'trap \'rm -f "$config"\' EXIT HUP INT TERM; '
                  'export BACKUP_MONGO_HOST="$1" BACKUP_MONGO_AUTH_DB="$2"; shift 2; '
                  'mongosh --nodb --quiet --eval '
                  '\'const e=process.env; const u=e.MONGO_INITDB_ROOT_USERNAME; '
                  'const p=e.MONGO_INITDB_ROOT_PASSWORD; '
                  'if (!!u !== !!p) { throw new Error("Incomplete MongoDB root credentials"); } '
                  'const auth=u ? encodeURIComponent(u)+"@" : ""; '
                  'const uri="mongodb://"+auth+e.BACKUP_MONGO_HOST+"/?authSource="'
                  '+encodeURIComponent(e.BACKUP_MONGO_AUTH_DB); '
                  'print("uri: "+JSON.stringify(uri)); '
                  'if(p) print("password: "+JSON.stringify(p));\' > "$config"; '
                  '"$@" --config "$config"')
    prefix = command + ["exec", "-T", execution["service"], "sh", "-c", script, "mongodb-backup"]
    if config is None:
        prefix += [connection.get("host", "127.0.0.1:27017"), connection.get("auth_database", "admin")]
    yield prefix + args, env, cwd, config


def run_backup(target, output_root):
    if skip_unavailable_container(target):
        return
    directory = Path(output_root) / target["output"]["subdirectory"]
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = directory / target["output"]["filename"]
    temporary = None
    # All invocations, including manual/pre-upgrade ones, share the output lock.
    with (directory / (destination.name + ".lock")).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            with dump_command(target) as (command, env, cwd, config):
                with tempfile.NamedTemporaryFile(dir=directory, prefix=".dump-", suffix=".tmp", delete=False) as stream:
                    temporary = Path(stream.name)
                    try:
                        # Tools may include the URI in diagnostics; avoid leaking
                        # credentials to journal or Ansible on either driver.
                        subprocess.run(command, env=env, cwd=cwd, stdout=stream,
                                       input=config, stderr=subprocess.PIPE, check=True)
                    except subprocess.CalledProcessError:
                        if skip_unavailable_container(target):
                            return
                        raise
                    stream.flush()
                    os.fsync(stream.fileno())
            require(temporary.stat().st_size > 0, "dump was empty")
            os.chmod(temporary, 0o600)
            os.replace(temporary, destination)
            temporary = None
            fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            print(f"Backup completed: {target['id']} -> {destination}")
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-dir")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--skip-path-resolution", action="store_true",
                        help="Validate structure only for an Ansible check-mode preview")
    parser.add_argument("--require-available", action="store_true",
                        help="Require a fresh dump instead of skipping a stopped Compose container")
    parser.add_argument("--validate-connections", action="store_true",
                        help="Check private connection references without connecting to MongoDB")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--validate", action="store_true")
    action.add_argument("--validate-stdin", action="store_true")
    action.add_argument("--target")
    os.umask(0o077)
    options = parser.parse_args()
    try:
        if options.validate_stdin:
            targets = validate_targets(json.load(sys.stdin), options.output_root,
                                       resolve_paths=not options.skip_path_resolution)
        else:
            require(options.manifest_dir is not None, "--manifest-dir is required")
            require(not options.skip_path_resolution, "path checks cannot be skipped for backups")
            targets = load_targets(options.manifest_dir, options.output_root)
        if options.validate or options.validate_stdin:
            if options.validate_connections:
                for target in targets:
                    connection = target.get('connection', {})
                    if connection.get('config_file') or connection.get('url_file'):
                        read_connection_config(connection)
            print(json.dumps(targets))
        else:
            target = next((item for item in targets if item["id"] == options.target), None)
            require(target is not None, "target is not declared; deploy its producer role first")
            if options.require_available:
                target = copy.deepcopy(target)
                target["execution"]["skip_if_unavailable"] = False
            run_backup(target, options.output_root)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        # CalledProcessError.__str__ includes argv; do not expose it.
        message = "MongoDB dump command failed" if isinstance(error, subprocess.CalledProcessError) else str(error)
        print(f"Backup failed: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
