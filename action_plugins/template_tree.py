from ansible.errors import AnsibleError, AnsibleParserError
from ansible.plugins.action import ActionBase
from pathlib import PurePath

import os
import os.path as path
import stat

import ansible.module_utils.common.text.converters as converters


class ActionModule(ActionBase):
    REQUIRED_ARGS = ("src", "dest")
    TEMPLATE_EXTENSION = ".j2"

    def run(self, tmp=None, task_vars=None):
        output = super(ActionModule, self).run(tmp, task_vars)

        for arg in self.REQUIRED_ARGS:
            if not arg in self._task.args:
                output["failed"] = True
                output["msg"] = f"missing required argument '{arg}'"
                return output

        remote_path = self._task.args["dest"]

        local_paths = self._task.args["src"]
        if not isinstance(local_paths, list):
            local_paths = [local_paths]

        owner = self._task.args.get("owner", None)
        group = self._task.args.get("group", None)
        file_mode = self._task.args.get("file_mode", None)
        directory_mode = self._task.args.get("directory_mode", None)
        exclusive = self._task.args.get("exclusive", False)
        exclusive_ignore = self._parse_path_list("exclusive_ignore")

        self._display.vv(f"TEMPLATE_TREE: {local_paths} -> {remote_path}")

        local_entries = self._get_local_entries(local_paths, task_vars)
        remote_entries = self._get_remote_entries(remote_path, task_vars)

        to_create = list(
            self._get_entries_to_create(
                local_entries, remote_path, owner, group, file_mode, directory_mode
            )
        )

        self._set_file_contents(to_create, task_vars)

        to_delete = list(
            self._get_entries_to_delete(
                to_create, remote_entries, remote_path, exclusive, exclusive_ignore
            )
        )

        results = list(self._delete_entries(to_delete, task_vars))
        results.extend(self._create_entries(to_create, task_vars))

        self._build_output(output, results)
        return output

    def _parse_path_list(self, argname):
        paths = self._task.args.get(argname, [])
        is_list = True
        if not isinstance(paths, list):
            paths = [paths]
            is_list = False

        try:
            return list(map(PurePath, paths))
        except:
            if is_list:
                raise AnsibleError(
                    f"Argument '{argname}' contains one or more values of an invalid type"
                )
            else:
                raise AnsibleError(f"Argument '{argname}' is of an invalid type")

    def _get_local_entries(self, local_paths, task_vars):
        entries = []
        for local_path in local_paths:
            basedir = task_vars.get("role_path", self._loader.get_basedir())
            found_path = self._loader.path_dwim_relative(basedir, "files", local_path)
            self._display.vv(f"RESOLVE_SRC: '{local_path}' -> '{found_path}'")

            # We'll receive a reference to either a file or a directory.
            # If it's a file, return it directly instead of searching through it.
            if path.exists(found_path):
                stat_result = os.lstat(found_path)
                if stat.S_ISREG(stat_result.st_mode):
                    # Path points to a regular file
                    entries.append(
                        dict(
                            root=path.dirname(found_path) + path.sep,
                            path=path.basename(found_path),
                            state="file",
                            src=found_path,
                        )
                    )
                    continue

            # If the source path does not end with a directory separator, we must
            # copy the source directory including its contents. filetree does not
            # support also retrieving the source directory, so we insert our own
            # entry here.
            # if not local_path.endswith(path.sep):
            entries.append(
                dict(
                    root=local_path,
                    path="",
                    state="directory",
                ),
            )

            filetree_lookup = self._shared_loader_obj.lookup_loader.get(
                "community.general.filetree", loader=self._loader
            )
            # Filetree supports passing multiple paths, and will handle duplicates
            # for us, by only returning the first entry it finds for a given
            # relative path.
            entries += filetree_lookup.run(local_paths, variables=task_vars)

        # Be explicit about the keys we use.
        filetree_used_keys = {"root", "path", "state", "src"}
        entries = [
            {key: value for key, value in entry.items() if key in filetree_used_keys}
            for entry in entries
        ]

        return entries

    def _get_remote_entries(self, remote_path, task_vars):
        result = self._execute_module(
            module_name="ansible.builtin.find",
            module_args=dict(
                file_type="any",
                hidden=True,
                paths=remote_path,
                recurse=True,
            ),
            task_vars=task_vars,
            tmp=None,
        )

        if "warnings" in result:
            for warning in result["warnings"]:
                self._display.warning(warning)

        # The find module always returns a message, either that all paths have been
        # examined, or that not all paths have been examined. In the second case, more
        # specific information is included as warnings, which are printed above. Because
        # of that, this message is not relevant during normal operation.
        if "msg" in result and result["msg"]:
            self._display.v(f"find module message: {result['msg']}")

        # Be explicit about the keys we use.
        filetree_used_keys = {"path", "isdir", "isreg"}
        entries = [
            {key: value for key, value in entry.items() if key in filetree_used_keys}
            for entry in result["files"]
        ]

        for entry in entries:
            # Since Ansible 9.0, the find module returns its results as
            # AnsibleUnsafeText instead of str. AnsibleUnsafeText is a subclass of str,
            # which is used to prevent accidental templating. As it is a subclass of
            # str, in most cases, this change is invisible to us. Unfortunately, pathlib
            # calls the string interner on its arguments, which does not accept a
            # subclass of str and instead throws an error.
            # To fix this, we have to convert entry["path"] into an actual str object.
            # This is difficult, because it is already a str subclass and Python
            # optimizes a lot of more obvious attempts away because it sees them as
            # no-ops. The following attempts still return AnsibleUnsafeText objects.
            #
            # * str(entry["path"])
            # * f"{entry['path']}"
            # * "" + entry["path"]
            # * entry["path"][:]
            #
            # We want to avoid depending on some Python optimization behaviour, which
            # may change between releases. Instead, we make sure that we modify the
            # string without changing its semantics, which will force the creation of a
            # new str object. Luckily, pathlib collapses spurious dots in paths, so we
            # can add /. at the end of the path. Note that adding ./ to the front of a
            # path may change its semantics when it is an absolute path (i.e. ".//foo"
            # is interpreted as "foo").
            entry["path"] = PurePath(f"{entry['path']}/.")

        return entries

    def _get_entries_to_create(
        self, local_entries, remote_path, owner, group, file_mode, directory_mode
    ):
        for local_entry in local_entries:
            relative_path = path.normpath(local_entry["path"])

            destination_root = remote_path
            if not local_entry["root"].endswith(path.sep):
                source_dir = path.basename(local_entry["root"])
                destination_root = path.join(destination_root, source_dir)

            destination_path = path.join(destination_root, relative_path)
            # When processing the root dir, relative_path will be '.', which
            # will end up as '/.' at the end of destination_path.
            # Normalising it one more time will get rid of this.
            destination_path = path.normpath(destination_path)

            entry = {
                "dest": destination_path,
                "state": local_entry["state"],
                "owner": owner,
                "group": group,
            }
            if entry["state"] == "file":
                # Only files have a 'src' key.
                entry["src"] = local_entry["src"]
                entry["template"] = False
                entry["mode"] = file_mode

                if destination_path.endswith(self.TEMPLATE_EXTENSION):
                    entry["dest"] = destination_path[: -len(self.TEMPLATE_EXTENSION)]
                    entry["template"] = True

                self._display.vv(f"MAP_FILE: '{entry['src']} -> {entry['dest']}'")

            elif entry["state"] == "directory":
                self._display.vv(f"REMOTE_DIR: '{entry['dest']}'")
                entry["mode"] = directory_mode
            else:
                self._display.warning(
                    f"Ignoring unrecognised local file type: {entry['state']}"
                )
                continue

            yield entry

    def _set_file_contents(self, entries, task_vars):
        for file in filter(lambda e: e["state"] == "file", entries):
            if file["template"]:
                self._display.vv(f"TEMPLATE: {file['src']}")
                content = self._template_local_file_contents(file["src"], task_vars)
            else:
                self._display.vv(f"READ: {file['src']}")
                content = self._get_local_file_contents(file["src"])

            file["content"] = content

    def _template_local_file_contents(self, path, task_vars):
        self._display.vvvv(f"Template local file '{path}'")
        template_lookup = self._shared_loader_obj.lookup_loader.get(
            "ansible.builtin.template",
            loader=self._loader,
            templar=self._templar,
        )
        return template_lookup.run([path], convert_data=False, variables=task_vars)[0]

    def _get_local_file_contents(self, path):
        self._display.vvvv(f"File lookup using '{path}' as file")
        try:
            contents, _ = self._loader._get_file_contents(path)
            return converters.to_text(contents, errors="surrogate_or_strict")
        except AnsibleParserError:
            raise AnsibleError(f"could not locate file in lookup: {path}")

    def _get_entries_to_delete(
        self,
        local_entries,
        remote_entries,
        remote_path,
        exclusive,
        exclusive_ignore,
    ):
        # For convenience, we'll allow specifying absolute ignore paths.
        # We rewrite them to relative paths here, so our comparison of a
        # relative path to another relative path below works.
        exclusive_ignore = list(
            map(
                lambda i: i.relative_to(remote_path) if i.is_absolute() else i,
                exclusive_ignore,
            )
        )

        for remote_entry in remote_entries:
            absolute_path: PurePath = remote_entry["path"]
            relative_path = absolute_path.relative_to(remote_path)

            # We could short-circuit on files here, if their parent is already
            # being deleted. This will reduce the number of calls
            # to the file module with state=absent.
            local_match = next(
                (
                    local_entry
                    for local_entry in local_entries
                    if PurePath(local_entry["dest"]) == absolute_path
                ),
                None,
            )

            if not local_match:
                if exclusive:
                    ignore_match = next(
                        (
                            ignore_path
                            for ignore_path in exclusive_ignore
                            if relative_path.is_relative_to(ignore_path)
                        ),
                        None,
                    )
                    if ignore_match:
                        self._display.vv(
                            f"COMPARE: keep '{relative_path}' (child of ignored path '{ignore_match}')"
                        )
                    else:
                        self._display.vv(
                            f"COMPARE: delete '{relative_path}' (absent in source)"
                        )
                        yield remote_entry
                else:
                    self._display.vv(
                        f"COMPARE: keep '{relative_path}' (exclusive mode disabled)"
                    )

                continue

            local_state = local_match["state"]
            remote_state = None
            if remote_entry["isdir"]:
                remote_state = "directory"
            elif remote_entry["isreg"]:
                remote_state = "file"
            else:
                remote_state = "other"

            if local_state != remote_state:
                self._display.vv(
                    f"COMPARE: delete '{relative_path}' (source is {remote_state}, destination is {local_state})"
                )
                yield remote_entry
                continue

            self._display.vv(f"COMPARE: keep '{relative_path}' (present in source)")

    def _delete_entries(self, entries, task_vars):
        for entry in entries:
            self._display.vv(f"DELETE: {entry['path']}")
            res = self._execute_module(
                module_name="ansible.builtin.file",
                module_args=dict(path=str(entry["path"]), state="absent"),
                task_vars=task_vars,
                tmp=None,
            )

            if res.get("failed", False):
                raise AnsibleError(res["msg"])
            yield res

    def _create_entries(self, entries, task_vars):
        for entry in entries:
            if entry["state"] == "file":
                result = self._copy_file(entry, task_vars)
            elif entry["state"] == "directory":
                result = self._create_directory(entry, task_vars)

            if result.get("failed", False):
                raise AnsibleError(result["msg"])
            yield result

    def _copy_file(self, file, task_vars):
        task = self._task.copy()
        task.args = dict(
            content=file["content"],
            dest=file["dest"],
            group=file["group"],
            owner=file["owner"],
            mode=file["mode"],
        )

        self._display.vv(f"COPY: {file['dest']}")
        copy_action = self._shared_loader_obj.action_loader.get(
            "ansible.builtin.copy",
            task=task,
            connection=self._connection,
            play_context=self._play_context,
            loader=self._loader,
            templar=self._templar,
            shared_loader_obj=self._shared_loader_obj,
        )
        return copy_action.run(task_vars=task_vars)

    def _create_directory(self, directory, task_vars):
        self._display.vv(f"DIR: {directory['dest']}")
        return self._execute_module(
            module_name="ansible.builtin.file",
            module_args=dict(
                path=directory["dest"],
                state="directory",
                group=directory["group"],
                owner=directory["owner"],
                mode=directory["mode"],
            ),
            task_vars=task_vars,
            tmp=None,
        )

    def _build_output(self, output, operation_results):
        output["deleted_entries"] = []
        output["managed_directories"] = []
        output["managed_files"] = []
        for result in operation_results:
            if "state" in result:
                if result["state"] == "absent":
                    output["deleted_entries"].append(result)
                elif result["state"] == "directory":
                    output["managed_directories"].append(result)
                elif result["state"] == "file":
                    output["managed_files"].append(result)

            output["changed"] = output.get("changed", False) or result["changed"]
            if "diff" in result:
                result_diff = result["diff"]
                output_diff = output.setdefault("diff", [])

                # Commands may return either a single diff, or a list of diffs.
                if isinstance(result_diff, list):
                    output_diff += result_diff
                else:
                    output_diff.append(result_diff)