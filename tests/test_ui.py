"""Real Tk widget checks; skipped explicitly when no display is available."""
import copy
import random
import sys
from pathlib import Path
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import reference_code, reference_for, world_for
from runner import evaluate


class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import tkinter as tk
            probe = tk.Tk()
            probe.destroy()
        except Exception as exc:
            raise unittest.SkipTest('GUI 无可用显示服务：' + str(exc))
        cls.warm = evaluate(reference_code(1), world_for(1, random.Random(42)))

    def setUp(self):
        import tkinter as tk
        from RouteLab import RouteLabApp
        self.root = tk.Tk()
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(str(args))
        self.app = RouteLabApp(self.root, seed=42)
        self.root.update()

    def tearDown(self):
        self.assertEqual(self.errors, [])
        for item in self.root.tk.call('after', 'info'):
            self.root.after_cancel(item)
        self.root.destroy()

    def test_walkthrough_and_typing_assistance(self):
        app = self.app
        editor = app.editor
        original = editor.get('1.0', 'end-1c')
        app.walk_button.invoke()
        self.assertIn('1/4', app.tutorial_task.cget('text'))
        self.assertEqual(editor.get('1.0', 'end-1c'), original)
        editor.focus_force()
        self.root.update()
        for key in ('f', 'o'):
            editor.event_generate('<KeyPress-' + key + '>')
            editor.event_generate('<KeyRelease-' + key + '>')
        self.assertIn('for edge', app.code_hint.cget('text'))
        self.assertTrue(editor.get('insert linestart', 'insert').endswith('fo'))
        editor.event_generate('<KeyPress-Tab>')
        self.assertEqual(editor.get('insert linestart', 'insert'), '    for edge in ctx["graph"]:')
        editor.event_generate('<KeyPress-Return>')
        self.assertEqual(editor.get('insert linestart', 'insert'), '        ')
        self.assertIn('新手引导临时返回', editor.get('insert', 'end'))
        app.tutorial_step = None
        self.assertIsNone(app.editor_completion())

    def test_layout_and_no_clickable_level_list(self):
        self.assertGreater(self.app.canvas.winfo_width(), 400)
        self.assertGreater(self.app.editor.winfo_width(), 350)
        def widgets(w):
            yield w
            for child in w.winfo_children():
                yield from widgets(child)
        labels = [str(w.cget('text')) for w in widgets(self.root) if w.winfo_class() == 'Button']
        self.assertFalse(any('下一关' in text or '关卡' in text for text in labels))

    def test_real_child_success_animates_then_advances_and_keeps_code(self):
        app = self.app
        app.tutorial_step = 3
        app.refresh_tutorial()
        app.editor.delete('1.0', 'end')
        app.editor.insert('1.0', reference_code(0))
        code = app.editor.get('1.0', 'end-1c')
        animations = []
        next_calls = []
        original_animate = app._animate_route
        original_next = app.next_world
        def animate(route, segment, tick, success):
            animations.append((app.chapter, segment))
            original_animate(route, segment, tick, success)
        def advance():
            next_calls.append((app.packet_t, list(app.visual_path)))
            original_next()
        app._animate_route = animate
        app.next_world = advance
        app.run_clicked()
        deadline = time.monotonic() + 12
        while app.chapter == 0 and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertEqual(app.chapter, 1, app.last_result)
        self.assertEqual(app.world.mode, 'local')
        self.assertTrue(animations)
        self.assertTrue(all(chapter == 0 for chapter, _ in animations))
        self.assertEqual(len(next_calls), 1)
        self.assertIsNone(next_calls[0][0])
        self.assertEqual(next_calls[0][1][-1], 'F')
        self.assertEqual(app.editor.get('1.0', 'end-1c'), code)

    def test_failed_run_does_not_advance_or_replace_code(self):
        app = self.app
        code = app.editor.get('1.0', 'end-1c')
        app.busy = True
        app.on_result(dict(ok=False, message='测试失败', route=[], cost=0, log=[]))
        self.assertFalse(app.busy)
        self.assertEqual(app.chapter, 0)
        self.assertEqual(app.editor.get('1.0', 'end-1c'), code)
        self.assertEqual(str(app.run_btn.cget('state')), 'normal')

    def test_contract_expires_after_animation_and_player_can_repair_route(self):
        app = self.app
        app.chapter = 6
        app.tutorial_step = None
        app.next_world()
        app.speed.set(4)
        code = "def solve(ctx): return ['A','B','C','F']"
        app.editor.delete('1.0','end')
        app.editor.insert('1.0', code)

        def wait_until(predicate):
            deadline = time.monotonic() + 10
            while not predicate() and time.monotonic() < deadline:
                self.root.update()
                time.sleep(.005)
            self.assertTrue(predicate())

        app.run_clicked()
        wait_until(lambda: app.play_action is not None)
        app.toggle_playback()
        self.assertTrue(app.paused)
        self.assertEqual(app.success_count, 0)
        app.step_playback()
        self.assertEqual(app.success_count, 0)
        app.toggle_playback()
        wait_until(lambda: app.chapter == 8)
        self.assertEqual(app.editor.get('1.0','end-1c'), code)
        app.run_clicked()
        wait_until(lambda: not app.busy)
        self.assertEqual(app.visual_path, ['A','B'])
        self.assertIn('对等协议', app.feedback)
        app.toggle_diagnostics()
        app.toggle_diagnostics()
        app.editor.delete('1.0','end')
        app.editor.insert('1.0', reference_for(app.world))
        app.run_clicked()
        wait_until(lambda: app.chapter == 9)
        self.assertEqual(app.success_count, 2)

    def test_service_baseline_retry_replay_and_progress(self):
        app = self.app
        def wait(predicate):
            deadline = time.monotonic() + 12
            while not predicate() and time.monotonic() < deadline:
                self.root.update()
                time.sleep(.005)
            self.assertTrue(predicate())
        app.chapter = 16
        app.tutorial_step = None
        app.speed.set(4)
        app.event_checkpoint = {'saved': True}
        app.editor.delete('1.0', 'end')
        app.editor.insert('1.0', 'def solve(ctx): return {}')
        app.next_world()
        self.assertTrue(app.service_step.cget('text').startswith('1/3'))
        wait(lambda: not app.busy)
        self.assertEqual(app.world.protocol, 'service')
        self.assertEqual(app.success_count, 0)
        self.assertTrue(app.service_step.cget('text').startswith('2/3'))
        app.service_example.invoke()
        self.assertEqual(app.editor.get('1.0','end-1c'), 'def solve(ctx): return {}')
        baseline = list(app.frames)
        app.seek_frame('1')
        self.assertEqual(app.active_frame['time'], 1)
        app.run_clicked()
        wait(lambda: not app.busy)
        self.assertFalse(app.last_result['ok'])
        self.assertTrue(app.service_step.cget('text').startswith('3/3'))
        self.assertIn('正常登录', app.service_instruction.cget('text'))
        self.assertEqual(app.frames, baseline)
        app.reference_button.invoke()
        wait(lambda: not app.busy)
        code = "def solve(ctx): return {'repeat_limits': dict.fromkeys(ctx['sources'], 2)}"
        app.editor.delete('1.0', 'end')
        app.editor.insert('1.0', code)
        app.run_clicked()
        wait(lambda: app.chapter == 18)
        self.assertEqual(app.editor.get('1.0','end-1c'), code)
        self.assertEqual(app.world.title, 'S2')
        app.toggle_playback()
        app.timeline.set(6)
        self.root.update()
        self.assertEqual(app.frame_index, 6)
        node = app.canvas.find_withtag('inspect_B')[-1]
        x,y = map(int, app.canvas.coords(node))
        app.canvas.event_generate('<Motion>', x=x, y=y)
        app.canvas.event_generate('<Button-1>', x=x, y=y)
        self.root.update()
        self.assertEqual(app.service_focus, 'B')
        self.assertIn('活跃会话', app.details['网络状态'].get('1.0','end'))
        app.toggle_diagnostics()
        self.root.update()
        self.assertTrue(app.timeline.winfo_ismapped())
        app.toggle_diagnostics()
        node = app.canvas.find_withtag('inspect_F')[-1]
        x,y = map(int, app.canvas.coords(node))
        app.canvas.event_generate('<Motion>', x=x, y=y)
        app.canvas.event_generate('<Button-1>', x=x, y=y)
        self.root.update()
        self.assertIsNone(app.service_focus)
        app.step_playback()
        self.assertEqual(app.frame_index, 7)
        app.toggle_playback()
        wait(lambda: not app.busy)
        app.service_example.invoke()
        self.assertEqual(app.editor.get('1.0','end-1c'), code)
        app.run_clicked()
        wait(lambda: not app.busy)
        self.assertFalse(app.last_result['ok'])
        self.assertIn('误封', app.service_instruction.cget('text'))
        app.editor.delete('1.0','end')
        app.editor.insert('1.0', "def solve(ctx): return {'repeat_limits': {s:1 for s,v in ctx['sources'].items() if v['repeats']>8 and v['sessions']<=4}}")
        app.run_clicked()
        wait(lambda: app.chapter == 19)
        self.assertEqual(app.world.protocol, 'dv')
        self.assertFalse(app.service_guide.winfo_manager())
        self.assertEqual(app.event_checkpoint, {'saved':True})

    def test_success_checkpoint_becomes_next_incident_start(self):
        app = self.app
        app.chapter = 1
        app.last_result = copy.deepcopy(self.warm)
        code = app.editor.get('1.0', 'end-1c')
        app.next_world()
        self.assertEqual(app.chapter, 2)
        self.assertEqual(app.event_checkpoint, self.warm['checkpoint'])
        self.assertEqual(app.editor.get('1.0', 'end-1c'), code)
        self.assertIn(str(app.world.seed), app.seed_var.get())

    def test_observer_table_timeline_and_popups_are_read_only(self):
        app = self.app
        app.chapter = 1
        app.world = world_for(1, random.Random(42))
        app.last_result = copy.deepcopy(self.warm)
        app.frames = app.last_result['frames']
        app.timeline.configure(to=len(app.frames)-1)
        before = copy.deepcopy(app.last_result)
        app.inspect_node.set('C')
        app.select_router('C')
        app.display_frame(len(app.frames)-1)
        rows = [app.route_table.item(i)['values'] for i in app.route_table.get_children()]
        self.assertIn(['F', 1, 'F'], rows)
        self.assertEqual(rows[0][0], 'F')  # Target stays visible without scrolling.
        app.seek_frame('0')
        self.assertEqual(len(app.route_table.get_children()), 1)
        app.inspect_messages()
        app.inspect_ctx()
        self.root.update()
        self.assertEqual(app.last_result, before)

    def test_reset_replays_seed_and_preserves_editor(self):
        app = self.app
        original_seed = app.world.seed
        app.editor.insert('end', '\n# 玩家笔记')
        code = app.editor.get('1.0', 'end-1c')
        with patch('RouteLab.messagebox.askyesno', return_value=True):
            app.reset()
        self.assertEqual(app.editor.get('1.0', 'end-1c'), code)
        self.assertEqual(app.world.seed, original_seed)


if __name__ == '__main__':
    unittest.main()
