# Copyright 2017 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = []

from datetime import (
    datetime,
    timedelta,
)
import random

from django.core.exceptions import ValidationError
from maasserver.enum import NODE_TYPE
from maasserver.exceptions import NoScriptsFound
from maasserver.models import (
    Config,
    Event,
    EventType,
)
from maasserver.preseed import CURTIN_INSTALL_LOG
from maasserver.testing.factory import factory
from maasserver.testing.testcase import MAASServerTestCase
from maasserver.utils.orm import reload_object
from maastesting.matchers import MockCalledOnceWith
from metadataserver.enum import (
    RESULT_TYPE,
    SCRIPT_STATUS,
    SCRIPT_TYPE,
)
from metadataserver.models import (
    ScriptSet,
    scriptset as scriptset_module,
)
from metadataserver.models.scriptset import translate_result_type
from provisioningserver.events import EVENT_TYPES
from provisioningserver.refresh.node_info_scripts import NODE_INFO_SCRIPTS


class TestTranslateResultType(MAASServerTestCase):
    """Test translate_result_type."""
    scenarios = [
        ('numeric testing', {
            'value': RESULT_TYPE.TESTING,
            'return_value': RESULT_TYPE.TESTING,
        }),
        ('numeric commissioning', {
            'value': RESULT_TYPE.COMMISSIONING,
            'return_value': RESULT_TYPE.COMMISSIONING,
        }),
        ('numeric installation', {
            'value': RESULT_TYPE.INSTALLATION,
            'return_value': RESULT_TYPE.INSTALLATION,
        }),
        ('numeric string testing', {
            'value': str(RESULT_TYPE.TESTING),
            'return_value': RESULT_TYPE.TESTING,
        }),
        ('numeric string commissioning', {
            'value': str(RESULT_TYPE.COMMISSIONING),
            'return_value': RESULT_TYPE.COMMISSIONING,
        }),
        ('numeric string installation', {
            'value': str(RESULT_TYPE.INSTALLATION),
            'return_value': RESULT_TYPE.INSTALLATION,
        }),
        ('invalid id', {
            'value': random.randint(100, 1000),
            'exception': 'Invalid result type numeric value.',
        }),
        ('test', {
            'value': 'test',
            'return_value': RESULT_TYPE.TESTING,
        }),
        ('testing', {
            'value': 'testing',
            'return_value': RESULT_TYPE.TESTING,
        }),
        ('commission', {
            'value': 'commission',
            'return_value': RESULT_TYPE.COMMISSIONING,
        }),
        ('commissioning', {
            'value': 'commissioning',
            'return_value': RESULT_TYPE.COMMISSIONING,
        }),
        ('install', {
            'value': 'install',
            'return_value': RESULT_TYPE.INSTALLATION,
        }),
        ('installation', {
            'value': 'installation',
            'return_value': RESULT_TYPE.INSTALLATION,
        }),
        ('invalid value', {
            'value': factory.make_name('value'),
            'exception': (
                'Result type must be commissioning, testing, or installation.')
        }),
    ]

    def test_translate_result_type(self):
        if hasattr(self, 'exception'):
            with self.assertRaisesRegex(ValidationError, self.exception):
                translate_result_type(self.value)
        else:
            self.assertEquals(
                self.return_value, translate_result_type(self.value))


class TestScriptSetManager(MAASServerTestCase):
    """Test the ScriptSet manager."""

    def test_clean_old_ignores_new_script_set(self):
        # Make sure the created script_set isn't cleaned up. This can happen
        # when multiple script_sets last_ping are set to None.
        script_set_limit = Config.objects.get_config(
            'max_node_installation_results')
        node = factory.make_Node()
        for _ in range(script_set_limit * 2):
            ScriptSet.objects.create(
                node=node, result_type=RESULT_TYPE.INSTALLATION,
                last_ping=None)

        script_set = ScriptSet.objects.create_installation_script_set(node)
        # If the new script_set was cleaned up this will fail.
        node.current_installation_script_set = script_set
        node.save()

        self.assertEquals(
            script_set_limit,
            ScriptSet.objects.filter(
                node=node,
                result_type=RESULT_TYPE.INSTALLATION).count())

    def test_create_commissioning_script_set(self):
        custom_scripts = [
            factory.make_Script(script_type=SCRIPT_TYPE.COMMISSIONING)
            for _ in range(3)
        ]
        node = factory.make_Node()

        script_set = ScriptSet.objects.create_commissioning_script_set(node)

        expected_scripts = list(NODE_INFO_SCRIPTS)
        expected_scripts += [
            script.name for script in custom_scripts]
        self.assertItemsEqual(
            expected_scripts,
            [script_result.name for script_result in script_set])
        self.assertEquals(RESULT_TYPE.COMMISSIONING, script_set.result_type)
        self.assertEquals(
            node.power_state, script_set.power_state_before_transition)

    def test_create_commissioning_script_set_for_controller(self):
        for _ in range(3):
            factory.make_Script(script_type=SCRIPT_TYPE.COMMISSIONING)
        node = factory.make_Node(
            node_type=random.choice([
                NODE_TYPE.RACK_CONTROLLER,
                NODE_TYPE.REGION_CONTROLLER,
                NODE_TYPE.REGION_AND_RACK_CONTROLLER]),
        )

        script_set = ScriptSet.objects.create_commissioning_script_set(node)

        expected_scripts = [
            script_name
            for script_name, data in NODE_INFO_SCRIPTS.items()
            if data['run_on_controller']
        ]
        self.assertItemsEqual(
            expected_scripts,
            [script_result.name for script_result in script_set])
        self.assertEquals(RESULT_TYPE.COMMISSIONING, script_set.result_type)
        self.assertEquals(
            node.power_state, script_set.power_state_before_transition)

    def test_create_commissioning_script_set_adds_all_user_scripts(self):
        script = factory.make_Script(script_type=SCRIPT_TYPE.COMMISSIONING)
        node = factory.make_Node()
        expected_scripts = list(NODE_INFO_SCRIPTS)
        expected_scripts.append(script.name)

        script_set = ScriptSet.objects.create_commissioning_script_set(node)

        self.assertItemsEqual(
            expected_scripts,
            [script_result.name for script_result in script_set])
        self.assertEquals(RESULT_TYPE.COMMISSIONING, script_set.result_type)
        self.assertEquals(
            node.power_state, script_set.power_state_before_transition)

    def test_create_commissioning_script_set_adds_selected_scripts(self):
        scripts = [
            factory.make_Script(script_type=SCRIPT_TYPE.COMMISSIONING)
            for _ in range(10)
        ]
        node = factory.make_Node()
        script_selected_by_tag = random.choice(scripts)
        script_selected_by_name = random.choice(scripts)
        script_selected_by_id = random.choice(scripts)
        expected_scripts = list(NODE_INFO_SCRIPTS)
        expected_scripts.append(script_selected_by_tag.name)
        expected_scripts.append(script_selected_by_name.name)
        expected_scripts.append(script_selected_by_id.name)

        script_set = ScriptSet.objects.create_commissioning_script_set(
            node, scripts=[
                random.choice([
                    tag for tag in script_selected_by_tag.tags
                    if 'tag' in tag]),
                script_selected_by_name.name,
                script_selected_by_id.id,
            ])
        self.assertItemsEqual(
            set(expected_scripts),
            [script_result.name for script_result in script_set])
        self.assertEquals(RESULT_TYPE.COMMISSIONING, script_set.result_type)
        self.assertEquals(
            node.power_state, script_set.power_state_before_transition)

    def test_create_commissioning_script_set_cleans_up_past_limit(self):
        script_set_limit = Config.objects.get_config(
            'max_node_commissioning_results')
        node = factory.make_Node()
        for _ in range(script_set_limit * 2):
            factory.make_ScriptSet(
                node=node, result_type=RESULT_TYPE.COMMISSIONING)

        ScriptSet.objects.create_commissioning_script_set(node)

        self.assertEquals(
            script_set_limit,
            ScriptSet.objects.filter(
                node=node,
                result_type=RESULT_TYPE.COMMISSIONING).count())

    def test_create_commissioning_script_set_cleans_up_current(self):
        Config.objects.set_config('max_node_commissioning_results', 1)
        node = factory.make_Node()
        script_set = factory.make_ScriptSet(
            node=node, result_type=RESULT_TYPE.COMMISSIONING)
        node.current_commissioning_script_set = script_set
        node.save()

        ScriptSet.objects.create_commissioning_script_set(node)

        self.assertEquals(
            1,
            ScriptSet.objects.filter(
                node=node,
                result_type=RESULT_TYPE.COMMISSIONING).count())

    def test_create_commissioning_script_set_accepts_params(self):
        script = factory.make_Script(
            script_type=SCRIPT_TYPE.COMMISSIONING, parameters={
                'storage': {'type': 'storage'}})
        node = factory.make_Node()
        for _ in range(3):
            factory.make_PhysicalBlockDevice(node=node)

        script_set = ScriptSet.objects.create_commissioning_script_set(
            node, [script.name], {script.name: {'storage': 'all'}})

        self.assertItemsEqual(
            [bd.name for bd in node.physicalblockdevice_set],
            [
                script_result.parameters['storage']['value']['name']
                for script_result in script_set
                if script_result.script == script
            ])

    def test_create_commissioning_script_set_errors_params(self):
        script = factory.make_Script(
            script_type=SCRIPT_TYPE.COMMISSIONING, parameters={
                'storage': {'type': 'storage'}})
        node = factory.make_Node()

        self.assertRaises(
            ValidationError,
            ScriptSet.objects.create_commissioning_script_set,
            node, [script.name], {script.name: factory.make_name('unknown')})
        self.assertFalse(ScriptSet.objects.all().exists())

    def test_create_testing_script_set(self):
        node = factory.make_Node()
        expected_scripts = [
            factory.make_Script(
                script_type=SCRIPT_TYPE.TESTING, tags=['commissioning']).name
            for _ in range(3)
        ]

        script_set = ScriptSet.objects.create_testing_script_set(node)

        self.assertItemsEqual(
            expected_scripts,
            [script_result.name for script_result in script_set])
        self.assertEquals(RESULT_TYPE.TESTING, script_set.result_type)
        self.assertEquals(
            node.power_state, script_set.power_state_before_transition)

    def test_create_testing_script_set_adds_selected_scripts(self):
        scripts = [
            factory.make_Script(script_type=SCRIPT_TYPE.TESTING)
            for _ in range(10)
        ]
        script_selected_by_tag = random.choice(scripts)
        script_selected_by_name = random.choice(scripts)
        script_selected_by_id = random.choice(scripts)
        node = factory.make_Node()
        expected_scripts = [
            script_selected_by_tag.name,
            script_selected_by_name.name,
            script_selected_by_id.name,
        ]

        script_set = ScriptSet.objects.create_testing_script_set(
            node, scripts=[
                random.choice([
                    tag for tag in script_selected_by_tag.tags
                    if 'tag' in tag]),
                script_selected_by_name.name,
                script_selected_by_id.id,
            ])

        self.assertItemsEqual(
            set(expected_scripts),
            [script_result.name for script_result in script_set])
        self.assertEquals(RESULT_TYPE.TESTING, script_set.result_type)
        self.assertEquals(
            node.power_state, script_set.power_state_before_transition)

    def test_create_testing_script_raises_exception_when_none_found(self):
        node = factory.make_Node()
        self.assertRaises(
            NoScriptsFound,
            ScriptSet.objects.create_testing_script_set, node)

    def test_create_testing_script_set_cleans_up_past_limit(self):
        script_set_limit = Config.objects.get_config(
            'max_node_testing_results')
        node = factory.make_Node()
        for _ in range(script_set_limit * 2):
            factory.make_ScriptSet(
                node=node, result_type=RESULT_TYPE.TESTING)

        script = factory.make_Script(script_type=SCRIPT_TYPE.TESTING)
        ScriptSet.objects.create_testing_script_set(
            node, scripts=[script.name])

        self.assertEquals(
            script_set_limit,
            ScriptSet.objects.filter(
                node=node,
                result_type=RESULT_TYPE.TESTING).count())

    def test_create_testing_script_set_cleans_up_current(self):
        Config.objects.set_config('max_node_testing_results', 1)
        node = factory.make_Node()
        script_set = factory.make_ScriptSet(
            node=node, result_type=RESULT_TYPE.TESTING)
        node.current_testing_script_set = script_set
        node.save()

        script = factory.make_Script(script_type=SCRIPT_TYPE.TESTING)
        ScriptSet.objects.create_testing_script_set(
            node, scripts=[script.name])

        self.assertEquals(
            1,
            ScriptSet.objects.filter(
                node=node,
                result_type=RESULT_TYPE.TESTING).count())

    def test_create_testing_script_set_accepts_params(self):
        script = factory.make_Script(
            script_type=SCRIPT_TYPE.TESTING, parameters={
                'storage': {'type': 'storage'}})
        node = factory.make_Node()
        for _ in range(3):
            factory.make_PhysicalBlockDevice(node=node)

        script_set = ScriptSet.objects.create_testing_script_set(
            node, [script.name], {script.name: {'storage': 'all'}})

        self.assertItemsEqual(
            [bd.name for bd in node.physicalblockdevice_set],
            [
                script_result.parameters['storage']['value']['name']
                for script_result in script_set
                if script_result.script == script
            ])

    def test_create_testing_script_set_errors_params(self):
        script = factory.make_Script(
            script_type=SCRIPT_TYPE.TESTING, parameters={
                'storage': {'type': 'storage'}})
        node = factory.make_Node()

        self.assertRaises(
            ValidationError,
            ScriptSet.objects.create_testing_script_set,
            node, [script.name], {script.name: factory.make_name('unknown')})
        self.assertFalse(ScriptSet.objects.all().exists())

    def test_create_installation_script_set(self):
        node = factory.make_Node()

        script_set = ScriptSet.objects.create_installation_script_set(node)
        self.assertItemsEqual(
            [CURTIN_INSTALL_LOG],
            [script_result.name for script_result in script_set])
        self.assertEquals(RESULT_TYPE.INSTALLATION, script_set.result_type)
        self.assertEquals(
            node.power_state, script_set.power_state_before_transition)

    def test_create_installation_script_set_cleans_up_past_limit(self):
        script_set_limit = Config.objects.get_config(
            'max_node_installation_results')
        node = factory.make_Node()
        for _ in range(script_set_limit * 2):
            factory.make_ScriptSet(
                node=node, result_type=RESULT_TYPE.INSTALLATION)

        ScriptSet.objects.create_installation_script_set(node)

        self.assertEquals(
            script_set_limit,
            ScriptSet.objects.filter(
                node=node,
                result_type=RESULT_TYPE.INSTALLATION).count())

    def test_create_installation_script_set_cleans_up_current(self):
        Config.objects.get_config('max_node_installation_results', 1)
        node = factory.make_Node()
        script_set = factory.make_ScriptSet(
            node=node, result_type=RESULT_TYPE.INSTALLATION)
        node.current_installation_script_set = script_set
        node.save()

        ScriptSet.objects.create_installation_script_set(node)

        self.assertEquals(
            1,
            ScriptSet.objects.filter(
                node=node,
                result_type=RESULT_TYPE.INSTALLATION).count())


class TestScriptSet(MAASServerTestCase):
    """Test the ScriptSet model."""

    def test_find_script_result_by_id(self):
        script_set = factory.make_ScriptSet()
        script_results = [
            factory.make_ScriptResult(script_set=script_set)
            for _ in range(3)
        ]
        script_result = random.choice(script_results)
        self.assertEquals(
            script_result,
            script_set.find_script_result(script_result_id=script_result.id))

    def test_find_script_result_by_name(self):
        script_set = factory.make_ScriptSet()
        script_results = [
            factory.make_ScriptResult(script_set=script_set)
            for _ in range(3)
        ]
        script_result = random.choice(script_results)
        self.assertEquals(
            script_result,
            script_set.find_script_result(script_name=script_result.name))

    def test_find_script_result_returns_none_when_not_found(self):
        script_set = factory.make_ScriptSet()
        self.assertIsNone(script_set.find_script_result())

    def test_status(self):
        statuses = {
            SCRIPT_STATUS.RUNNING: (
                SCRIPT_STATUS.INSTALLING, SCRIPT_STATUS.PENDING,
                SCRIPT_STATUS.ABORTED, SCRIPT_STATUS.FAILED,
                SCRIPT_STATUS.FAILED_INSTALLING, SCRIPT_STATUS.TIMEDOUT,
                SCRIPT_STATUS.PENDING, SCRIPT_STATUS.DEGRADED,
                SCRIPT_STATUS.PASSED),
            SCRIPT_STATUS.PENDING: (
                SCRIPT_STATUS.ABORTED, SCRIPT_STATUS.FAILED,
                SCRIPT_STATUS.FAILED_INSTALLING, SCRIPT_STATUS.TIMEDOUT,
                SCRIPT_STATUS.DEGRADED, SCRIPT_STATUS.PASSED),
            SCRIPT_STATUS.ABORTED: (
                SCRIPT_STATUS.FAILED, SCRIPT_STATUS.FAILED_INSTALLING,
                SCRIPT_STATUS.TIMEDOUT, SCRIPT_STATUS.PASSED,
                SCRIPT_STATUS.DEGRADED),
            SCRIPT_STATUS.FAILED: (
                SCRIPT_STATUS.FAILED_INSTALLING, SCRIPT_STATUS.TIMEDOUT,
                SCRIPT_STATUS.DEGRADED, SCRIPT_STATUS.PASSED),
            SCRIPT_STATUS.TIMEDOUT: (
                SCRIPT_STATUS.DEGRADED, SCRIPT_STATUS.PASSED,),
            SCRIPT_STATUS.DEGRADED: (SCRIPT_STATUS.PASSED,),
            SCRIPT_STATUS.PASSED: (SCRIPT_STATUS.PASSED,),
        }
        for status, other_statuses in statuses.items():
            script_set = factory.make_ScriptSet()
            factory.make_ScriptResult(
                script_set=script_set, status=status)
            for _ in range(3):
                factory.make_ScriptResult(
                    script_set=script_set,
                    status=random.choice(other_statuses))
            if status == SCRIPT_STATUS.TIMEDOUT:
                status = SCRIPT_STATUS.FAILED
            self.assertEquals(status, script_set.status)

    def test_started(self):
        script_set = factory.make_ScriptSet()
        now = datetime.now()
        started = now - timedelta(seconds=random.randint(1, 500))
        factory.make_ScriptResult(script_set=script_set, started=now)
        factory.make_ScriptResult(script_set=script_set, started=started)
        self.assertEquals(started, script_set.started)

    def test_ended(self):
        script_set = factory.make_ScriptSet()
        ended = datetime.now() + timedelta(seconds=random.randint(1, 500))
        factory.make_ScriptResult(
            script_set=script_set, status=SCRIPT_STATUS.PASSED)
        factory.make_ScriptResult(
            script_set=script_set, status=SCRIPT_STATUS.PASSED, ended=ended)
        self.assertEquals(ended, script_set.ended)

    def test_ended_returns_none_when_not_all_results_finished(self):
        script_set = factory.make_ScriptSet()
        factory.make_ScriptResult(
            script_set=script_set, status=SCRIPT_STATUS.PASSED)
        factory.make_ScriptResult(
            script_set=script_set, status=SCRIPT_STATUS.RUNNING)
        self.assertIsNone(script_set.ended)

    def test_get_runtime(self):
        script_set = factory.make_ScriptSet()
        runtime_seconds = random.randint(1, 59)
        now = datetime.now()
        factory.make_ScriptResult(
            script_set=script_set, status=SCRIPT_STATUS.PASSED,
            started=now - timedelta(seconds=runtime_seconds), ended=now)
        if runtime_seconds < 10:
            text_seconds = '0%d' % runtime_seconds
        else:
            text_seconds = '%d' % runtime_seconds
        self.assertEquals('0:00:%s' % text_seconds, script_set.runtime)

    def test_get_runtime_blank_when_missing(self):
        script_set = factory.make_ScriptSet()
        factory.make_ScriptResult(
            script_set=script_set, status=SCRIPT_STATUS.PENDING)
        self.assertEquals('', script_set.runtime)

    def test_regenerate(self):
        node = factory.make_Node()
        script_set = factory.make_ScriptSet(node=node)

        passed_storage_script = factory.make_Script(parameters={'storage': {
            'type': 'storage'}})
        passed_storage_parameters = {'storage': {
            'type': 'storage',
            'value': {
                'name': factory.make_name('name'),
                'model': factory.make_name('model'),
                'serial': factory.make_name('serial'),
                'id_path': '/dev/%s' % factory.make_name('id_path'),
            },
        }}
        passed_storage_script_result = factory.make_ScriptResult(
            script_set=script_set, status=SCRIPT_STATUS.PASSED,
            script=passed_storage_script, parameters=passed_storage_parameters)

        pending_storage_script = factory.make_Script(parameters={'storage': {
            'type': 'storage'}})
        pending_storage_parameters = {'storage': {
            'type': 'storage',
            'value': {
                'name': factory.make_name('name'),
                'model': factory.make_name('model'),
                'serial': factory.make_name('serial'),
                'id_path': '/dev/%s' % factory.make_name('id_path'),
            },
        }}
        pending_storage_script_result = factory.make_ScriptResult(
            script_set=script_set, status=SCRIPT_STATUS.PENDING,
            script=pending_storage_script,
            parameters=pending_storage_parameters)

        pending_other_script = factory.make_ScriptResult(script_set=script_set)

        script_set.regenerate()

        passed_storage_script_result = reload_object(
            passed_storage_script_result)
        self.assertIsNotNone(passed_storage_script_result)
        self.assertDictEqual(
            passed_storage_parameters, passed_storage_script_result.parameters)
        self.assertIsNone(reload_object(pending_storage_script_result))
        self.assertIsNotNone(reload_object(pending_other_script))

        new_storage_script_result = script_set.scriptresult_set.get(
            script=pending_storage_script)
        bd = node.physicalblockdevice_set.first()
        self.assertDictEqual({'storage': {
            'type': 'storage',
            'value': {
                'name': bd.name,
                'model': bd.model,
                'serial': bd.serial,
                'id_path': bd.id_path,
                'physical_blockdevice_id': bd.id,
            }}}, new_storage_script_result.parameters)

    def test_regenerate_logs_failure(self):
        mock_logger = self.patch(scriptset_module.logger, 'error')
        node = factory.make_Node()
        script_set = factory.make_ScriptSet(node=node)

        pending_storage_script = factory.make_Script(parameters={
            'storage': {'type': 'storage'},
            'runtime': {'type': 'runtime'},
            })
        pending_storage_parameters = {
            'storage': {
                'type': 'storage',
                'value': {
                    'name': factory.make_name('name'),
                    'model': factory.make_name('model'),
                    'serial': factory.make_name('serial'),
                    'id_path': '/dev/%s' % factory.make_name('id_path'),
                },
            },
            'runtime': {
                'type': 'runtime',
                'value': factory.make_name('invalid_value'),
            },
        }
        pending_storage_script_result = factory.make_ScriptResult(
            script_set=script_set, status=SCRIPT_STATUS.PENDING,
            script=pending_storage_script,
            parameters=pending_storage_parameters)

        script_set.regenerate()

        self.assertIsNone(reload_object(pending_storage_script_result))
        self.assertItemsEqual([], list(script_set))
        expected_msg = (
            "Removing Script %s from ScriptSet due to regeneration "
            "error - {'runtime': ['Must be an int']}" %
            pending_storage_script.name)
        event_type = EventType.objects.get(
            name=EVENT_TYPES.SCRIPT_RESULT_ERROR)
        event = Event.objects.get(node=node, type_id=event_type.id)
        self.assertEquals(expected_msg, event.description)
        self.assertThat(mock_logger, MockCalledOnceWith(expected_msg))

    def test_delete(self):
        node = factory.make_Node(with_empty_script_sets=True)
        orig_commissioning_script_set = node.current_commissioning_script_set
        orig_testing_script_set = node.current_testing_script_set
        orig_installation_script_set = node.current_installation_script_set
        script_set = factory.make_ScriptSet(node=node)

        script_set.delete()

        node = reload_object(node)
        self.assertIsNone(reload_object(script_set))
        self.assertEquals(
            orig_commissioning_script_set,
            node.current_commissioning_script_set)
        self.assertEquals(
            orig_testing_script_set, node.current_testing_script_set)
        self.assertEquals(
            orig_installation_script_set, node.current_installation_script_set)

    def test_delete_prevents_del_of_current_commissioning_script_set(self):
        node = factory.make_Node(with_empty_script_sets=True)
        self.assertRaises(
            ValidationError, node.current_commissioning_script_set.delete)

    def test_delete_prevents_del_of_current_installation_script_set(self):
        node = factory.make_Node(with_empty_script_sets=True)
        self.assertRaises(
            ValidationError, node.current_installation_script_set.delete)

    def test_delete_sets_current_testing_script_set_to_older_version(self):
        node = factory.make_Node(with_empty_script_sets=True)
        previous_script_set = factory.make_ScriptSet(
            node=node, result_type=RESULT_TYPE.TESTING)
        node.current_testing_script_set = factory.make_ScriptSet(
            node=node, result_type=RESULT_TYPE.TESTING)
        node.save()

        node.current_testing_script_set.delete()
        self.assertEquals(
            previous_script_set,
            reload_object(node).current_testing_script_set)
