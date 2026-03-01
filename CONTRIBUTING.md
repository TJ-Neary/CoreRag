# Contributing to CoreRag

Thanks for your interest in contributing to CoreRag!

## Getting Started

1. Fork the repository
2. Clone your fork and set up the development environment:

```bash
git clone https://github.com/your-username/CoreRag.git
cd CoreRag
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
python -m spacy download en_core_web_lg
```

3. Copy `.env.example` to `.env` and configure paths
4. Install pre-commit hooks: `pre-commit install`

## Development Workflow

1. Create a branch from `main` for your changes
2. Make your changes following the conventions below
3. Run the test suite: `pytest`
4. Run linting: `ruff check src/ tests/ && black --check src/ tests/`
5. Run the security scanner: `./scripts/security_scan.sh --staged`
6. Submit a pull request

## Code Conventions

- Python 3.12+, type hints on all function signatures
- `black` at 100 character line length, `ruff` for linting
- Imports: stdlib, then third-party, then local (`from src.models import ...`)
- Dataclasses or Pydantic for data structures
- Commit format: `<type>: <description>` (feat/fix/docs/refactor/test/chore/perf)

## Testing

```bash
pytest                          # Full suite with coverage
pytest -m "not slow"            # Skip slow tests
pytest -m "not integration"     # Skip integration tests
pytest -k "test_name"           # Single test
```

All new code should include tests. Pytest is configured with coverage reporting by default.

## Security

- No real personal data in committed files — use synthetic test data
- No hardcoded paths, API keys, or credentials
- Run `./scripts/security_scan.sh` before committing
- See [SECURITY.md](SECURITY.md) for the full security policy

## Reporting Issues

Open an issue on GitHub with:
- Steps to reproduce
- Expected vs actual behavior
- Python version and OS

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
