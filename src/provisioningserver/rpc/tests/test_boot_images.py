# Copyright 2014-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for provisioningserver.rpc.boot_images"""

__all__ = []

import os
from random import randint
from unittest.mock import (
    ANY,
    sentinel,
)

from maastesting.factory import factory
from maastesting.matchers import (
    MockCalledOnceWith,
    MockNotCalled,
)
from maastesting.testcase import (
    MAASTestCase,
    MAASTwistedRunTest,
)
from provisioningserver import concurrency
from provisioningserver.boot import tftppath
from provisioningserver.import_images import boot_resources
from provisioningserver.rpc import (
    boot_images,
    region,
)
from provisioningserver.rpc.boot_images import (
    _run_import,
    fix_sources_for_cluster,
    get_hosts_from_sources,
    import_boot_images,
    is_import_boot_images_running,
    list_boot_images,
    reload_boot_images,
)
from provisioningserver.rpc.region import UpdateLastImageSync
from provisioningserver.rpc.testing import MockLiveClusterToRegionRPCFixture
from provisioningserver.testing.config import (
    BootSourcesFixture,
    ClusterConfigurationFixture,
)
from provisioningserver.utils.twisted import pause
from testtools.matchers import (
    Equals,
    Is,
)
from twisted.internet import defer
from twisted.internet.defer import (
    inlineCallbacks,
    succeed,
)
from twisted.internet.task import Clock


def make_sources():
    hosts = [factory.make_name('host').lower() for _ in range(3)]
    urls = [
        'http://%s:%s/images-stream/streams/v1/index.json' % (
            host, randint(1, 1000))
        for host in hosts
        ]
    sources = [
        {'url': url, 'selections': []}
        for url in urls
        ]
    return sources, hosts


class TestListBootImages(MAASTestCase):

    def setUp(self):
        super(TestListBootImages, self).setUp()
        self.tftp_root = self.make_dir()
        self.useFixture(ClusterConfigurationFixture(tftp_root=self.tftp_root))

    def test__calls_list_boot_images_with_boot_resource_storage(self):
        self.patch(boot_images, 'CACHED_BOOT_IMAGES', None)
        mock_list_boot_images = self.patch(tftppath, 'list_boot_images')
        list_boot_images()
        self.assertThat(
            mock_list_boot_images,
            MockCalledOnceWith(self.tftp_root))

    def test__calls_list_boot_images_when_cache_is_None(self):
        self.patch(boot_images, 'CACHED_BOOT_IMAGES', None)
        mock_list_boot_images = self.patch(tftppath, 'list_boot_images')
        list_boot_images()
        self.assertThat(
            mock_list_boot_images,
            MockCalledOnceWith(ANY))

    def test__doesnt_call_list_boot_images_when_cache_is_not_None(self):
        fake_boot_images = [factory.make_name('image') for _ in range(3)]
        self.patch(boot_images, 'CACHED_BOOT_IMAGES', fake_boot_images)
        mock_list_boot_images = self.patch(tftppath, 'list_boot_images')
        self.expectThat(list_boot_images(), Equals(fake_boot_images))
        self.expectThat(
            mock_list_boot_images,
            MockNotCalled())


class TestReloadBootImages(MAASTestCase):

    def test__sets_CACHED_BOOT_IMAGES(self):
        self.patch(
            boot_images, 'CACHED_BOOT_IMAGES', factory.make_name('old_cache'))
        fake_boot_images = [factory.make_name('image') for _ in range(3)]
        mock_list_boot_images = self.patch(tftppath, 'list_boot_images')
        mock_list_boot_images.return_value = fake_boot_images
        reload_boot_images()
        self.assertEqual(
            boot_images.CACHED_BOOT_IMAGES, fake_boot_images)


class TestGetHostsFromSources(MAASTestCase):

    def test__returns_set_of_hosts_from_sources(self):
        sources, hosts = make_sources()
        self.assertItemsEqual(hosts, get_hosts_from_sources(sources))


class TestFixSourcesForCluster(MAASTestCase):

    def set_maas_url(self, url):
        self.useFixture(ClusterConfigurationFixture(maas_url=url))

    def test__removes_matching_path_from_maas_url_with_extra_slashes(self):
        self.set_maas_url("http://192.168.122.2/MAAS/////")
        sources = [
            {
                "url": "http://localhost/MAAS/images/index.json"
            }
        ]
        observed = fix_sources_for_cluster(sources)
        self.assertEqual(
            "http://192.168.122.2/MAAS/images/index.json",
            observed[0]['url'])

    def test__removes_matching_path_from_maas_url(self):
        self.set_maas_url("http://192.168.122.2/MAAS/")
        sources = [
            {
                "url": "http://localhost/MAAS/images/index.json"
            }
        ]
        observed = fix_sources_for_cluster(sources)
        self.assertEqual(
            "http://192.168.122.2/MAAS/images/index.json",
            observed[0]['url'])

    def test__removes_matching_path_with_extra_slashes_from_maas_url(self):
        self.set_maas_url("http://192.168.122.2/MAAS/")
        sources = [
            {
                "url": "http://localhost///MAAS///images/index.json"
            }
        ]
        observed = fix_sources_for_cluster(sources)
        self.assertEqual(
            "http://192.168.122.2/MAAS/images/index.json",
            observed[0]['url'])

    def test__doesnt_remove_non_matching_path_from_maas_url(self):
        self.set_maas_url("http://192.168.122.2/not-matching/")
        sources = [
            {
                "url": "http://localhost/MAAS/images/index.json"
            }
        ]
        observed = fix_sources_for_cluster(sources)
        self.assertEqual(
            "http://192.168.122.2/not-matching/MAAS/images/index.json",
            observed[0]['url'])

    def test__doesnt_remove_non_matching_path_from_maas_url_with_slashes(self):
        self.set_maas_url("http://192.168.122.2/not-matching////")
        sources = [
            {
                "url": "http://localhost///MAAS/images/index.json"
            }
        ]
        observed = fix_sources_for_cluster(sources)
        self.assertEqual(
            "http://192.168.122.2/not-matching/MAAS/images/index.json",
            observed[0]['url'])


class TestRunImport(MAASTestCase):

    def make_archive_url(self, name=None):
        if name is None:
            name = factory.make_name('archive')
        return 'http://%s.example.com/%s' % (name, factory.make_name('path'))

    def patch_boot_resources_function(self):
        """Patch out `boot_resources.import_images`.

        Returns the installed fake.  After the fake has been called, but not
        before, its `env` attribute will have a copy of the environment dict.
        """

        class CaptureEnv:
            """Fake function; records a copy of the environment."""

            def __call__(self, *args, **kwargs):
                self.args = args
                self.env = os.environ.copy()

        return self.patch(boot_resources, 'import_images', CaptureEnv())

    def test__run_import_integrates_with_boot_resources_function(self):
        # If the config specifies no sources, nothing will be imported.  But
        # the task succeeds without errors.
        fixture = self.useFixture(BootSourcesFixture([]))
        self.patch(boot_resources, 'logger')
        self.patch(boot_resources, 'locate_config').return_value = (
            fixture.filename)
        self.assertThat(_run_import(sources=[]), Is(False))

    def test__run_import_sets_GPGHOME(self):
        home = factory.make_name('home')
        self.patch(boot_images, 'get_maas_user_gpghome').return_value = home
        fake = self.patch_boot_resources_function()
        _run_import(sources=[])
        self.assertEqual(home, fake.env['GNUPGHOME'])

    def test__run_import_sets_proxy_if_given(self):
        proxy = 'http://%s.example.com' % factory.make_name('proxy')
        fake = self.patch_boot_resources_function()
        _run_import(sources=[], http_proxy=proxy, https_proxy=proxy)
        self.expectThat(fake.env['http_proxy'], Equals(proxy))
        self.expectThat(fake.env['https_proxy'], Equals(proxy))

    def test__run_import_sets_proxy_for_loopback(self):
        fake = self.patch_boot_resources_function()
        _run_import(sources=[])
        self.assertEqual(
            fake.env['no_proxy'],
            "localhost,::ffff:127.0.0.1,127.0.0.1,::1")

    def test__run_import_sets_proxy_for_source_host(self):
        host = factory.make_name("host").lower()
        maas_url = "http://%s/" % host
        self.useFixture(ClusterConfigurationFixture(maas_url=maas_url))
        sources, _ = make_sources()
        fake = self.patch_boot_resources_function()
        _run_import(sources=sources)
        self.assertItemsEqual(
            fake.env['no_proxy'].split(','),
            ["localhost", "::ffff:127.0.0.1", "127.0.0.1", "::1"] + [host])

    def test__run_import_accepts_sources_parameter(self):
        fake = self.patch(boot_resources, 'import_images')
        sources, _ = make_sources()
        _run_import(sources=sources)
        self.assertThat(fake, MockCalledOnceWith(sources))

    def test__run_import_calls_reload_boot_images(self):
        fake_reload = self.patch(boot_images, 'reload_boot_images')
        self.patch(boot_resources, 'import_images')
        sources, _ = make_sources()
        _run_import(sources=sources)
        self.assertThat(fake_reload, MockCalledOnceWith())


class TestImportBootImages(MAASTestCase):

    run_tests_with = MAASTwistedRunTest.make_factory(timeout=5)

    @defer.inlineCallbacks
    def test__does_not_run_if_lock_taken(self):
        yield concurrency.boot_images.acquire()
        self.addCleanup(concurrency.boot_images.release)
        deferToThread = self.patch(boot_images, 'deferToThread')
        deferToThread.return_value = defer.succeed(None)
        yield import_boot_images(sentinel.sources)
        self.assertThat(
            deferToThread, MockNotCalled())

    @defer.inlineCallbacks
    def test__calls__run_import_using_deferToThread(self):
        deferToThread = self.patch(boot_images, 'deferToThread')
        deferToThread.return_value = defer.succeed(None)
        yield import_boot_images(sentinel.sources)
        self.assertThat(
            deferToThread, MockCalledOnceWith(
                _run_import, sentinel.sources,
                http_proxy=None, https_proxy=None))

    def test__takes_lock_when_running(self):
        clock = Clock()
        deferToThread = self.patch(boot_images, 'deferToThread')
        deferToThread.return_value = pause(1, clock)

        # Lock is acquired when import is started.
        import_boot_images(sentinel.sources)
        self.assertTrue(concurrency.boot_images.locked)

        # Lock is released once the download is done.
        clock.advance(1)
        self.assertFalse(concurrency.boot_images.locked)

    @inlineCallbacks
    def test_update_last_image_sync(self):
        get_maas_id = self.patch(boot_images, "get_maas_id")
        get_maas_id.return_value = factory.make_string()
        getRegionClient = self.patch(boot_images, "getRegionClient")
        _run_import = self.patch_autospec(boot_images, '_run_import')
        _run_import.return_value = True
        yield boot_images._import_boot_images(sentinel.sources)
        self.assertThat(
            _run_import, MockCalledOnceWith(sentinel.sources, None, None))
        self.assertThat(getRegionClient, MockCalledOnceWith())
        self.assertThat(get_maas_id, MockCalledOnceWith())
        client = getRegionClient.return_value
        self.assertThat(
            client, MockCalledOnceWith(
                UpdateLastImageSync, system_id=get_maas_id()))

    @inlineCallbacks
    def test_update_last_image_sync_not_performed(self):
        get_maas_id = self.patch(boot_images, "get_maas_id")
        get_maas_id.return_value = factory.make_string()
        getRegionClient = self.patch(boot_images, "getRegionClient")
        _run_import = self.patch_autospec(boot_images, '_run_import')
        _run_import.return_value = False
        yield boot_images._import_boot_images(sentinel.sources)
        self.assertThat(
            _run_import, MockCalledOnceWith(sentinel.sources, None, None))
        self.assertThat(getRegionClient, MockNotCalled())
        self.assertThat(get_maas_id, MockNotCalled())

    @inlineCallbacks
    def test_update_last_image_sync_end_to_end(self):
        get_maas_id = self.patch(boot_images, "get_maas_id")
        get_maas_id.return_value = factory.make_string()
        self.useFixture(ClusterConfigurationFixture())
        fixture = self.useFixture(MockLiveClusterToRegionRPCFixture())
        protocol, connecting = fixture.makeEventLoop(
            region.UpdateLastImageSync)
        protocol.UpdateLastImageSync.return_value = succeed({})
        self.addCleanup((yield connecting))
        self.patch_autospec(boot_resources, 'import_images')
        boot_resources.import_images.return_value = True
        sources, hosts = make_sources()
        yield boot_images.import_boot_images(sources)
        self.assertThat(
            boot_resources.import_images,
            MockCalledOnceWith(sources))
        self.assertThat(
            protocol.UpdateLastImageSync,
            MockCalledOnceWith(protocol, system_id=get_maas_id()))

    @inlineCallbacks
    def test_update_last_image_sync_end_to_end_import_not_performed(self):
        self.useFixture(ClusterConfigurationFixture())
        fixture = self.useFixture(MockLiveClusterToRegionRPCFixture())
        protocol, connecting = fixture.makeEventLoop(
            region.UpdateLastImageSync)
        protocol.UpdateLastImageSync.return_value = succeed({})
        self.addCleanup((yield connecting))
        self.patch_autospec(boot_resources, 'import_images')
        boot_resources.import_images.return_value = False
        sources, hosts = make_sources()
        yield boot_images.import_boot_images(sources)
        self.assertThat(
            boot_resources.import_images,
            MockCalledOnceWith(sources))
        self.assertThat(
            protocol.UpdateLastImageSync,
            MockNotCalled())


class TestIsImportBootImagesRunning(MAASTestCase):

    run_tests_with = MAASTwistedRunTest.make_factory(timeout=5)

    @defer.inlineCallbacks
    def test__returns_True_when_lock_is_held(self):
        yield concurrency.boot_images.acquire()
        self.addCleanup(concurrency.boot_images.release)
        self.assertTrue(is_import_boot_images_running())

    def test__returns_False_when_lock_is_not_held(self):
        self.assertFalse(is_import_boot_images_running())
