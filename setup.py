#!/usr/bin/python
import setuptools

params = dict(
    name='vr.runners',
    namespace_packages=['vr'],
    version='2.10.0',
    author='Brent Tubbs',
    author_email='brent.tubbs@gmail.com',
    packages=setuptools.find_packages(),
    include_package_data=True,
    url='https://bitbucket.org/yougov/vr.runners',
    install_requires=[
        'vr.common>=4.4.0',
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
    setup_requires=['pytest-runner'],
    tests_require=['pytest'],
)

if __name__ == '__main__':
    setuptools.setup(**params)
