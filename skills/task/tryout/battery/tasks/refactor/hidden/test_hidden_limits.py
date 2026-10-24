import inspect
import unittest

import app.helpers
import app.limits
import app.util


class TestHiddenLimits(unittest.TestCase):
    def test_new_module_holds_both_names(self):
        self.assertEqual(app.limits.MAX_FLOW, 100)
        self.assertEqual(app.limits.clamp_flow(250), 100)
        self.assertEqual(app.limits.clamp_flow(-5), 0)

    def test_helpers_reexports_the_same_objects(self):
        self.assertIs(app.helpers.clamp_flow, app.limits.clamp_flow)
        self.assertEqual(app.helpers.MAX_FLOW, app.limits.MAX_FLOW)

    def test_clamp_is_defined_in_limits(self):
        self.assertEqual(app.limits.clamp_flow.__module__, "app.limits")

    def test_util_imports_from_limits(self):
        src = inspect.getsource(app.util)
        self.assertTrue("from .limits import" in src or "from app.limits import" in src)
