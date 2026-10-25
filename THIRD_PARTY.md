# Third-party materials

Runtime uses only Python's standard library. There is no vendored third-party
code, artwork, font or license corpus. The examples and test data were authored
for this project; the example notice is labeled demonstration text.

Python is distributed under the PSF license. Build/test tools are separate
development dependencies: setuptools (MIT), build (MIT), pytest (MIT),
pytest-cov (MIT), coverage.py (Apache-2.0), Ruff (MIT). CI uses official
actions/checkout and actions/setup-python under MIT. They are not bundled into
the wheel. MIT licensing of this project does not change the license of any
user-provided material processed by the tool.
