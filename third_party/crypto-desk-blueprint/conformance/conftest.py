"""Conformance suites run against one implementation module, chosen with --impl (default: the toy).

An implementation module exposes the factories the suites call; conformance/toy is the complete example
and scripts/new_stage.py scaffolds a new one that reuses the toy for every stage you have not replaced.
"""
import importlib
import os

import pytest


def pytest_addoption(parser):
    parser.addoption("--impl", default=os.environ.get("PIPELINE_IMPL", "conformance.toy"),
                     help="dotted module path of the implementation under test")


@pytest.fixture(scope="session")
def impl(request):
    return importlib.import_module(request.config.getoption("--impl"))
