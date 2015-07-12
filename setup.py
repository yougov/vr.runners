#!/usr/bin/python
from setuptools import setup, find_packages

setup(
    name='vr.runners',
    namespace_packages=['vr'],
    version='2.5',
    author='Brent Tubbs',
    author_email='brent.tubbs@gmail.com',
    packages=find_packages(),
    include_package_data=True,
    url='https://bitbucket.org/yougov/vr.runners',
    install_requires=[
        'vr.common>=3.16.2,<5dev',
        'requests>=1.2.0',
    ],
    entry_points={
        'console_scripts': [
            'vrun = vr.runners.image:main',
            'vrun_precise = vr.runners.precise:main',
        ]
    },
    description='Command line tools to launch procs.',
)
