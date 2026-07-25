"""Marks the test tree as a package.

Not decoration: several tests share fixtures by absolute import (``from
tests.unit.bmp_fixtures import write_bmp24``). Without these ``__init__.py`` files
``tests`` is only a namespace package, and Python resolves a *regular* package of the
same name found anywhere on sys.path ahead of it -- so an unrelated ``tests`` package
in site-packages silently shadows this one and collection fails with
``No module named 'tests.unit'``.
"""
