# -*- coding: utf-8 -*-
"""Keep the values a secret file already has when it is rendered again.

Regenerating the secrets of a group must not rotate the credentials that are
already deployed on the hosts. The freshly rendered text is the authority on
the *shape* of the file - which keys exist, in which order, with which
comments - while the file on disk is the authority on the *values* of the
keys both of them have.

The merge is done on the text of the new file rather than on a parsed
structure that is dumped again: these files carry large blocks of commented
out documentation (the `{% raw %}` parts of the templates) that a YAML round
trip would throw away. PyYAML's compose() gives every scalar its position in
the source, so the old value can be cut into the new text and everything
around it stays byte for byte what the template produced.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import re

import yaml

from ansible.errors import AnsibleFilterError

# The keys that identify an item of a list of mappings. The first one an item
# has decides which item of the old list it is paired with; without it the
# items are paired by position.
DEFAULT_ID_KEYS = (
    'name',
    'id',
    'username',
    'user',
    'job_name',
    'hostname',
    'host',
    'target',
)

# A value between angle brackets is how this inventory marks "fill this in",
# so it does not count as a value worth keeping.
PLACEHOLDER_RE = re.compile(r'^<.*>$', re.DOTALL)

NULL_TAG = 'tag:yaml.org,2002:null'


def _compose(text, what):
    try:
        return yaml.compose(text)
    except yaml.YAMLError as error:
        raise AnsibleFilterError(
            "secrets_preserve: the %s content is not valid YAML: %s" % (what, error)
        )


def _is_scalar(node):
    return isinstance(node, yaml.ScalarNode)


def _has_value(node):
    """Whether the old scalar holds something worth keeping."""
    if node.tag == NULL_TAG:
        return False
    value = (node.value or '').strip()
    if not value:
        return False
    return not PLACEHOLDER_RE.match(value)


def _mapping_pairs(node):
    """The key/value nodes of a mapping node, by key, keeping scalars only."""
    pairs = {}
    for key_node, value_node in node.value:
        if _is_scalar(key_node):
            pairs[key_node.value] = value_node
    return pairs


def _identity(node, id_keys):
    """The (key, value) that identifies an item of a list of mappings."""
    if not isinstance(node, yaml.MappingNode):
        return None
    pairs = _mapping_pairs(node)
    for key in id_keys:
        value_node = pairs.get(key)
        if value_node is not None and _is_scalar(value_node):
            return (key, value_node.value)
    return None


def _pair_sequences(new_node, old_node, id_keys):
    """Pair the items of two sequences, by identity key where there is one."""
    old_items = list(old_node.value)
    old_by_identity = {}
    for index, item in enumerate(old_items):
        identity = _identity(item, id_keys)
        if identity is not None and identity not in old_by_identity:
            old_by_identity[identity] = index

    taken = set()
    pairs = []
    unmatched = []

    # The identity keys win, so that an item inserted into the template does
    # not shift every value that follows it onto the wrong item.
    for index, item in enumerate(new_node.value):
        identity = _identity(item, id_keys)
        old_index = old_by_identity.get(identity) if identity is not None else None
        if old_index is not None and old_index not in taken:
            taken.add(old_index)
            pairs.append((item, old_items[old_index]))
        else:
            unmatched.append((index, item))

    # What is left over is paired by position, ignoring the items that an
    # identity key already claimed.
    free = [index for index in range(len(old_items)) if index not in taken]
    for offset, (_index, item) in enumerate(unmatched):
        if offset < len(free):
            pairs.append((item, old_items[free[offset]]))

    return pairs


def _line_tail(text, end):
    """The rest of the line after a scalar: its end, and the text in between."""
    newline = text.find('\n', end)
    if newline == -1:
        newline = len(text)
    return newline, text[end:newline]


def _trailing_comment(tail):
    """A trailing comment of a line, or None when there is none."""
    return tail if re.match(r'^[ \t]*#', tail) else None


def _collect(new_node, old_node, new_text, old_text, id_keys, edits):
    """Walk both trees together and note every value to carry over."""
    if type(new_node) is not type(old_node):
        return

    if isinstance(new_node, yaml.MappingNode):
        old_pairs = _mapping_pairs(old_node)
        for key_node, value_node in new_node.value:
            if not _is_scalar(key_node):
                continue
            old_value = old_pairs.get(key_node.value)
            if old_value is not None:
                _collect(value_node, old_value, new_text, old_text, id_keys, edits)
        return

    if isinstance(new_node, yaml.SequenceNode):
        for new_item, old_item in _pair_sequences(new_node, old_node, id_keys):
            _collect(new_item, old_item, new_text, old_text, id_keys, edits)
        return

    if not _is_scalar(new_node) or not _has_value(old_node):
        return

    start = new_node.start_mark.index
    end = new_node.end_mark.index
    replacement = old_text[old_node.start_mark.index:old_node.end_mark.index]

    # A trailing comment belongs to the value it sits behind: the templates
    # write the bcrypt hash and repeat the raw password in the comment, so
    # keeping the old hash while keeping the new comment would pair a hash
    # with a password that does not produce it.
    new_end, new_tail = _line_tail(new_text, end)
    if _trailing_comment(new_tail) is not None:
        _old_end, old_tail = _line_tail(old_text, old_node.end_mark.index)
        old_comment = _trailing_comment(old_tail)
        end = new_end
        replacement += old_comment if old_comment is not None else ''

    edits.append((start, end, replacement))


def secrets_preserve(new_text, old_text, id_keys=None):
    """Put the values of old_text back into new_text where both have the key.

    Only the keys that exist in both files are touched, and only when the old
    value is a scalar that is neither empty nor an <angle bracket>
    placeholder. Keys the new file added keep their freshly generated value,
    keys it dropped stay dropped.
    """
    if not isinstance(new_text, str) or not isinstance(old_text, str):
        raise AnsibleFilterError('secrets_preserve: both arguments must be strings')

    if not old_text.strip():
        return new_text

    keys = tuple(id_keys) if id_keys else DEFAULT_ID_KEYS

    new_root = _compose(new_text, 'new')
    old_root = _compose(old_text, 'old')
    if new_root is None or old_root is None:
        return new_text

    edits = []
    _collect(new_root, old_root, new_text, old_text, keys, edits)

    result = new_text
    last_start = len(new_text)
    for start, end, replacement in sorted(edits, reverse=True):
        # Applying back to front keeps the untouched positions valid; a span
        # that overlaps the one already written is dropped rather than
        # corrupting the line.
        if end > last_start:
            continue
        result = result[:start] + replacement + result[end:]
        last_start = start

    return result


def secrets_group_dirs(groups, mapping=None, available=None):
    """Match every inventory group with the template directories it owns.

    A group that the mapping does not name owns the directory of its own
    name. Directories that do not exist are dropped, and so are the groups
    left with none of them: `git_sync` and `domain_management` have no secret
    to write, and offering them would only lead to an empty run.
    """
    mapping = mapping or {}
    known = None if available is None else set(available)

    matched = {}
    for group in groups:
        dirs = mapping.get(group, [group])
        if isinstance(dirs, str):
            dirs = [dirs]
        if known is not None:
            dirs = [d for d in dirs if d in known]
        if dirs:
            matched[group] = dirs
    return matched


def secrets_group_choices(matched):
    """Label every group of the choice with the directories it writes.

    The directory is usually the name of the group again, and repeating it
    would only make the list harder to read, so it is named only when it
    differs.
    """
    choices = {}
    for group, dirs in matched.items():
        if list(dirs) == [group]:
            choices[group] = group
        else:
            choices[group] = '%s (%s)' % (group, ', '.join(dirs))
    return choices


class FilterModule(object):
    """Merge filter of roles/setup/secrets."""

    def filters(self):
        return {
            'secrets_preserve': secrets_preserve,
            'secrets_group_dirs': secrets_group_dirs,
            'secrets_group_choices': secrets_group_choices,
        }
