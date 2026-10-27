# repopilot-demo-bugs

A tiny, dependency-free Python project with **four deliberate bugs**. It exists so you can try
[RepoPilot AI](https://github.com/Xdiad47/RepoPilot-AI) on a real public repository in one click.

> The test suite is **expected to fail** on `main`: each failing test reproduces one bug.
> Please don't "fix" them here; fork the repository if you want to experiment.

| Module | Symptom a user would report |
| --- | --- |
| `shop/validators.py` | Submitting an empty email crashes the signup endpoint with a 500 error |
| `shop/pagination.py` | Page 1 of the product list skips the first items and the last page is empty |
| `shop/stats.py` | The dashboard crashes for new shops with no orders; the median of an even number of values is wrong |
| `shop/cart.py` | A 10% discount takes off 100% of the price |

Run the tests locally: `pip install pytest && python -m pytest`.
