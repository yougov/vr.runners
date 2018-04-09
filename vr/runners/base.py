# pylint: disable=attribute-defined-outside-init,redefined-outer-name
from __future__ import print_function

import argparse
import hashlib
import os
import shutil
import stat
import tarfile

import pkg_resources
import requests
import yaml
import path
import six

from vr.common.paths import (
    get_container_name, get_buildfile_path, BUILDS_ROOT, get_app_path,
    get_container_path, get_proc_path, get_lxc_work_path)
from vr.common.models import ProcData
from vr.common.utils import (
    tmpdir, mkdir, lock_file, which, file_md5,
    get_lxc_version, get_lxc_network_config)


def get_version():
    try:
        return pkg_resources.get_distribution('vr.runners').version
    except Exception:
        return None


class BaseRunner(object):
    """
    >>> callable(BaseRunner.shell.lock)
    True
    """

    def main(self):
        self.commands = {
            'setup': self.setup,
            'run': self.run,
            'shell': self.shell,
            'uptest': self.uptest,
            'teardown': self.teardown,
        }

        # pylint: disable=unused-variable
        cmd_list = ', '.join(self.commands)
        parser = argparse.ArgumentParser()
        cmd_help = 'One of: {cmd_list}'.format(**locals())
        parser.add_argument('command', help=cmd_help)
        parser.add_argument('file', help="Path to proc.yaml file.")
        parser.add_argument(
            '--version', action='version', version=get_version())

        args = parser.parse_args()

        try:
            cmd = self.commands[args.command]
        except KeyError:
            msg = 'Command must be one of: {cmd_list}'.format(**locals())
            raise SystemExit(msg)

        with open(args.file, 'r+b') as fid:
            self.config = ProcData(yaml.safe_load(fid))

            # Lock the file for exclusive access. Some commands (such as shell
            # or uptest) may override the behavior by providing a 'lock'
            # attribute on the method.
            getattr(cmd, 'lock', lock_file)(fid)
            cmd()

    @property
    def container_name(self):
        return get_container_name(self.config)

    # pylint: disable=no-self-argument,no-member
    def __close_file(fid):
        fid.close()

    def setup(self):
        print("Setting up", self.container_name)
        self.make_proc_dirs()
        self.ensure_build()
        self.write_proc_lxc()
        self.write_settings_yaml()
        self.write_proc_sh()
        self.write_env_sh()

    def run(self):
        print("Running", self.container_name)
        self._lxc_start()

    def shell(self):
        print("Running shell for", self.container_name)
        self._lxc_start(special_cmd='/bin/bash')
    shell.lock = __close_file

    def untar(self):
        tarpath = get_buildfile_path(self.config)
        print("Untarring", tarpath)
        outfolder = get_app_path(self.config)
        owners = (self.config.user, self.config.group)
        untar(tarpath, outfolder, owners)

    def write_proc_sh(self):
        """
        Write the script that is the first thing called inside the
        container.  It sets env vars and then calls the real program.
        """
        print("Writing proc.sh")
        context = {
            'tmp': '/tmp',
            'home': '/app',
            'settings': '/settings.yaml',
            'envsh': '/env.sh',
            'port': self.config.port,
            'cmd': self.get_cmd(),
        }
        sh_path = os.path.join(get_container_path(self.config), 'proc.sh')
        rendered = get_template('proc.sh') % context
        with open(sh_path, 'w') as f:
            f.write(rendered)
        st = os.stat(sh_path)
        os.chmod(
            sh_path, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def write_env_sh(self):
        print("Writing env.sh")
        envsh_path = os.path.join(get_container_path(self.config), 'env.sh')

        with open(envsh_path, 'w') as f:

            def _interpolate(val):
                if isinstance(val, six.string_types) and val.startswith('$'):
                    return os.environ.get(val[1:], '')
                return val

            def format_var(key, val):
                return 'export %s="%s"' % (key, _interpolate(val))

            e = self.config.env or {}
            env_str = '\n'.join(format_var(k, e[k]) for k in e) + '\n'
            f.write(env_str)

    def get_cmd(self):
        """
        If self.config.cmd is not None, return that.

        Otherwise, read the Procfile inside the build code, parse it
        (as yaml), and pull out the command for self.config.proc_name.
        """
        if self.config.cmd is not None:
            return self.config.cmd

        procfile_path = os.path.join(get_app_path(self.config), 'Procfile')
        with open(procfile_path, 'r') as f:
            procs = yaml.safe_load(f)
        return procs[self.config.proc_name]

    def ensure_container(self, name=None):
        """Make sure container exists. It's only needed on newer
        versions of LXC."""
        if get_lxc_version() < pkg_resources.parse_version('2.0.0'):
            # Nothing to do for old versions of LXC
            return

        if name is None:
            name = self.container_name

        args = [
            'lxc-create',
            '--name', name,
            '--template', 'none',
            '>', '/dev/null', '2>&1',
        ]
        os.system(' '.join(args))

    def ensure_build(self):
        """
        If self.config.build_url is set, ensure it's been downloaded to the
        builds folder.
        """
        if self.config.build_url:
            path = get_buildfile_path(self.config)

            # Ensure that builds_root has been created.
            mkdir(BUILDS_ROOT)
            build_md5 = getattr(self.config, 'build_md5', None)
            ensure_file(self.config.build_url, path, build_md5)

            # Now untar.
            self.untar()

    def write_settings_yaml(self):
        print("Writing settings.yaml")
        path = os.path.join(get_container_path(self.config), 'settings.yaml')
        with open(path, 'w') as f:
            f.write(
                yaml.safe_dump(self.config.settings, default_flow_style=False))

    def _lxc_start(self, special_cmd=None):
        args = self.get_lxc_args(special_cmd=special_cmd)
        os.execve(which('lxc-start')[0], args, {})

    def get_lxc_args(self, special_cmd=None):

        name = self.container_name
        if special_cmd:
            cmd = special_cmd
            # Container names must be unique, so to allow running a shell or
            # uptests next to the app container, add more
            # stuff to the name. Assumes that "special_cmd" are
            # ephemeral, so create a unique container name per
            # special_cmd, to allow creating too many containers (new
            # versions of LXC don't clean after themselves).
            # Use a hash of the command to eliminate characters that
            # are invalid filename characters.

            # Note: container name can't be too long, because of a
            # limitation of earlier versions of LXC
            uniq = hashlib.md5(special_cmd.encode('utf-8')).hexdigest()[:8]
            stuff = '-TMP' + uniq
            name += stuff

            self.ensure_container(name)
        else:
            cmd = 'run'

        # If we have an app_folder value, then we can use it to determine where
        # LXC debug logs can live (which is somewhere that build processes are
        # able to access if they want it).
        log_args = []
        if getattr(self.config, 'app_folder', None):
            log_args = [
                '--logpriority', 'debug',
                '--logfile', os.path.join(
                    self.config.app_folder, '.lxcdebug.log'),
            ]

        extra_params = []
        if get_lxc_version() >= pkg_resources.parse_version('2.0.0'):
            # Early versions of LXC either didn't have the
            # --foreground flag or defaulted to it.
            extra_params.append('--foreground')

        return [
            'lxc-start',
            '--name', name,
            '--rcfile', os.path.join(get_proc_path(self.config), 'proc.lxc'),
        ] + extra_params + log_args + [
            '--',

            # Note: using `su` seems to crash lxc container when
            # building certain Py3 projects.
            # See comments on:
            # https://bitbucket.org/yougov/vr.runners/commits/05ba82d54636db8e0e0791ee470742d0ef440715
            # Note: use short options (long options are not supported
            # by old version of sudo)

            'sudo',
            '-u', self.config.user,
            '-E',  # preserve environment
            '-s', '/bin/bash',  # shell
            '-c', 'cd /app;source /env.sh; exec /proc.sh "%s"' % cmd,
        ]

    def get_lxc_volume_str(self):
        content = ''
        # append lines to bind-mount volumes.
        volumes = getattr(self.config, 'volumes', []) or []
        volume_tmpl = "\nlxc.mount.entry = %s %s%s none bind 0 0"
        for outside, inside in volumes:
            content += volume_tmpl % (
                outside, get_container_path(self.config), inside)
        return content

    def uptest(self):
        # copy the uptester into the container. ensure it's executable.
        src = pkg_resources.resource_filename(
            'vr.runners', 'uptester/uptester')
        container_path = get_container_path(self.config)
        dest = os.path.join(container_path, 'uptester')
        shutil.copy(src, dest)
        st = os.stat(dest)
        os.chmod(dest, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        proc_name = getattr(self.config, 'proc_name', None)
        if proc_name:
            app_path = get_app_path(self.config)
            uptests_path = os.path.join(app_path, 'uptests', proc_name)
            if os.path.isdir(uptests_path):
                # run an LXC container for the uptests.
                inside_path = os.path.join('/app/uptests', proc_name)
                cmd = '/uptester %s %s %s ' % (inside_path, self.config.host,
                                               self.config.port)
                self._lxc_start(special_cmd=cmd)
            else:
                # There are no uptests for this proc.  Output an empty
                # JSON list.
                print("[]")
    uptest.lock = __close_file

    def teardown(self):
        """
        Delete the proc path where everything has been put.
        The build will be cleaned up elsewhere.
        """
        proc_path = get_proc_path(self.config)
        if os.path.isdir(proc_path):
            shutil.rmtree(proc_path)

    def make_proc_dirs(self):
        print("Making directories")

        proc_path = get_proc_path(self.config)
        mkdir(proc_path)

        container_path = get_container_path(self.config)
        mkdir(container_path)

        work_path = get_lxc_work_path(self.config)
        mkdir(work_path)

        volumes = getattr(self.config, 'volumes', None) or []
        for _, inside in volumes:
            mkdir(os.path.join(container_path, inside.lstrip('/')))

    def get_lxc_memory_limits(self):
        lines = []
        mem_limit = getattr(self.config, 'mem_limit', None)
        if mem_limit:
            lines.append(
                'lxc.cgroup.memory.limit_in_bytes = {limit}'.format(
                    limit=mem_limit))
        memsw_limit = getattr(self.config, 'memsw_limit', None)
        if memsw_limit:
            lines.append(
                'lxc.cgroup.memory.memsw.limit_in_bytes = {limit}'.format(
                    limit=memsw_limit))

        return '\n'.join(lines)

    def get_proc_lxc_tmpl_ctx(self):
        return {
            'proc_path': get_container_path(self.config),
            'network_config': get_lxc_network_config(get_lxc_version()),
            'memory_limits': self.get_lxc_memory_limits(),
            'volumes': self.get_lxc_volume_str(),
        }

    def write_proc_lxc(self):
        print("Writing proc.lxc")
        proc_path = get_proc_path(self.config)
        tmpl = get_template(self.lxc_template_name)
        content = tmpl % self.get_proc_lxc_tmpl_ctx()
        filepath = os.path.join(proc_path, 'proc.lxc')
        with open(filepath, 'w') as f:
            f.write(content)

    @classmethod
    def invoke(cls):
        "Instantiate and invoke the runner"
        cls().main()


def untar(tarpath, outfolder, owners=None, overwrite=True, fixperms=True):
    """
    Unpack tarpath to outfolder.  Make a guess about the compression based on
    file extension (.gz or .bz2).

    The unpacking of the tarfile is done in a temp directory and moved into
    place atomically at the end (assuming /tmp is on the same filesystem as
    outfolder).

    If 'owners' is provided, it should be a tuple in the form
    (username, groupname), and the contents of the unpacked folder will be set
    with that owner and group.

    If outfolder already exists, and overwrite=True (the default), the existing
    outfolder will be deleted before the new one is put in place. If outfolder
    already exists and overwrite=False, IOError will be raised.
    """

    # We don't use fixperms at all
    _ignored = fixperms  # noqa

    # make a folder to untar to
    with tmpdir():
        _, _, ext = tarpath.rpartition('.')

        if ext not in ('gz', 'bz2'):
            raise ValueError('tarpath must point to a .gz or .bz2 file')

        tf = tarfile.open(tarpath, 'r:' + ext)
        try:
            os.mkdir('contents')
            tf.extractall('contents')
        finally:
            tf.close()

        if owners is not None:
            contents = path.Path('contents')
            for item in contents.walk():
                if item.isdir():
                    # chown user:group
                    item.chown(*owners)
                    # chmod ug+xr
                    item.chmod('ug+xr')
                if item.isfile() and not item.islink():
                    # chown user:group
                    item.chown(*owners)
                    # chmod ug+rw
                    item.chmod('ug+rw')

        if os.path.isdir(outfolder):
            if overwrite:
                shutil.rmtree(outfolder)
            else:
                raise IOError(
                    ('Cannot untar %s because %s already exists and '
                     'overwrite=False') % (tarfile, outfolder))
        shutil.move('contents', outfolder)


def ensure_file(url, path, md5sum=None):
    """
    If file is not already at 'path', then download from 'url' and put it
    there.

    If md5sum is provided, and 'path' exists, check that file matches the
    md5sum.  If not, re-download.
    """

    if not os.path.isfile(path) or (md5sum and md5sum != file_md5(path)):
        download_file(url, path)


def download_file(url, path):
    with tmpdir():
        print("Downloading %s" % url)
        base = os.path.basename(path)
        with open(base, 'wb') as f:
            resp = requests.get(url, stream=True)
            resp.raise_for_status()
            shutil.copyfileobj(resp.raw, f)
        shutil.move(base, path)


def get_template(name):
    """
    Look for 'name' in the vr.runners.templates folder.  Return its contents.
    """
    path = pkg_resources.resource_filename('vr.runners', 'templates/' + name)
    with open(path, 'r') as f:
        return f.read()
