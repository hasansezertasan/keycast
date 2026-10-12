Configuration
=============

keycast is configured through a JSON file validated by a Pydantic settings
model — not environment variables. On the first launch the app writes defaults
to ``~/.keycast/config.json`` (all platforms); edit that file to configure it.
A corrupt file is moved aside to ``config.json.<epoch>.bak`` and defaults are
used, so a bad edit never bricks the app.

The reference below is generated on every docs build directly from the live
:class:`~keycast.settings.Settings` model (via
`autodoc-pydantic <https://autodoc-pydantic.readthedocs.io/>`_), so the
documented fields, types, defaults, and constraints stay in lockstep with the
code and each field's ``description=``.

.. The ``settings`` module is also autodoc'd on the Modules page, which owns
   the canonical index anchor for ``Settings``; ``:noindex:`` here renders the
   rich field reference without registering a duplicate object description.
.. autopydantic_settings:: keycast.settings.Settings
   :noindex:

Top-level flags
---------------

``debug``, ``start_minimized``, ``auto_start``, ``check_for_updates``,
``show_startup_status``, and ``preset`` live at the top level of the file (not
in a section). ``preset`` names a settings bundle — ``"custom"`` (default)
uses the file verbatim, while ``"presenter"``, ``"minimal"``, and ``"debug"``
override a handful of display/mouse/keyboard fields for common scenarios. A
preset only changes the fields it names; the on-disk config is never rewritten
with the preset's values.
