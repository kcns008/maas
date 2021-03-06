# Copyright 2012-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Generate JavaScript enum definitions based on Python definitions.

MAAS defines its enums as simple classes, with the enum items as attributes.
Running this script produces a source text containing the JavaScript
equivalents of the same enums, so that JavaScript code can make use of them.

The script takes the filename of the enum modules. Each will be compiled and
executed in an empty namespace, though they will have access to other MAAS
libraries, including their dependencies.

The resulting JavaScript module is printed to standard output.
"""

__all__ = []

from argparse import ArgumentParser
from datetime import datetime
from itertools import chain
import json
from operator import attrgetter
import os.path
import sys
from textwrap import dedent

# Header.  Will be written on top of the output.
header = dedent("""\
/*
Generated file.  DO NOT EDIT.

This file was generated by %(script)s,
on %(timestamp)s.
*/

YUI.add('maas.enums', function(Y) {
Y.log('loading maas.enums');
var module = Y.namespace('maas.enums');
""" % {
    'script': os.path.basename(sys.argv[0]),
    'timestamp': datetime.now(),
})

# Footer.  Will be written at the bottom.
footer = "}, '0.1');"


def is_enum(item):
    """Does the given python item look like an enum?

    :param item: An item imported from a MAAS enum module.
    :return: Bool.
    """
    return isinstance(item, type) and item.__name__.isupper()


def get_enum_classes(namespace):
    """Collect all enum classes exported from `namespace`."""
    return list(filter(is_enum, namespace.values()))


def get_enums(filename):
    namespace = {}
    with open(filename, "rbU") as fd:
        source = fd.read()
    code = compile(source, filename, "exec")
    exec(code, namespace)
    return get_enum_classes(namespace)


# This method is duplicated from provisioningserver/utils/enum.py
# because jsenums is used by the packaging to build the JS file and
# we don't want to force the packaging to require all the dependencies
# that using provisioningserver/utils/enum.py would imply.
def map_enum(enum_class):
    """Map out an enumeration class as a "NAME: value" dict."""
    # Filter out anything that starts with '_', which covers private and
    # special methods.  We can make this smarter later if we start using
    # a smarter enumeration base class etc.  Or if we switch to a proper
    # enum mechanism, this function will act as a marker for pieces of
    # code that should be updated.
    return {
        key: value
        for key, value in vars(enum_class).items()
        if not key.startswith('_')
    }


def serialize_enum(enum):
    """Represent a MAAS enum class in JavaScript."""
    definitions = json.dumps(map_enum(enum), indent=4, sort_keys=True)
    definitions = '\n'.join(
        line.rstrip()
        for line in definitions.splitlines()
        )
    return "module.%s = %s;\n" % (enum.__name__, definitions)


def parse_args():
    """Parse options & arguments."""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        'sources', metavar="FILENAME", nargs='+',
        help="File to search for enums.")
    return parser.parse_args()


def dump(source_filenames):
    enums = chain.from_iterable(
        get_enums(filename) for filename in source_filenames)
    enums = sorted(enums, key=attrgetter("__name__"))
    dumps = [serialize_enum(enum) for enum in enums]
    return "\n".join([header] + dumps + [footer])


if __name__ == "__main__":
    args = parse_args()
    print(dump(args.sources))
