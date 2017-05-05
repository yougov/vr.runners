#!/usr/bin/env python

# Project skeleton maintained at https://github.com/jaraco/skeleton

import io

import setuptools

with io.open('README.rst', encoding='utf-8') as readme:
    long_description = readme.read()

name = 'vr.runners'
description = 'Command line tools to launch procs.'

params = dict(
    name=name,
    use_scm_version=True,
    author='Brent Tubbs',
    author_email='brent.tubbs@gmail.com',
    description=description or name,
    long_description=long_description,
    url="https://github.com/yougov/" + name,
    packages=setuptools.find_packages(),
    include_package_data=True,
    namespace_packages=name.split('.')[:-1],
    python_requires='>=2.7',
    install_requires=[
        'vr.common>=4.9.0',
        'requests>=1.2.0',
        'path.py',
    ],
    extras_require={
    },
    setup_requires=[
        'setuptools_scm>=1.15.0',
    ],
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3",
    ],
    entry_points={
        'console_scripts': [
            'vrun = vr.runners.image:ImageRunner.invoke',
            'vrun_precise = vr.runners.precise:PreciseRunner.invoke',
        ],
    },
)
if __name__ == '__main__':
	setuptools.setup(**params)
