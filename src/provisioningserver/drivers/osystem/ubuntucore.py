# Copyright 2017 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Operating System class used for custom images."""

__all__ = [
    "UbuntuCoreOS",
    ]

import os

from provisioningserver.config import ClusterConfiguration
from provisioningserver.drivers.osystem import (
    BOOT_IMAGE_PURPOSE,
    OperatingSystem,
)


class UbuntuCoreOS(OperatingSystem):
    """Ubuntu Core operating system."""

    name = "ubuntu-core"
    title = "Ubuntu Core"

    def get_boot_image_purposes(self, arch, subarch, release, label):
        """Gets the purpose of each boot image."""
        # Custom images can only be used with XINSTALL.
        return [BOOT_IMAGE_PURPOSE.XINSTALL]

    def is_release_supported(self, release):
        """Return True when the release is supported, False otherwise."""
        # All release are supported, since the user uploaded it.
        return True

    def get_default_release(self):
        """Gets the default release to use when a release is not
        explicit."""
        return "16"

    def get_release_title(self, release):
        """Return the title for the given release."""
        # Return the same name, since the cluster does not know about the
        # title of the image. The region will fix the title for the UI.
        return release

    def get_xinstall_parameters(self, arch, subarch, release, label):
        """Returns the xinstall image name and type for given image."""
        filetypes = {
            "root-tgz": "tgz",
            "root-dd.tar": "dd-tar",
            "root-dd.raw": "dd-raw",
            "root-dd.tar.bz2": "dd-tbz",
            "root-dd": "dd-tgz",
            "root-dd.tar.xz": "dd-txz",
            "root-dd.bz2": "dd-bz2",
            "root-dd.gz": "dd-gz",
            "root-dd.xz": "dd-xz"
        }
        with ClusterConfiguration.open() as config:
            dd_path = os.path.join(
                config.tftp_root, 'ubuntu-core', arch,
                subarch, release, label)
        try:
            filename, filetype = "", ""
            for fname in os.listdir(dd_path):
                if fname in filetypes.keys():
                    filename, filetype = fname, filetypes[fname]
        except FileNotFoundError:
            # In case the path does not exist
            pass
        return filename, filetype
