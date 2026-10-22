"""Shared pytest configuration (owner: R11). Only registers markers; fixtures live in each test module."""


def pytest_configure(config):
    config.addinivalue_line("markers", "engine: needs the RAI engine (live PyRel queries through pe_deal_graph.queries)")
    config.addinivalue_line("markers", "warehouse: needs Snowflake warehouse access only (naive SQL baselines)")
