# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Migration to create physical interfaces.

WARNING: Although these methods will become obsolete very quickly, they
cannot be removed, since they are used by the
0161_migration_to_physical_interfaces DataMigration. (changing them might also
be futile unless a customer restores from a backup, since any bugs that occur
will have already occurred, and this code will not be executed again.)

Note: Each helper must have its dependencies on any model classes injected,
since the migration environment is a skeletal replication of the 'real'
database model. So each function takes as parameters the model classes it
requires. Importing from the model is not allowed here. (but the unit tests
do it, to ensure that the migrations meet validation requirements.)
"""

from __future__ import (
    absolute_import,
    print_function,
    unicode_literals,
    )

str = None

__metaclass__ = type
__all__ = [
    "create_physical_interfaces",
]

from textwrap import dedent

from maasserver.enum import INTERFACE_TYPE


def find_macs_having_no_interfaces(MACAddress):
    """Find all MAC addresses without a linked interface."""
    return MACAddress.objects.raw(
        dedent("""\
            SELECT DISTINCT macaddress.*
                FROM maasserver_macaddress AS macaddress
                LEFT OUTER JOIN maasserver_interface AS iface
                    ON macaddress.id = iface.mac_id
                WHERE iface.id IS NULL
                ORDER BY macaddress.node_id, macaddress.mac_address
            """))


def update_interface_with_subnet_vlan(iface, subnet):
    """Utility function to update an interface's VLAN to match a corresponding
    Subnet's VLAN.
    """
    if iface.vlan_id != subnet.vlan_id and subnet.vlan_id != 0:
        iface.vlan = subnet.vlan
        iface.save()


def create_physical_interfaces(MACAddress, Interface, Subnet, VLAN):
    """Create a PhysicalInterface for every MACAddress in the database that
    is not associated with a Interface."""
    # Go through each MAC that does not have an associated interface.
    macs = find_macs_having_no_interfaces(MACAddress)
    previous_node = -1
    index = 0
    for mac in macs:
        current_node = mac.node_id
        # Note: this code assumes that the query is ordered by node_id.
        if current_node != previous_node or current_node is None:
            index = 0
        else:
            index += 1
        # Create a "dummy" interface. (this is a 'legacy' MACAddress)
        iface = Interface.objects.create(
            mac=mac, type=INTERFACE_TYPE.PHYSICAL,
            name='eth' + unicode(index),
            vlan=VLAN.objects.get_default_vlan()
        )
        previous_node = current_node

        # Determine the Subnet that this MAC resides on, and link up any
        # related StaticIPAddresses.
        ngi = mac.cluster_interface
        if ngi is not None and ngi.subnet is not None:
            # Known cluster interface subnet.
            subnet = ngi.subnet
            for ip in mac.ip_addresses.all():
                if unicode(ip.ip) in subnet.cidr:
                    ip.subnet = subnet
                    ip.save()
                    # Since we found the Subnet, adjust the new Interface's
                    # VLAN, too.
                    update_interface_with_subnet_vlan(iface, subnet)
        else:
            for ip in mac.ip_addresses.all():
                # The Subnet isn't on a known cluster interface. Expand the
                # search. At this moment subnets are unique so no need to worry
                # about the fabric.
                for subnet in Subnet.objects.get_subnets_with_ip(ip.ip):
                    break
                else:
                    subnet = None
                if subnet is not None:
                    ip.subnet = subnet
                    ip.save()
                    update_interface_with_subnet_vlan(iface, subnet)