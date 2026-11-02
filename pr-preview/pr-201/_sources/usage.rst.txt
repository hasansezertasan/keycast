Usage
=====

Run the overlay
---------------

Launch keycast with no arguments to start the transparent overlay. It shows
keystrokes and mouse clicks in real time:

.. code-block:: sh

   keycast

Stop it with ``Ctrl+C`` in the terminal.

On the first launch keycast writes a default config to ``~/.keycast/config.json``
(see :doc:`configuration`) and shows a one-line startup status on the overlay so
you can immediately tell whether input capture is live
(``OK`` / ``Off`` / ``Permission needed`` / ``Not capturing`` / ``Unknown``).

As a command-line tool
----------------------

Two subcommands expose the terminal surface:

.. code-block:: sh

   keycast version
   keycast info

``version`` prints the running version. ``info`` prints the application version,
the Python version, the platform, and how keycast was installed (which decides
the update advice — see the README's Updates section).

Or invoke the entry point from Python (it never returns on the GUI path —
it launches the overlay):

.. code-block:: python

   from keycast.main import main

   main()

Configuration preview
---------------------

The overlay's size, colors, fonts, fade timing, key/mouse filtering, and
logging all live in ``~/.keycast/config.json``. Named presets (``presenter``,
``minimal``, ``debug``) retune the overlay for common scenarios without
editing every field. See :doc:`configuration` for the full reference, which is
generated from the live settings model so it cannot drift from the code.
