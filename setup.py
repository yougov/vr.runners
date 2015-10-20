#!/usr/bin/python
from setuptools import setup, find_packages

setup(
    name='vr.runners',
    namespace_packages=['vr'],
    version='2.7',
    author='Brent Tubbs',
    author_email='brent.tubbs@gmail.com',
    packages=find_packages(),
    include_package_data=True,
    url='https://bitbucket.org/yougov/vr.runners',
    install_requires=[
        'vr.common>=3.16.2,<5dev',
        'requests>=1.2.0',
        'path.py',
    ],
    entry_points={
        'console_scripts': [
            'vrun = vr.runners.image:ImageRunner.invoke',
            'vrun_precise = vr.runners.precise:PreciseRunner.invoke',
        ],
    },
    description='Command line tools to launch procs.',
)
