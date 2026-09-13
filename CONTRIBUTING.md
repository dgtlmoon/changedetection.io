Contributing is always welcome!

I am no professional flask developer, if you know a better way that something can be done, please let me know!

Otherwise, it's always best to PR into the `master` branch.

Install the development and test dependencies with `pip install -r requirements-dev.txt`.

Then activate the git hooks once with `pre-commit install` — this wires up linting on commit and a
translation catalog check on push, matching what CI enforces. Git cannot enable hooks automatically
on clone, so this step is manual.

Please be sure that all new functionality has a matching test!

Use `pytest` to validate/test, you can run the existing tests as `pytest tests/test_notification.py` for example
