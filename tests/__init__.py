import os

# Use a cheap password-hash work factor so the test-suite stays fast (production default is 600,000).
os.environ.setdefault("PASSWORD_HASH_ITERATIONS", "1000")
