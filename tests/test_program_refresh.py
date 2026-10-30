"""A program refresh must not bless incompatible shader/resource inputs."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/maintenance/refresh_programs.py'
spec = importlib.util.spec_from_file_location('refresh_programs', SCRIPT)
refresh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refresh)


class ProgramRefreshGuardTests(unittest.TestCase):
    def check_change(self, name):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / name
            target.parent.mkdir(parents=True)
            target.write_text('changed asset')
            with patch.object(refresh.compatibility, 'generation_paths', return_value={name}), \
                    patch.object(refresh.compatibility, 'git', side_effect=[name + '\n', 'original asset']):
                refresh.verify_reusable(root, 'a' * 40)

    def test_program_generator_is_regenerated(self):
        self.check_change('dm/tools/patch_nso.py')

    def test_shader_changes_require_full_preparation(self):
        with self.assertRaisesRegex(ValueError, 'asset dependency changed'):
            self.check_change('dm/gfx/nvn/shader.cpp')

    def test_product_changes_require_full_preparation(self):
        with self.assertRaisesRegex(ValueError, 'asset dependency changed'):
            self.check_change('dm/PRODUCT')

    def test_unknown_change_to_reviewed_generator_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'asset dependency changed'):
            self.check_change('dm/gfx/tools/msl_retarget.sh')
