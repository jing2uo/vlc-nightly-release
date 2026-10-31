"""No-network tests of bounded download retries and shell failure propagation."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class DownloadRetryTests(unittest.TestCase):
    def run_retry(self, failures):
        helper = Path(__file__).resolve().parents[1] / 'scripts/download-retry.sh'
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'calls'
            # Functions replace the download and wait; no SDK, network or delay.
            script = r'''
set -euo pipefail
source "$1"
count=0
flatpak() {
  count=$((count + 1))
  printf 'call' >> "$CALL_LOG"
  printf ' <%s>' "$@" >> "$CALL_LOG"
  printf '\n' >> "$CALL_LOG"
  if (( count <= FAILURES )); then return 28; fi
}
sleep() { printf 'sleep %s\n' "$1" >> "$CALL_LOG"; }
retry_download flatpak update --user --noninteractive --assumeyes --no-related --commit=exact-pinned-commit org.kde.Sdk/aarch64/6.11
echo completed
'''
            result = subprocess.run(['bash', '-c', script, 'test', str(helper)],
                                    env={**os.environ, 'CALL_LOG': str(log), 'FAILURES': str(failures)},
                                    capture_output=True, text=True)
            return result, log.read_text().splitlines()

    def test_first_attempt_success(self):
        result, lines = self.run_retry(0)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(lines), 1)
        self.assertEqual(result.stderr, '')

    def test_second_attempt_success(self):
        result, lines = self.run_retry(1)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(lines[1], 'sleep 5')
        self.assertEqual(lines[0], lines[2])

    def test_third_attempt_success_preserves_arguments(self):
        result, lines = self.run_retry(2)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(lines[1::2], ['sleep 5', 'sleep 10'])
        self.assertEqual(len(set(lines[::2])), 1)
        self.assertIn('<--commit=exact-pinned-commit> <org.kde.Sdk/aarch64/6.11>', lines[0])

    def test_exhaustion_propagates_exit_status(self):
        result, lines = self.run_retry(10)
        self.assertEqual(result.returncode, 28)
        self.assertEqual(len(lines), 5)
        self.assertNotIn('completed', result.stdout)
        self.assertIn('failed after 3 attempts', result.stderr)


if __name__ == '__main__':
    unittest.main()
