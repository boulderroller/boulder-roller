"""Keep actual previous-version cutover in the release's governance matrix."""
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch


class GovernanceCoverage(unittest.TestCase):
    def test_both_deployable_variants_upgrade_actual_previous_version(self):
        script = Path(__file__).resolve().parents[1] / 'scripts/run-stage1-ci-group.py'
        with patch('sys.argv', [str(script), '--group', 'governance', '--wallet', 'local-wallet',
                               '--pool-program', 'local-pool', '--squads-program', 'local-squads']), \
                patch('subprocess.run') as run:
            runpy.run_path(str(script), run_name='__main__')
        upgrades = [call.args[0] for call in run.call_args_list if '--version-upgrade' in call.args[0]]
        self.assertEqual([command[command.index('--build') + 1] for command in upgrades], ['default', 'devnet'])
        for command in upgrades:
            self.assertEqual(command[command.index('--pool-program') + 1], 'local-pool')
            self.assertEqual(Path(command[command.index('--initial-program') + 1]).parts[-3:],
                             ('stage1-previous', 'deploy', 'boulder_rollers.so'))


if __name__ == '__main__':
    unittest.main()
