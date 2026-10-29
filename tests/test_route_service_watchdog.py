"""Only health classification and process admission, never actual input."""
import json
import unittest
from unittest.mock import patch, MagicMock

from scripts.pilot import route_service_watchdog as watchdog


class WatchdogTests(unittest.TestCase):
    def test_only_a_missing_listener_can_be_started(self):
        self.assertTrue(watchdog.can_start('absent',False,10))
        for state,owned,elapsed in [('healthy',False,100),('occupied',False,100),('absent',True,100),('absent',False,9)]:
            self.assertFalse(watchdog.can_start(state,owned,elapsed))

    def test_verified_health_never_needs_a_port_probe(self):
        response=MagicMock(); response.__enter__.return_value=response
        response.status=200; response.read.return_value=json.dumps(dict(service='sphere-reconstruction-v1',one_active_job=True)).encode()
        with patch.object(watchdog,'urlopen',return_value=response),patch.object(watchdog.socket,'socket') as sock:
            self.assertEqual(watchdog.probe(),'healthy')
            sock.assert_not_called()

    def test_http_error_or_other_service_on_port_is_not_killed_or_replaced(self):
        for code,expected in [(0,'occupied'),(10061,'absent')]:
            sock=MagicMock(); sock.__enter__.return_value=sock; sock.connect_ex.return_value=code
            with patch.object(watchdog,'urlopen',side_effect=OSError),patch.object(watchdog.socket,'socket',return_value=sock):
                self.assertEqual(watchdog.probe(),expected)


if __name__=='__main__': unittest.main()
