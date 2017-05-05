import shutil
import tempfile

import vr.common.paths


VR_ROOT = None


def pytest_configure():
    global VR_ROOT

    vr.common.paths.VR_ROOT = VR_ROOT = tempfile.mkdtemp()
    vr.common.paths.BUILDS_ROOT = VR_ROOT + '/builds'
    vr.common.paths.PROCS_ROOT = VR_ROOT + '/procs'
    vr.common.paths.RELEASES_ROOT = VR_ROOT + '/releases'
    vr.common.paths.IMAGES_ROOT = VR_ROOT + '/images'


def pytest_unconfigure():
    if VR_ROOT is not None:
        shutil.rmtree(VR_ROOT)
