def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "local_env: needs files or a runtime that exist only on the developer machine "
        "(local artifacts, .venv-research, running Ollama); excluded in CI via -m 'not local_env'",
    )
