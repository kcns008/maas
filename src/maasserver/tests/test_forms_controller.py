# Copyright 2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for controller forms."""

__all__ = []

from maasserver.clusterrpc.power_parameters import get_power_type_choices
from maasserver.forms import ControllerForm
from maasserver.testing.factory import factory
from maasserver.testing.testcase import MAASServerTestCase


class TestControllerForm(MAASServerTestCase):
    def test_Contains_limited_set_of_fields(self):
        form = ControllerForm()

        self.assertItemsEqual(
            [
                'zone',
                'power_type',
                'power_parameters',
            ],
            list(form.fields))

    def test___populates_power_type_choices(self):
        form = ControllerForm()
        self.assertEqual(
            [''] + [choice[0] for choice in get_power_type_choices()],
            [choice[0] for choice in form.fields['power_type'].choices])

    def test___populates_power_type_initial(self):
        rack = factory.make_RackController()
        form = ControllerForm(instance=rack)
        self.assertEqual(rack.power_type, form.fields['power_type'].initial)

    def test__sets_power_type(self):
        rack = factory.make_RackController()
        power_type = factory.pick_power_type()
        form = ControllerForm(
            data={
                'power_type': power_type,
            },
            instance=rack)
        rack = form.save()
        self.assertEqual(power_type, rack.power_type)

    def test__sets_power_parameters(self):
        rack = factory.make_RackController()
        power_parameters_field = factory.make_string()
        form = ControllerForm(
            data={
                'power_parameters_field': power_parameters_field,
                'power_parameters_skip_check': True,
            },
            instance=rack)
        rack = form.save()
        self.assertEqual(
            {'field': power_parameters_field}, rack.power_parameters)

    def test__sets_zone(self):
        rack = factory.make_RackController()
        zone = factory.make_zone()
        form = ControllerForm(
            data={
                'zone': zone.name,
            },
            instance=rack)
        rack = form.save()
        self.assertEqual(zone.name, rack.zone.name)
