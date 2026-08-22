"""Probe: greet command check directly."""
import sys
from pathlib import Path
sys.path.insert(0, 'src')
from tests.base import AgentOSTestCase
import unittest

class P(AgentOSTestCase):
    def runTest(self):
        goal_id = self.make_goal_with_task()
        run_id, ctx = self.open_live_run(goal_id)
        src = ('def greet(name):\n    return f"hello, {name}"\n\n\n'
               'def test_greet():\n    assert greet("world") == "hello, world"\n')

        def w(path, content):
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding='utf-8')
            return {'written': str(p)}

        self.gw.register(self.write_contract(handler=w))
        self.gw.invoke(ctx, self.gw.resolve('fs.write.handler'),
                       {'path': str(Path(ctx.workspace_path) / 'greet.py'),
                        'content': src}, idempotency_key='x')
        self.eng.complete_live_run(ctx)
        ok, detail = self.ev._check_command_exit_0(goal_id, {
            'entry': 'greet.py', 'call': 'greet', 'arg': 'world',
            'expect_stdout_contains': 'hello, world'})
        print('cmd:', ok, detail)

unittest.TextTestRunner(verbosity=0).run(unittest.TestSuite([P()]))
