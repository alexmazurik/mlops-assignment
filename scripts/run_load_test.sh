#!/bin/bash -e

uv run python load_test/driver.py --rps 1 --duration 30
