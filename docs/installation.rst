Installation
============

``keycast`` is an end-user application, not a library, so install
it as a standalone tool rather than as a project dependency. Its primary entry
point is the ``keycast`` command.

Stable release
--------------

Install ``keycast`` into an isolated environment with your
preferred tool installer:

.. code-block:: sh

   uv tool install keycast

.. code-block:: sh

   pipx install keycast

Or run it without installing:

.. code-block:: sh

   uvx keycast

Homebrew (macOS):

.. code-block:: sh

    brew install --cask hasansezertasan/tap/keycast

Homebrew (Linux):

.. code-block:: sh

    brew install hasansezertasan/tap/keycast

The cask is the double-click app; the formula (``brew install
hasansezertasan/tap/keycast``) is the terminal tool.

Scoop (Windows):

.. code-block:: sh

   scoop bucket add keycast https://github.com/hasansezertasan/scoop-bucket
   scoop install keycast
   scoop install keycast-pipx

``keycast`` is the packaged app; ``keycast-pipx`` is the terminal tool
(installed via pipx).

Verify release provenance
-------------------------

The release workflow uses two complementary attestation mechanisms:

* GitHub build attestations record SLSA provenance for distributions when they
  are built, including workflow and source information. Their Sigstore bundles
  are also attached to the GitHub Release.
* PyPI publication attestations identify the Trusted Publisher that uploaded each
  distribution. The publishing action enables these by default for Trusted
  Publishing to PyPI or TestPyPI. They are available through PyPI's per-file
  provenance APIs and UI, rather than as GitHub release bundles.

The publication claim does not replace the structured build-provenance claim.
Both refer to the distribution bytes transferred from the build job, without an
intervening rebuild. See `PyPI's attestation documentation
<https://docs.pypi.org/attestations/>`_ for the index-hosted publication claim.

After downloading a wheel or source distribution, verify its GitHub build
attestation against this repository's release workflow and ``main`` ref:

.. code-block:: sh

   gh attestation verify <downloaded-distribution> \
     --repo hasansezertasan/keycast \
     --signer-workflow hasansezertasan/keycast/.github/workflows/release.yml \
     --source-ref refs/heads/main

To use the matching provenance bundle downloaded from the GitHub Release instead
of fetching the attestation from GitHub's API, add ``--bundle``:

.. code-block:: sh

   gh attestation verify <downloaded-distribution> \
     --bundle <downloaded-provenance-bundle> \
     --repo hasansezertasan/keycast \
     --signer-workflow hasansezertasan/keycast/.github/workflows/release.yml \
     --source-ref refs/heads/main

Fully offline verification also needs trusted-root material; see
`GitHub's offline verification guide
<https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/verify-attestations-offline>`_.

GitHub build attestations are available for public repositories on current
GitHub plans. Private and internal repositories require GitHub Enterprise Cloud
and the repository variable ``ENABLE_PRIVATE_ATTESTATIONS=true``. This opt-in
applies to GitHub build attestations, not PyPI's publication attestations. PyPI's
default attestation path requires Trusted Publishing and uses public Sigstore
infrastructure; publication with an API token or an explicit attestation opt-out
does not generate those attestations automatically.

From source
-----------

The source files for ``keycast`` can be downloaded from the
`GitHub repo <https://github.com/hasansezertasan/keycast>`_.

You can either clone the public repository:

.. code-block:: sh

   git clone https://github.com/hasansezertasan/keycast.git

Or download the
`tarball <https://github.com/hasansezertasan/keycast/tarball/main>`_:

.. code-block:: sh

   mkdir keycast
   curl -fL https://github.com/hasansezertasan/keycast/tarball/main | tar -xz --strip-components=1 -C keycast

Once you have a copy of the source, you can install it with:

.. code-block:: sh

   cd keycast
   uv tool install .
