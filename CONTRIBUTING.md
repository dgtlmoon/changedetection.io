# Contributing
Contributing is always welcome!

I am no professional flask developer, if you know a better way that something can be
done, please let me know!

Otherwise, it's always best to PR into the `dev` branch.

# Pre-commit hooks & code style
Before contributing, make sure to install the development requirements:
```
pip3 install -r requirements-dev.txt
```
and then install the pre-commit hook using:
```
pre-commit install
```

Once set up, `pre-commit` will run [black](https://github.com/psf/black) and
[isort](https://github.com/PyCQA/isort), as well as some formatting fixes for YAML and
generic text files. Black is set up to use a line-length of 100.

# Tests
Please be sure that all new functionality has a matching test!

Use `pytest` to validate/test. you can run the existing tests as `pytest
changedetectionio/tests/test_notifications.py`, or all tests in one go using:
```
bash changedetectionio/run_all_tests_sh.sh
```

Please run all tests and make sure they pass locally before submitting a pull request.
