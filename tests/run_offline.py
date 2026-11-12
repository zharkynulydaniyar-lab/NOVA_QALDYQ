"""Run all suites with HTTP in memory, for sandboxes that prohibit loopback sockets."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import http_memory
import test_server
import helpers
import server
import importlib.util

test_server.create_server = http_memory.create_memory_server
test_server.Client = http_memory.MemoryClient
helpers.create_server = http_memory.create_memory_server
helpers.Client = http_memory.MemoryClient
server.create_server = http_memory.create_memory_server
if '--skip-optional-ml' in sys.argv and importlib.util.find_spec('sklearn') is None:
    import test_forecast
    for cls,name in [(test_forecast.ForecastCore,'test_03_ml_is_not_assumed_to_be_better'),
                     (test_forecast.ForecastApi,'test_01_training_command_compares_methods_on_later_dates')]:
        setattr(cls,name,unittest.skip('Optional scikit-learn is unavailable; --skip-optional-ml was explicitly requested')(getattr(cls,name)))
suite = unittest.defaultTestLoader.discover(str(Path(__file__).resolve().parent))
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(not result.wasSuccessful())
