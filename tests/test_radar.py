import importlib.util
from pathlib import Path
import unittest
spec = importlib.util.spec_from_file_location('radar', Path(__file__).resolve().parents[1] / 'scripts' / 'radar.py')
radar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(radar)
class ModelTests(unittest.TestCase):
    def test_price(self):
        self.assertTrue(radar.is_free({'pricing': {'prompt': '0', 'completion': '0'}}))
        self.assertFalse(radar.is_free({'pricing': {'prompt': '0', 'completion': '0.00001'}}))
    def test_unknown_parameters_fail_closed(self):
        self.assertFalse(radar.eligible({'id':'some/550b:free','pricing':{'prompt':'0','completion':'0'},'supported_parameters':['tools']}))
    def test_verified_parameters(self):
        self.assertTrue(radar.eligible({'id':'any','total_parameters':120000000000,'pricing':{'prompt':'0','completion':'0'},'supported_parameters':['tools']}))

class ResolveTests(unittest.TestCase):
    """v0.1.1 fail-closed model resolution: never trust a hand-typed ID."""
    def setUp(self):
        self._orig = radar.free_ids
        radar.free_ids = lambda **kwargs: {'a/model:free', 'openrouter/free'}
    def tearDown(self):
        radar.free_ids = self._orig
    def test_exact_id_used_asis(self):
        self.assertEqual(radar.resolve_free_model('a/model:free'), 'a/model:free')
    def test_missing_free_suffix_autocorrects(self):
        # Dropping ':free' silently routes to the PAID variant; auto-correct loudly.
        self.assertEqual(radar.resolve_free_model('a/model'), 'a/model:free')
    def test_unknown_id_refused(self):
        with self.assertRaises(radar.NotFreeError):
            radar.resolve_free_model('x/paid-model')
    def test_blank_id_refused(self):
        with self.assertRaises(radar.NotFreeError):
            radar.resolve_free_model('   ')

import contextlib
import datetime as dt
import io
import json
import os
import tempfile
import urllib.error
from unittest.mock import patch


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = Path(self.tmp.name) / 'cache.json'
        self.cache_patch = patch.object(radar, 'CACHE', self.cache)
        self.cache_patch.start()
        self.addCleanup(self.cache_patch.stop)

    def report(self, **changes):
        report = {'checked_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                  'free_ids': ['a/model:free']}
        report.update(changes)
        return report

    def write(self, report):
        self.cache.write_text(json.dumps(report))

    def test_valid_cache_avoids_discovery(self):
        self.write(self.report())
        with patch.object(radar, 'discover') as discover:
            self.assertEqual(radar.free_ids(), {'a/model:free'})
            discover.assert_not_called()

    def test_invalid_caches_refresh(self):
        now = dt.datetime.now(dt.timezone.utc)
        cases = [None, [], 'wrong', {},
                 self.report(checked_at=(now + dt.timedelta(days=1)).isoformat()),
                 self.report(checked_at=(now - dt.timedelta(hours=25)).isoformat()),
                 self.report(checked_at=now.replace(tzinfo=None).isoformat()),
                 self.report(checked_at=123), self.report(checked_at='bad-date'),
                 self.report(free_ids='a/model:free'),
                 self.report(free_ids=[[]]), self.report(free_ids=['']),
                 self.report(free_ids=['   '])]
        for invalid in cases:
            with self.subTest(invalid=invalid):
                self.write(invalid)
                with patch.object(radar, 'discover', return_value=self.report()) as discover:
                    self.assertEqual(radar.free_ids(), {'a/model:free'})
                    discover.assert_called_once_with()

    def test_missing_malformed_unreadable_cache_refreshes(self):
        with patch.object(radar, 'discover', return_value=self.report()):
            self.assertEqual(radar.free_ids(), {'a/model:free'})
            self.cache.write_text('{bad json')
            self.assertEqual(radar.free_ids(), {'a/model:free'})
            with patch.object(Path, 'read_text', side_effect=PermissionError('denied')):
                self.assertEqual(radar.free_ids(), {'a/model:free'})

    def test_probe_rechecks_cached_prices_and_refuses_paid_model(self):
        self.write(self.report(free_ids=['a/now-paid']))
        def request(url, *args, **kwargs):
            self.assertEqual(url, radar.API + '/models')
            return {'data': [{'id': 'a/now-paid',
                              'pricing': {'prompt': '0.01', 'completion': '0'}}]}
        with patch.object(radar, 'request', side_effect=request) as req:
            self.assertFalse(radar.probe('a/now-paid', 'dummy')['ok'])
            self.assertEqual(req.call_count, 1)

    def test_catalog_failure_never_uses_cached_authorization(self):
        self.write(self.report())
        cases = [urllib.error.URLError('offline'), {'error': 'unavailable'},
                 {'data': None}, {'data': [{}]}, {'data': [{'id': [], 'pricing': {}}]}]
        for failure in cases:
            with self.subTest(failure=str(failure)):
                kwargs = {'side_effect': failure} if isinstance(failure, Exception) else {'return_value': failure}
                with patch.object(radar, 'request', **kwargs) as req:
                    self.assertFalse(radar.probe('a/model:free', 'dummy')['ok'])
                    req.assert_called_once_with(radar.API + '/models')

    def test_live_free_probe_succeeds(self):
        responses = [{'data': [{'id': 'a/model:free',
                               'pricing': {'prompt': '0', 'completion': '0'}}]},
                     {'choices': [{'message': {'content': 'PONG'}}]}]
        with patch.object(radar, 'request', side_effect=responses) as req:
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertTrue(radar.probe('a/model', 'dummy')['ok'])
            self.assertEqual(req.call_args.args[2]['model'], 'a/model:free')
            self.assertEqual(req.call_count, 2)

    def test_status_does_not_print_invalid_cache(self):
        self.write(self.report(checked_at='invalid'))
        output = io.StringIO()
        with patch('sys.argv', ['radar', 'status']), contextlib.redirect_stdout(output):
            self.assertEqual(radar.main(), 0)
        self.assertIn('message', json.loads(output.getvalue()))
        self.assertNotIn('free_ids', output.getvalue())


class ProbeExitTests(unittest.TestCase):
    def test_completion_failures_return_nonzero(self):
        failures = [{'error': 'denied'}, {'choices': []}, {'choices': 'invalid'}, [],
                    urllib.error.HTTPError(radar.API, 429, 'rate limited', {}, None),
                    urllib.error.URLError('offline'), ValueError('bad JSON')]
        for failure in failures:
            with self.subTest(failure=str(failure)):
                kwargs = {'side_effect': failure} if isinstance(failure, Exception) else {'return_value': failure}
                with patch.object(radar, 'resolve_free_model', return_value='a/model:free'), \
                     patch.object(radar, 'request', **kwargs), \
                     patch.dict(os.environ, {'OPENROUTER_API_KEY': 'dummy'}), \
                     patch('sys.argv', ['radar', 'probe', '--model', 'a/model:free']), \
                     contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(radar.main(), 1)

    def test_success_returns_zero(self):
        with patch.object(radar, 'probe', return_value={'ok': True, 'error': None}), \
             patch.dict(os.environ, {'OPENROUTER_API_KEY': 'dummy'}), \
             patch('sys.argv', ['radar', 'probe', '--model', 'a/model:free']), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(radar.main(), 0)


if __name__ == '__main__':
    unittest.main()
