"""Only used by run_extension.cjs; serve deterministic suggestions for its fixture."""
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from whitedot.browser_bridge import BrowserBridge
from whitedot.types import Issue

bridge = BrowserBridge("local-integration-fixture-no-actual-account")
bridge.start()
print("ready", flush=True)
try:
    while True:
        target = bridge.snapshot("chrome")
        if target and target.text == "😀 fix teh word":
            at = target.text.index("teh")
            bridge.publish(target, [Issue(at, at + 3, "teh", ("the",), "笔误")])
        time.sleep(0.08)
finally:
    bridge.stop()
