from __future__ import print_function

import argparse
import grp
import os
import pkg_resources
import pwd
import shutil
import stat
import tarfile
import textwrap

import requests
import yaml

from vr.common.paths import (get_container_name, get_buildfile_path,
                             BUILDS_ROOT, get_app_path, get_container_path,
                             get_proc_path)
from vr.common.models import ProcData
from vr.common.utils import (tmpdir, randchars, mkdir, lock_file, which,
                             file_md5, get_lxc_version, get_lxc_network_config)


class BaseRunner(object):
    def main(self):
        self.commands = {
            'setup': self.setup,
            'run': self.run,
            'shell': self.shell,
            'uptest': self.uptest,
            'teardown': self.teardown,
        }

        parser = argparse.ArgumentParser()
        cmd_help = "One of: %s" % ', '.join(self.commands.keys())
        parser.add_argument('command', help=cmd_help)
        parser.add_argument('file', help="Path to proc.yaml file.")

        args = parser.parse_args()

        try:
            cmd = self.commands[args.command]
        except KeyError:
            raise SystemExit("Command must be one of: %s" %
                             ', '.join(self.commands.keys()))

        with open(args.file, 'r+b') as file:
            self.config = ProcData(yaml.safe_load(file))

            # Lock the file for exclusive access. Some commands (such as shell
            # or uptest) may override the behavior by providing a 'lock'
            # attribute on the method.
            getattr(cmd, 'lock', lock_file)(file)
            cmd()

    def __close_file(file):
        file.close()

    def setup(self):
        print("Setting up", get_container_name(self.config))
        self.make_proc_dirs()
        self.ensure_build()
        self.write_proc_lxc()
        self.write_settings_yaml()
        self.write_proc_sh()
        self.write_env_sh()

    def run(self):
        print("Running", get_container_name(self.config))
        args = self.get_lxc_args()
        os.execve(which('lxc-start')[0], args, {})

    def shell(self):
        print("Running shell for", get_container_name(self.config))
        args = self.get_lxc_args(special_cmd='/bin/bash')
        os.execve(which('lxc-start')[0], args, {})
    shell.lock = __close_file

    def untar(self):
        tarpath = get_buildfile_path(self.config)
        print("Untarring", tarpath)
        outfolder = get_app_path(self.config)
        owners = (self.config.user, self.config.group)
        untar(tarpath, outfolder, owners)

    def write_proc_sh(self):
        """
        Write the script that is the first thing called inside the container.  It
        sets env vars and then calls the real program.
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
        os.chmod(sh_path, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def write_env_sh(self):
        print("Writing env.sh")
        envsh_path = os.path.join(get_container_path(self.config), 'env.sh')

        with open(envsh_path, 'w') as f:
            def format_var(key, val):
                return 'export %s="%s"' % (key, val)
            e = self.config.env
            env_str = '\n'.join(format_var(k, e[k]) for k in e) + '\n'
            f.write(env_str)

    def get_cmd(self):
        """
        If self.config.cmd is not None, return that.

        Otherwise, read the Procfile inside the build code, parse it (as yaml), and
        pull out the command for self.config.proc_name.
        """
        if self.config.cmd is not None:
            return self.config.cmd

        procfile_path = os.path.join(get_app_path(self.config), 'Procfile')
        with open(procfile_path, 'r') as f:
            procs = yaml.safe_load(f)
        return procs[self.config.proc_name]

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
            f.write(yaml.safe_dump(self.config.settings, default_flow_style=False))

    def get_lxc_args(self, special_cmd=None):

        name = get_container_name(self.config)
        if special_cmd:
            cmd = special_cmd
            # Container names must be unique, so to allow running a shell or
            # uptests next to the app container we have to add more stuff to the
            # name.
            name += '-tmp' + randchars()
        else:
            cmd = 'run'

        return [
            'lxc-start',
            '--name', name,
            '--rcfile', os.path.join(get_proc_path(self.config), 'proc.lxc'),
            '--',
            'su',
            '--preserve-environment',
            '--shell', '/bin/bash',
            '-c', 'cd /app;source /env.sh; exec /proc.sh "%s"' % cmd,
            self.config.user
        ]

    def get_lxc_volume_str(self):
        content = ''
        # append lines to bind-mount volumes.
        volumes = getattr(self.config, 'volumes', []) or []
        volume_tmpl = "\nlxc.mount.entry = %s %s%s none bind 0 0"
        for outside, inside in volumes:
            content += volume_tmpl % (outside, get_container_path(self.config), inside)
        return content

    def uptest(self):
        # copy the uptester into the container. ensure it's executable.
        src = pkg_resources.resource_filename('vr.runners', 'uptester/uptester')
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
                args = self.get_lxc_args(special_cmd=cmd)
                os.execve(which('lxc-start')[0], args, {})
            else:
                # There are no uptests for this proc.  Output an empty JSON list.
                print("[]")
    uptest.lock = __close_file

    def teardown(self):
        # Everything should have been put in the proc path, so delete that.
        # We don't delete the build.  That will have to be cleaned up by someone
        # else.
        shutil.rmtree(get_proc_path(self.config))

    def make_proc_dirs(self):
        print("Making directories")
        proc_path = get_proc_path(self.config)
        container_path = get_container_path(self.config)
        mkdir(proc_path)
        mkdir(container_path)

        volumes = getattr(self.config, 'volumes', None) or []
        for outside, inside in volumes:
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
        container_path = get_container_path(self.config)

        tmpl = get_template(self.lxc_template_name)

        content = tmpl % self.get_proc_lxc_tmpl_ctx()

        filepath = os.path.join(proc_path, 'proc.lxc')
        with open(filepath, 'w') as f:
            f.write(content)


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
    # make a folder to untar to
    with tmpdir():
        _, _, ext = tarpath.rpartition('.')

        if ext not in ('gz', 'bz2'):
            raise ValueError('tarpath must point to a .gz or .bz2 file')

        tf = tarfile.open(tarpath, 'r:'+ext)
        try:
            os.mkdir('contents')
            tf.extractall('contents')
        finally:
            tf.close()

        if owners is not None:
            username, groupname = owners
            user = pwd.getpwnam(username)
            group = grp.getgrnam(groupname)
            for root, dirs, files in os.walk('contents'):
                for d in dirs:
                    path = os.path.join(root, d)
                    # chown user:group
                    os.chown(path, user.pw_uid, group.gr_gid)
                    # chmod ug+xr
                    st = os.stat(path)
                    os.chmod(path, st.st_mode | stat.S_IXUSR
                                              | stat.S_IXGRP
                                              | stat.S_IRUSR
                                              | stat.S_IRGRP)
                for f in files:
                    path = os.path.join(root, f)
                    if not os.path.islink(path):
                        # chown nobody:admin
                        os.chown(path, user.pw_uid, group.gr_gid)
                        # chmod ug+rw
                        st = os.stat(path)
                        os.chmod(path, st.st_mode | stat.S_IWUSR
                                                  | stat.S_IWGRP
                                                  | stat.S_IRUSR
                                                  | stat.S_IRGRP)

        if os.path.isdir(outfolder):
            if overwrite:
                shutil.rmtree(outfolder)
            else:
                raise IOError(('Cannot untar %s because %s already exists and '
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
            shutil.copyfileobj(resp.raw, f)
        shutil.move(base, path)


def get_template(name):
    """
    Look for 'name' in the vr.runners.templates folder.  Return its contents.
    """
    path = pkg_resources.resource_filename('vr.runners', 'templates/' + name)
    with open(path, 'r') as f:
        return f.read()
