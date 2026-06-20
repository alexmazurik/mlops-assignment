#!/bin/bash -e

uv run python load_test/driver.py --rps 10 --duration 30
