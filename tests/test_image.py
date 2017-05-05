import os
from pkg_resources import parse_version
from unittest.mock import Mock, patch

import pytest

import vr.runners.image as I
from vr.common.models import ProcData
from vr.common.paths import get_container_path


@pytest.fixture()
def runner():
    r = I.ImageRunner()
    r.config = ProcData({
        'app_name': 'myApp',
        'proc_name': 'proc.exe',
        'port': 1234,
        'release_hash': 'deadbeef',
        'version': '1.0',
        'config_name': 'config-name',
        'image_name': 'image-name',
        'cmd': 'command',
        # 'env': {},
    })
    r.ensure_image = Mock()
    r.ensure_char_devices = Mock()
    return r


class TestImageRunner(object):

    @patch('vr.runners.image.get_lxc_version')
    def test_setup(self, get_lxc_version_, runner):
        get_lxc_version_.return_value = parse_version('1.0.8')
        runner.setup()
        p = get_container_path(runner.config)
        assert os.path.exists(os.path.join(p, 'env.sh')), 'env.sh missing'
        assert os.path.exists(os.path.join(p, 'proc.sh')), 'proc.sh missing'
        assert os.path.exists(os.path.join(p, 'settings.yaml')), \
            'settings.yaml missing'
        assert os.path.exists(os.path.join(p, '../proc.lxc')), \
            'proc.lxc missing'
        assert os.path.isdir(os.path.join(p, '../work')), \
            'work_dir does not exists'

    @patch('vr.runners.image.get_lxc_version')
    def test_proc_lxc(self, get_lxc_version_, runner):
        get_lxc_version_.return_value = parse_version('1.0.8')
        runner.setup()
        p = get_container_path(runner.config)
        proc_lxc = open(os.path.join(p, '../proc.lxc'), 'r').read()

        assert 'lxc.network.type = none' in proc_lxc
        assert 'lxc.mount.entry = overlayfs ' in proc_lxc

    @patch('vr.runners.image.get_lxc_version')
    def test_proc_lxc_lxc_pre1(self, get_lxc_version_, runner):
        get_lxc_version_.return_value = parse_version('0.9.9')
        runner.setup()
        p = get_container_path(runner.config)
        proc_lxc = open(os.path.join(p, '../proc.lxc'), 'r').read()

        assert 'lxc.network.type = none' not in proc_lxc
        assert 'lxc.mount.entry = overlayfs ' in proc_lxc
        assert 'workdir' not in proc_lxc

    @patch('vr.runners.image.get_lxc_version')
    def test_proc_lxc_lxc_post2(self, get_lxc_version_, runner):
        get_lxc_version_.return_value = parse_version('2.0.1')
        runner.setup()
        p = get_container_path(runner.config)
        proc_lxc = open(os.path.join(p, '../proc.lxc'), 'r').read()

        assert 'lxc.network.type = none' in proc_lxc
        assert 'lxc.mount.entry = overlay ' in proc_lxc
        assert 'workdir' in proc_lxc
