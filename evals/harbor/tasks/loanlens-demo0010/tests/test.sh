#!/bin/bash
# Grade /app/output.json against the answer key. Writes /logs/verifier/reward.json.
mkdir -p /logs/verifier
python3 /tests/grade.py --output /app/output.json --expected /tests/expected.json \
    --reward-dir /logs/verifier
