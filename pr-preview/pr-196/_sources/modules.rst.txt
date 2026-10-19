.. A 7-character "=" underline (the length of "Modules") is treated as a
   merge-conflict separator by ``git diff --check`` / ``check-merge-conflict``;
   keep this underline longer than the title to avoid the false positive.

Modules
=========

An overview of the modules that make up ``keycast``.
The API reference below is generated automatically from the source docstrings.

Composition root
-------------------------------

Wiring and lifecycle — the only place components meet.

.. automodule:: keycast.application

.. automodule:: keycast.main

.. automodule:: keycast.cli

Input capture
-------------------------------

pynput listeners that format each event into one display string and push it to
a ``TextSink``. They know nothing about the display.

.. automodule:: keycast.listeners

.. automodule:: keycast.secure_input

Overlay display
-------------------------------

The Tkinter overlay window (the production ``TextSink``).

.. automodule:: keycast.display

Settings and logging
-------------------------------

JSON-file settings (Pydantic) and rotating-file logging setup.

.. automodule:: keycast.settings

.. automodule:: keycast.logging_setup

Update notices
-------------------------------

Install-source-aware update check (notify only): how keycast was installed,
the GitHub release fetch, and the once-a-day throttle state.

.. automodule:: keycast.updates

.. automodule:: keycast.updates.sources

.. automodule:: keycast.updates.versions

.. automodule:: keycast.updates.state
