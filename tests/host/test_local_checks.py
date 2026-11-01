"""Suite discovery only, no process, device or network execution."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('local_checks',Path(__file__).resolve().parents[2]/'tools/check_local.py')
checks = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checks)


class LocalSuiteDiscovery(unittest.TestCase):
    def test_nested_nonpackage_suite_is_discovered_and_empty_roots_are_not(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root/'tests'/'boundary'
            nested.mkdir(parents=True)
            (nested/'test_contract.py').write_text('')
            (root/'tests'/'empty').mkdir()
            (root/'examples').mkdir()
            (root/'review_tools').mkdir()
            (root/'review_tools'/'test_record.py').write_text('')
            found = [str(path.relative_to(root)) for path in checks.python_suites(root)]
            self.assertEqual(found,['review_tools','tests/boundary'])

    def test_empty_project_is_not_reported_as_green(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(checks,'ROOT',Path(directory)), patch.object(checks.subprocess,'run') as run:
            with self.assertRaisesRegex(SystemExit,'No Python suites discovered'):
                checks.main()
            run.assert_not_called()
