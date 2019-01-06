4.0.0
=====

* Switch to pkgutil-style namespace package.

3.3.0
=====

* Pin against dependencies for namespace compatibility.

3.2.0
=====

* Add support for decompressing tarfiles with lzma compression
  (.xz extension).

3.1.4
=====

* #224: Correct TypeError on Python 3 when hashing container
  name for uptests.

3.0
===

* Removed vrun_precise command and vr.runners.precise module.

2.12.1
======

* Don't attempt to save a file that returns a 404 (or other error).

2.12
====

* #188: Support later kernels by having overlayfs configuration
  depending on LXC version

* Environment variables written as ``$VARNAME`` are substituted
  with the value present on the host.

2.11.1
======

* #215: Don't attempt to teardown a directory that doesn't
  exist.

2.11.0
======

Moved project to Github.

Incorporated `project
skeleton from jaraco <https://github.com/jaraco/skeleton>`_.

Enabled automatic releases of tagged commits.
