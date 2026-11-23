"""RouteLab — immersive routing algorithm game in Python/Tkinter.

Launch: python RouteLab.py   (Windows: double-click 启动RouteLab.bat)
Requires Python 3.10+ with Tkinter. No pip install, web service or Unity.
"""
from __future__ import annotations

import json
import argparse
import queue
import random
import re
import subprocess
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path
import tkinter as tk
from tkinter import messagebox
from tkinter import ttk

from engine import (
    BASE_EDGES, DESTINATION, POSITIONS, SOURCE,
    ctx_for, edge_key, reference_for, session_world, world_for,
)
from runner import run_isolated
from carriers import OPERATORS, OWNER, denial, market
from service_incident import INCIDENTS, SOURCES, simulate

HERE = Path(__file__).resolve().parent
BG = '#0A1120'
PANEL = '#111D30'
PANEL2 = '#17263A'
BORDER = '#365471'
FG = '#EAF3FF'
MUTED = '#BCCFE4'
BLUE = '#62E0FF'
GREEN = '#6AE8AF'
RED = '#FF7F8C'
AMBER = '#F0C474'
PURPLE = '#B69DFF'
MONO = ('Consolas', 14)
FONT = ('Microsoft YaHei UI', 10)


class RouteLabApp:
    def __init__(self, root, seed=20261028, backend='trusted'):
        self.root = root
        self.backend = backend
        self.root.title('RouteLab v0.4 · 动态网络与跨网运营')
        self.root.geometry('1440x920')
        self.root.minsize(1100, 760)
        self.root.configure(bg=BG)
        self.session_seed = seed
        self.rng = random.Random(seed)
        self.event_checkpoint = None
        self.frames = []
        self.active_frame = None
        self.frame_index = 0
        self._setting_timeline = False
        self.tutorial_step = 0
        self.tutorial_passed = False
        self.chapter = 0
        self.world = world_for(self.chapter, self.rng)
        self.cycle = 0
        self.success_count = 0
        self.busy = False
        self.visual_current = SOURCE
        self.visual_path = []
        self.packet_t = None
        self.last_result = None
        self.last_run_time = 0.0
        self.draw_debounce = None
        self.results_queue = queue.Queue()
        self.play_timer = None
        self.play_action = None
        self.history = []
        self.amendments = None
        self.feedback = '等待首次运行。'
        self.paused = False
        self.speed = tk.IntVar(value=1)
        self.build_ui()
        from tutorial import initial_code
        self.editor.insert('1.0', initial_code())
        self.refresh_tutorial()
        self.highlight_code()
        self.push_event(self.world.headline, self.world.brief)
        self.root.bind('<Control-Return>', self.run_clicked)
        self.root.after(120, self.draw_network)
        self.root.after(80, self.poll_results)

    def make_label(self, parent, text='', size=10, weight='normal', color=FG, **kwargs):
        return tk.Label(parent, text=text, bg=kwargs.pop('bg', BG), fg=color,
                        font=('Microsoft YaHei UI', size, weight), **kwargs)

    def make_button(self, parent, text, handler, primary=False):
        bg = '#267ED0' if primary else PANEL2
        active = '#389CEB' if primary else BORDER
        btn = tk.Button(parent, text=text, command=handler, font=('Microsoft YaHei UI', 10, 'bold'),
                        bg=bg, fg=FG, relief='flat', borderwidth=0, padx=15, pady=10,
                        activebackground=active, activeforeground='white', cursor='hand2')
        return btn

    def build_ui(self):
        header = tk.Frame(self.root, bg=BG, height=78)
        header.pack(fill='x', padx=24, pady=(15, 6))
        header.pack_propagate(False)
        tk.Label(header, text='◈', fg=BLUE, bg=BG, font=('Segoe UI Symbol', 24)).pack(side='left', padx=(0, 10))
        titles = tk.Frame(header, bg=BG)
        titles.pack(side='left', anchor='center')
        self.make_label(titles, 'ROUTELAB  /  动态网络实验室', 17, 'bold').pack(anchor='w')
        self.make_label(titles, '你写算法。世界改变规则。', 10, color=MUTED).pack(anchor='w')
        self.status_var = tk.StringVar(value='● NETWORK ONLINE')
        self.make_label(header, textvariable=self.status_var, size=10, weight='bold', color=GREEN).pack(side='right', padx=10)

        main = tk.PanedWindow(self.root, orient='horizontal', bg=BG, sashwidth=8,
                              sashrelief='flat', borderwidth=0, showhandle=False)
        main.pack(fill='both', expand=True, padx=18, pady=(0, 18))
        self.left = tk.Frame(main, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        self.right = tk.Frame(main, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        main.add(self.left, minsize=460, stretch='always', width=810)
        main.add(self.right, minsize=395, stretch='always', width=510)

        # Narrative and network.
        event_area = tk.Frame(self.left, bg=PANEL)
        event_area.pack(fill='x', padx=18, pady=(17, 0))
        self.make_label(event_area, '网络事件  /  LIVE EVENT', 9, 'bold', color=AMBER, bg=PANEL).pack(anchor='w')
        self.event_title = self.make_label(event_area, self.world.headline, 16, 'bold', color=FG, bg=PANEL, wraplength=650, justify='left')
        self.event_title.pack(anchor='w', pady=(7, 5))
        self.event_desc = self.make_label(event_area, self.world.brief, 11, color=MUTED, bg=PANEL, wraplength=680, justify='left')
        self.event_desc.pack(anchor='w')

        canvas_frame = tk.Frame(self.left, bg='#0D192A', highlightbackground=BORDER, highlightthickness=1)
        canvas_frame.pack(fill='both', expand=True, padx=18, pady=(3, 12))
        canvas_top = tk.Frame(canvas_frame, bg='#0D192A')
        canvas_top.pack(fill='x', padx=14, pady=(12, 2))
        self.make_label(canvas_top, 'NETWORK MAP  /  网络拓扑', 10, 'bold', bg='#0D192A').pack(side='left')
        self.vision_var = tk.StringVar(value='全局视野')
        self.make_label(canvas_top, textvariable=self.vision_var, size=9, color=BLUE, bg='#0D192A').pack(side='right')
        self.canvas = tk.Canvas(canvas_frame, bg='#0D192A', highlightthickness=0, relief='flat')
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Configure>', self.on_canvas_resize)
        self.service_focus = None
        for node in (*SOURCES, 'F'):
            self.canvas.tag_bind('inspect_'+node, '<Button-1>', lambda event, n=node: self.inspect_gate(n))
        controls = tk.Frame(canvas_frame, bg=PANEL2)
        controls.pack(fill='x')
        self.pause_button = tk.Button(controls, text='暂停', command=self.toggle_playback)
        self.pause_button.pack(side='left')
        tk.Button(controls, text='单步', command=self.step_playback).pack(side='left')
        tk.OptionMenu(controls, self.speed, 1, 2, 4).pack(side='left')
        self.make_label(controls, '倍速', 9, bg=PANEL2).pack(side='left')

        # Observer controls expose tables/messages, never an answer in solve(ctx).
        self.diagnostics = ttk.Notebook(self.left)
        self.diagnostics.pack(fill='x', padx=18, pady=(0, 8))
        debug = tk.Frame(self.diagnostics, bg=PANEL2)
        self.diagnostics.add(debug, text='路由表')
        self.details = {}
        for title in ('事件日志', '网络状态', '运营商关系', '任务说明', '算法反馈'):
            view = tk.Text(self.diagnostics, height=5, width=1, wrap='word', bg=PANEL2,
                           fg=FG, font=FONT, state='disabled')
            self.details[title] = view
            self.diagnostics.add(view, text=title)
        self.panel_button = tk.Button(controls, text='折叠诊断', command=self.toggle_diagnostics)
        self.panel_button.pack(side='right')
        debugbar = tk.Frame(debug, bg=PANEL2)
        debugbar.pack(fill='x', padx=10, pady=(5, 0))
        self.make_label(debugbar, '诊断观察器 · 路由表', 9, 'bold', bg=PANEL2).pack(side='left')
        self.inspect_node = tk.StringVar(value=SOURCE)
        node_menu = tk.OptionMenu(debugbar, self.inspect_node, *sorted(POSITIONS), command=self.select_router)
        node_menu.config(bg=PANEL2, fg=BLUE, highlightthickness=0, relief='flat', font=FONT)
        node_menu.pack(side='left', padx=8)
        tk.Button(debugbar, text='消息明细', command=self.inspect_messages,
                  bg=BORDER, fg=FG, relief='flat', font=('Microsoft YaHei UI', 9)).pack(side='left')
        self.debug_var = tk.StringVar(value='t=0 · 尚未交换消息')
        self.make_label(debugbar, textvariable=self.debug_var, size=9, color=MUTED, bg=PANEL2).pack(side='right')
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('Route.Treeview', background=PANEL2, fieldbackground=PANEL2,
                        foreground=FG, rowheight=20, font=('Consolas', 10))
        style.configure('Route.Treeview.Heading', background=BORDER, foreground=FG)
        self.route_table = ttk.Treeview(debug, columns=('destination', 'metric', 'hop'),
                                        show='headings', height=3, style='Route.Treeview')
        for col, label in [('destination', '目的地址'), ('metric', '距离（16=不可达）'), ('hop', '下一跳')]:
            self.route_table.heading(col, text=label)
            self.route_table.column(col, anchor='center', width=130)
        table_scroll = ttk.Scrollbar(debug, orient='vertical', command=self.route_table.yview)
        self.route_table.configure(yscrollcommand=table_scroll.set)
        table_scroll.pack(side='right', fill='y')
        self.route_table.pack(fill='x', padx=(10, 3), pady=3)
        self.timeline = tk.Scale(canvas_frame, from_=0, to=0, orient='horizontal', resolution=1,
                                 showvalue=False, command=self.seek_frame, bg=PANEL2, fg=MUTED,
                                 troughcolor=BG, highlightthickness=0, sliderlength=18,
                                 label='回放时间线 · 拖动查看窗口', font=('Microsoft YaHei UI', 8))
        self.timeline.pack(fill='x', padx=10)
        self.seed_var = tk.StringVar(value=f'会话 seed={self.session_seed} / 事件 seed={self.world.seed}')
        self.make_label(debug, textvariable=self.seed_var, size=8, color=MUTED, bg=PANEL2).pack(anchor='w', padx=10, pady=(0, 5))

        footer = tk.Frame(self.left, bg=PANEL)
        self.footer = footer
        footer.pack(fill='x', padx=18, pady=(0, 15))
        self.make_label(footer, '━━ 发送路径', 9, 'bold', color=BLUE, bg=PANEL).pack(side='left')
        self.path_var = tk.StringVar(value='尚未发送数据包')
        self.make_label(footer, textvariable=self.path_var, size=10, color=FG, bg=PANEL).pack(side='left', padx=12)
        self.make_label(footer, '  绿色·成功   红色·故障   紫色·禁行   橙色·可疑',
                        8, color=MUTED, bg=PANEL).pack(side='right')

        # Python editor.
        editor_head = tk.Frame(self.right, bg=PANEL)
        editor_head.pack(fill='x', padx=16, pady=(15, 8))
        self.make_label(editor_head, 'PYTHON CODE  /  routing.py', 11, 'bold', bg=PANEL).pack(side='left')
        self.make_label(editor_head, 'Python 3', 9, color=BLUE, bg=PANEL).pack(side='right')
        self.code_hint = self.make_label(self.right,
            '函数接口：def solve(ctx)  ·  Ctrl + Enter 运行',
            9, color=MUTED, bg=PANEL, anchor='w')
        self.code_hint.pack(fill='x', padx=16, pady=(0, 8))
        self.tutorial_bar = tk.Frame(self.right, bg=PANEL2)
        self.tutorial_bar.pack(fill='x', padx=16, pady=(0, 8))
        self.tutorial_label = self.make_label(self.tutorial_bar, '', 10, color=BLUE, bg=PANEL2)
        self.tutorial_label.pack(anchor='w', padx=8)
        self.tutorial_task = self.make_label(self.tutorial_bar, '', 10, color=FG, bg=PANEL2,
                                             justify='left', anchor='w', wraplength=340)
        self.tutorial_task.pack(fill='x', padx=8, pady=(2, 4))
        self.tutorial_bar.bind('<Configure>', lambda e: self.tutorial_task.config(wraplength=max(220, e.width - 18)))
        self.walk_button = self.make_button(self.tutorial_bar, '拆开看', self.next_walk_hint)
        self.walk_button.pack(side='left')
        self.make_button(self.tutorial_bar, '代码提示', self.tutorial_help).pack(side='left')
        self.tutorial_next = self.make_button(self.tutorial_bar, '继续写下一步', self.advance_tutorial)
        self.tutorial_next.pack(side='right')
        editor_wrap = tk.Frame(self.right, bg='#0B1423', highlightbackground=BORDER, highlightthickness=1)
        self.editor_wrap = editor_wrap
        self.service_guide = tk.Frame(self.right, bg=PANEL2)
        heading = tk.Frame(self.service_guide, bg=PANEL2)
        heading.pack(fill='x', padx=8, pady=(4, 0))
        self.service_step = self.make_label(heading, '', 10, 'bold', color=BLUE, bg=PANEL2)
        self.service_step.pack(side='left')
        self.service_example = tk.Button(heading, text='看起手写法', command=self.show_service_example,
                                         bg=PANEL2, fg=BLUE, relief='flat', cursor='hand2')
        self.service_example.pack(side='right')
        self.service_instruction = self.make_label(self.service_guide, '', 10, bg=PANEL2,
                                                  anchor='w', justify='left', wraplength=340)
        self.service_instruction.pack(fill='x', padx=8, pady=(2, 6))
        self.service_guide.bind('<Configure>', lambda e: self.service_instruction.config(wraplength=max(200, e.width-20)))
        editor_wrap.pack(fill='both', expand=True, padx=16)
        yscroll = tk.Scrollbar(editor_wrap, orient='vertical')
        yscroll.pack(side='right', fill='y')
        self.editor = tk.Text(editor_wrap, wrap='none', font=MONO,
                              bg='#0B1423', fg='#D8E7F9', insertbackground=BLUE,
                              selectbackground='#244D73', relief='flat', padx=12, pady=12,
                              undo=True, tabs=('32',), height=12, yscrollcommand=yscroll.set,
                              borderwidth=0, spacing1=1)
        self.editor.pack(side='left', fill='both', expand=True)
        yscroll.config(command=self.editor.yview)
        self.editor.tag_configure('kw', foreground='#87BFFF')
        self.editor.tag_configure('comment', foreground='#8096AD')
        self.editor.tag_configure('string', foreground='#A2DEB0')
        self.editor.bind('<KeyRelease>', self.on_editor_key)
        self.editor.bind('<Tab>', self.complete_word)
        self.editor.bind('<Return>', self.tutorial_newline)
        self.editor.bind('<Control-Return>', self.run_from_editor)
        self.editor.bind('<ButtonRelease-1>', self.update_completion)

        action = tk.Frame(self.right, bg=PANEL)
        action.pack(fill='x', padx=16, pady=(11, 11))
        self.run_btn = self.make_button(action, '▶ 运行并观察', self.run_clicked, primary=True)
        self.run_btn.pack(side='left', fill='x', expand=True, padx=(0, 7))
        self.make_button(action, '提示', self.show_hint).pack(side='left', padx=(0, 7))
        self.reference_button = self.make_button(action, '参考代码', self.load_reference)
        self.reference_button.pack(side='left')

        console_outer = tk.Frame(self.right, bg='#0B1423', highlightbackground=BORDER, highlightthickness=1, height=195)
        console_outer.pack(fill='x', padx=16, pady=(0, 10))
        console_outer.pack_propagate(False)
        bar = tk.Frame(console_outer, bg='#132237')
        bar.pack(fill='x')
        self.make_label(bar, '控制台 / RUN LOG', 9, 'bold', bg='#132237').pack(side='left', padx=12, pady=7)
        self.success_var = tk.StringVar(value='成功传输 0 次')
        self.make_label(bar, textvariable=self.success_var, size=9, color=GREEN, bg='#132237').pack(side='right', padx=12)
        self.console = tk.Text(console_outer, bg='#0B1423', fg='#ABC1D8',
                               font=('Consolas', 10), borderwidth=0, relief='flat',
                               wrap='word', state='disabled', padx=11, pady=9)
        self.console.pack(fill='both', expand=True)
        bottom = tk.Frame(self.right, bg=PANEL)
        bottom.pack(fill='x', padx=16, pady=(0, 13))
        self.make_button(bottom, '查看本轮 ctx', self.inspect_ctx).pack(side='left')
        self.make_button(bottom, '↻ 重置世界', self.reset).pack(side='right')
        mode = '可信本地 · 仅运行自己的代码' if self.backend == 'trusted' else '隔离模式 · 未部署'
        self.make_label(bottom, mode, size=8, color=MUTED, bg=PANEL).pack(side='right', padx=10)

    def refresh_tutorial(self):
        from tutorial import LESSONS, TASKS
        if self.chapter == 0 and self.tutorial_step is not None:
            self.tutorial_label.config(text=f'新手引导 {self.tutorial_step+1}/4 · {LESSONS[self.tutorial_step][0]}')
            self.tutorial_task.config(text=TASKS[self.tutorial_step])
            self.walk_index = 0
            self.walk_button.config(text='拆开看')
            self.update_completion()
            self.run_btn.config(text='▶ 检查本步' if self.tutorial_step < 3 else '▶ 检查并发送')
            self.tutorial_next.config(state='normal' if self.tutorial_passed else 'disabled')
            todo = self.editor.search('# TODO', 'end-1c', backwards=True)
            if todo:
                self.editor.mark_set('insert', f'{todo} +1 lines lineend')
                self.editor.see('insert')

    def next_walk_hint(self):
        from tutorial import TASKS, WALKTHROUGH
        hints = WALKTHROUGH[self.tutorial_step]
        if self.walk_index == len(hints):
            self.walk_index = 0
            self.tutorial_task.config(text=TASKS[self.tutorial_step])
            self.walk_button.config(text='拆开看')
            return
        self.tutorial_task.config(text=f'{self.walk_index + 1}/{len(hints)}  {hints[self.walk_index]}')
        self.walk_index += 1
        self.walk_button.config(text='回到目标' if self.walk_index == len(hints) else '下一条提示')

    def tutorial_help(self):
        from tutorial import LESSONS
        if self.tutorial_step is not None:
            messagebox.showinfo('本步讲解', LESSONS[self.tutorial_step][1], parent=self.root)

    def advance_tutorial(self):
        if self.busy or not self.tutorial_passed or self.tutorial_step >= 3:
            return
        from tutorial import extend_code
        try:
            code = extend_code(self.editor.get('1.0', 'end-1c'), self.tutorial_step+1)
        except ValueError as exc:
            messagebox.showinfo('保留你的代码', str(exc), parent=self.root)
            return
        self.tutorial_step += 1
        self.tutorial_passed = False
        self.editor.delete('1.0','end')
        self.editor.insert('1.0',code)
        self.highlight_code()
        self.refresh_tutorial()

    def console_add(self, text):
        self.console.configure(state='normal')
        self.console.insert('end', text + '\n')
        self.console.see('end')
        self.console.configure(state='disabled')

    def push_event(self, title, brief):
        self.history.append(title + '  ' + brief)
        self.history = self.history[-40:]
        self.feedback = '等待运行。'
        self.refresh_details()
        self.event_title.config(text=title)
        self.event_desc.config(text=brief)
        self.console_add(f'◆ 事件：{title}')
        self.console_add('  ' + brief)
        self.status_var.set('● NETWORK ONLINE · 等待代码')

    def toggle_diagnostics(self):
        if self.diagnostics.winfo_manager():
            self.diagnostics.pack_forget()
            self.panel_button.config(text='展开诊断')
        else:
            self.diagnostics.pack(fill='x', padx=18, pady=(0, 8), before=self.footer)
            self.panel_button.config(text='折叠诊断')

    def refresh_details(self):
        relations = '当前为网内寻路实验。跨运营商任务开始后，这里显示合同与目的地出口范围。'
        state = '\n'.join(f"{e['a']}—{e['b']}　费用 {e['cost']}　{'通车' if e['up'] else '中断'}"
                          for e in self.world.graph())
        if self.world.protocol == 'carrier':
            data = market(self.world.carrier_event, self.world.amendments)
            rows = [f"{k}　{v['name']}　{v['goal']}" for k, v in data['operators'].items()]
            kinds = {'peering':'对等（仅对端目的地）', 'transit':'付费转接', 'internal':'网内'}
            for e in data['links']:
                if e['contract'] != 'internal':
                    rows.append(f"{e['a']}→{e['b']}　{kinds[e['contract']]}　转接费 {e['fee']}　"
                                + (denial(e, data) or '可达 F'))
            relations = '\n'.join(rows)
            state = '\n'.join(f"{e['a']}→{e['b']}　费用 {e['cost']}+{e['fee']}　延迟 {e['delay']}+排队 {e['congestion']} ms　风险 {e['risk']}　"
                              + (denial(e, data) or '可用') for e in data['links'])
        elif self.world.protocol == 'service':
            relations = '登录服务观察点：云渡 B、禾线 C、蓝港 D，汇入蓝港 F。只显示入口汇总。'
            state = '等待窗口。'
            if self.active_frame and 'service' in self.active_frame:
                frame = self.active_frame
                obs, m = frame['observation'], frame['service']
                state = (f"窗口 {m['time']}　入站 {m['received']}/{obs['bandwidth']}　处理 {m['processed']}/{obs['capacity']}"
                         f"　积压 {m['queue']}　平均等待 {m['wait']} 窗\n"
                         f"过滤 {m['filtered']}　容量丢包 {m['dropped']}　实际配额 {frame['policy']}\n" +
                         '　'.join(f"{s}: {v['requests']} 次 / 重复 {v['repeats']}" for s,v in obs['sources'].items()))
                if self.service_focus:
                    s = self.service_focus
                    row = obs['sources'][s]
                    sessions = f"　活跃会话 {row['sessions']}" if 'sessions' in row else ''
                    state = (f"入口 {s}　请求 {row['requests']}　重复 {row['repeats']}{sessions}"
                             f"　在 F 排队 {frame['backlog'][s]}\n" + state)
        for key, value in zip(self.details, ('\n'.join(self.history), state, relations,
                                             self.world.brief, self.feedback)):
            view = self.details[key]
            view.config(state='normal')
            view.delete('1.0', 'end')
            view.insert('end', value)
            view.config(state='disabled')

    def on_canvas_resize(self, event=None):
        width = max(320, self.left.winfo_width() - 45)
        self.event_title.configure(wraplength=width)
        self.event_desc.configure(wraplength=width)
        if self.draw_debounce is not None:
            self.root.after_cancel(self.draw_debounce)
        self.draw_debounce = self.root.after(40, self.draw_network)

    def draw_network(self):
        c = self.canvas
        c.delete('all')
        W = max(c.winfo_width(), 420)
        H = max(c.winfo_height(), 290)
        positions = {n: (50 + x * (W - 105), 25 + y * (H - 58)) for n, (x, y) in POSITIONS.items()}
        for x in range(20, W, 40):
            c.create_line(x, 0, x, H, fill='#13263B')
        for y in range(20, H, 40):
            c.create_line(0, y, W, y, fill='#13263B')
        local = self.world.mode == 'local'
        data = market(self.world.carrier_event, self.world.amendments) if self.world.protocol == 'carrier' else None
        offers = {(e['a'],e['b']): e for e in data['links']} if data else {}
        shown = {self.visual_current}
        edges = [(e['a'], e['b'], e['cost']) for e in self.world.graph()]
        for a, b, cost in edges:
            if a == self.visual_current:
                shown.add(b)
            if b == self.visual_current:
                shown.add(a)
        shown.update(self.visual_path)
        shown.add(DESTINATION)
        failed = self.active_frame.get('failed', self.world.failed) if self.active_frame else self.world.failed
        down = {edge_key(*e) for e in failed}
        travelled = {edge_key(a, b) for a, b in zip(self.visual_path, self.visual_path[1:])}
        for a, b, cost in edges:
            is_visited = edge_key(a, b) in travelled
            is_near = a == self.visual_current or b == self.visual_current
            if local and not (is_visited or is_near):
                continue
            x1, y1 = positions[a]; x2, y2 = positions[b]
            failure = edge_key(a, b) in down
            policy = b in self.world.blocked or a in self.world.blocked
            link = offers.get((a,b))
            if link and denial(link, data):
                policy = True
            suspect = a in self.world.spoofed or b in self.world.spoofed
            color = (GREEN if is_visited else RED if failure else PURPLE if policy else AMBER if suspect else '#7B9FBE')
            width = 5 if is_visited else 3
            traffic = None
            if self.active_frame and 'service' in self.active_frame:
                traffic = self.active_frame['observation']['sources'][a]['requests']
                width, color = min(10, 1 + traffic // 2), AMBER if traffic >= 10 else BLUE
            c.create_line(x1, y1, x2, y2, fill=color, width=width,
                          arrow='last' if link else 'none',
                          dash=(7, 5) if failure else None, tags='links')
            if is_near or not local:
                mx = (x1+x2)/2; my = (y1+y2)/2
                c.create_rectangle(mx-12, my-12, mx+12, my+11, fill='#1C2C40', outline=BORDER)
                label = f"{cost + link['fee']}/{link['delay'] + link['congestion']}ms" if link else str(cost)
                if traffic is not None:
                    label = f'{traffic} 次'
                c.create_text(mx, my, text=label, fill='#DCEAF9', font=('Consolas', 11, 'bold'))
        if self.active_frame:
            for a, b, sent, due in self.active_frame.get('transit', []):
                if local and self.visual_current not in (a, b):
                    continue
                t = (self.active_frame['time'] - sent) / (due - sent)
                x = positions[a][0] + t * (positions[b][0] - positions[a][0])
                y = positions[a][1] + t * (positions[b][1] - positions[a][1])
                c.create_rectangle(x-3, y-3, x+3, y+3, fill=AMBER)
            delivered = [e for e in self.active_frame.get('changes', []) if e['kind'] == 'deliver']
            for msg in delivered[-8:]:
                a, b = msg['sender'], msg['receiver']
                if local and self.visual_current not in (a, b):
                    continue
                c.create_line(*positions[a], *positions[b], fill=AMBER,
                              width=2, dash=(3, 5), arrow='last')
        for name, (x, y) in positions.items():
            if self.world.protocol == 'service' and name not in (*SOURCES, 'F'):
                continue
            if local and name not in shown:
                c.create_oval(x-15, y-15, x+15, y+15, fill='#162537', outline='#273A51', width=1)
                c.create_text(x, y, text='?', fill='#516982', font=('Consolas', 12, 'bold'))
                continue
            current = name == (self.service_focus if self.world.protocol == 'service' else self.visual_current)
            visited = name in self.visual_path
            blocked = name in self.world.blocked
            spoofed = name in self.world.spoofed
            color = BLUE if current else GREEN if visited else PURPLE if blocked else AMBER if spoofed else '#466C8D'
            r = 25 if current else 22
            if data:
                owner = data['owners'][name]
                ink = data['operators'][owner]['color']
                c.create_oval(x-r-4, y-r-4, x+r+4, y+r+4, outline=ink, width=3)
                c.create_text(x, y-r-12, text='运营商 '+owner, fill=ink)
            elif self.world.protocol == 'service':
                ink = OPERATORS[OWNER[name]]['color']
                c.create_oval(x-r-4, y-r-4, x+r+4, y+r+4, outline=ink, width=3)
                c.create_text(x, y-r-12, text=OPERATORS[OWNER[name]]['name'].split(' · ')[0], fill=ink)
            if current:
                c.create_oval(x-r-7, y-r-7, x+r+7, y+r+7, outline='#296B86', width=2)
            tag = ('inspect_'+name,) if self.world.protocol == 'service' else ()
            c.create_oval(x-r, y-r, x+r, y+r, fill='#142A41', outline=color, width=3 if current else 2, tags=tag)
            c.create_text(x, y, text=name, fill='#F0F7FF', font=('Consolas', 13, 'bold'), tags=tag)
            if name == SOURCE or name == DESTINATION:
                c.create_text(x, y+32, text='SOURCE' if name == SOURCE else 'TARGET',
                              fill='#91ACC5', font=('Consolas', 8, 'bold'))
        if self.packet_t is not None:
            a, b, progress = self.packet_t
            ax, ay = positions[a]; bx, by = positions[b]
            x, y = ax+(bx-ax)*progress, ay+(by-ay)*progress
            c.create_oval(x-8, y-8, x+8, y+8, fill=GREEN, outline='#E5FFF5', width=2)
        if local:
            c.create_text(W/2, H-12, text='局部视野：仅展示当前路由器的邻居、已走路径和目标位置',
                          fill='#748DA6', font=('Microsoft YaHei UI', 9))
        if self.active_frame and 'service' in self.active_frame:
            m = self.active_frame['service']
            samples = self.frames[:self.frame_index+1]
            s = self.service_focus
            c.create_text(12, 12, anchor='w', fill=MUTED, text=s or '全网')
            c.create_text(49, 12, anchor='w', fill=BLUE, text='请求')
            if s:
                c.create_text(84, 12, anchor='w', fill=PURPLE, text='重复')
            c.create_text(119 if s else 84, 12, anchor='w', fill=AMBER, text='积压')
            series = [(BLUE, [f['service']['offered'] for f in samples]), (AMBER, [f['service']['queue'] for f in samples])]
            if s:
                series = [(BLUE, [f['observation']['sources'][s]['requests'] for f in samples]),
                          (PURPLE, [f['observation']['sources'][s]['repeats'] for f in samples]),
                          (AMBER, [f['backlog'][s] for f in samples])]
            for ink, values in series:
                points = [(158+i*8, 29-min(26, value*.5)) for i,value in enumerate(values)]
                if len(points) > 1:
                    c.create_line(*points, fill=ink, width=2)
            caption = f"窗口 {m['time']}　排队 {m['queue']}　丢包 {m['dropped']}　完成 {m['processed']}"
            if s:
                row = self.active_frame['observation']['sources'][s]
                caption = f"窗口 {m['time']} · {s}　请求 {row['requests']}　重复 {row['repeats']}　在队 {self.active_frame['backlog'][s]}"
                if 'sessions' in row:
                    caption += f"　会话 {row['sessions']}"
            c.create_text(W/2, H-17, fill=FG, text=caption)

    def on_editor_key(self, event=None):
        self.highlight_code()
        self.update_completion()

    def editor_completion(self):
        from tutorial import completion
        if (self.tutorial_step is None or self.chapter != 0 or self.editor.tag_ranges('sel')
                or self.editor.get('insert', 'insert lineend').strip()):
            return None
        return completion(self.editor.get('insert linestart', 'insert'), self.tutorial_step)

    def update_completion(self, event=None):
        if self.tutorial_step is None or self.chapter != 0:
            return
        suggestion = self.editor_completion()
        hint = f'Tab 补全  {suggestion[1]}' if suggestion else '在 TODO 下方续写 · 输入后按 Tab 补全 · Ctrl + Enter 检查'
        self.code_hint.config(text=hint, fg=BLUE if suggestion else MUTED)

    def complete_word(self, event=None):
        if self.tutorial_step is None or self.chapter != 0 or self.editor.tag_ranges('sel'):
            return
        suggestion = self.editor_completion()
        self.editor.insert('insert', suggestion[0] if suggestion else '    ')
        self.highlight_code()
        self.update_completion()
        return 'break'

    def tutorial_newline(self, event=None):
        if self.tutorial_step is None or self.chapter != 0 or self.editor.tag_ranges('sel'):
            return
        line = self.editor.get('insert linestart', 'insert')
        indent = re.match(r'[ \t]*', line).group()
        if line.rstrip().endswith(':') and not line.lstrip().startswith('#'):
            indent += '    '
        self.editor.insert('insert', '\n' + indent)
        self.editor.see('insert')
        return 'break'

    def run_from_editor(self, event):
        self.run_clicked(event)
        return 'break'

    def highlight_code(self):
        code = self.editor.get('1.0', 'end-1c')
        for tag in ('kw', 'comment', 'string'):
            self.editor.tag_remove(tag, '1.0', 'end')
        for m in re.finditer(r'\b(?:def|return|for|while|if|else|elif|and|or|not|in|True|False|None|break|continue|import|from)\b', code):
            self._tag_offset('kw', code, m.start(), m.end())
        for m in re.finditer(r'#[^\n]*', code):
            self._tag_offset('comment', code, m.start(), m.end())
        for m in re.finditer(r'(?:"[^"\n]*"|\'[^\'\n]*\')', code):
            self._tag_offset('string', code, m.start(), m.end())

    def _tag_offset(self, name, code, start, end):
        s = f'1.0+{start}c'; e = f'1.0+{end}c'
        self.editor.tag_add(name, s, e)

    def display_frame(self, index):
        if not self.frames:
            return
        index = max(0, min(index, len(self.frames)-1))
        self.frame_index = index
        self.active_frame = frame = self.frames[index]
        self._setting_timeline = True
        self.timeline.set(index)
        self._setting_timeline = False
        if 'service' in frame:
            self.debug_var.set(f"窗口 {frame['time']} · 入站请求 {frame['service']['offered']}")
            self.refresh_details()
            self.draw_network()
            return
        node = self.inspect_node.get()
        self.route_table.delete(*self.route_table.get_children())
        for dest, route in sorted(frame['tables'].get(node, {}).items(),
                                  key=lambda item: (item[0] != DESTINATION, item[0])):
            value = '16 ∞' if route['metric'] == 16 else str(route['metric'])
            self.route_table.insert('', 'end', values=(dest, value, route['next_hop'] or '—'))
        arrived = sum(e['kind'] == 'deliver' for e in frame['changes'])
        changed = sum(e['kind'] == 'table' for e in frame['changes'])
        self.debug_var.set(f"t={frame['time']} · 送达 {arrived} · 表变 {changed} · 在途 {frame['in_flight']}")
        loops = frame.get('routing_loops', [])
        if loops:
            self.debug_var.set(self.debug_var.get() + ' · 表中环路 ' +
                               ' / '.join('→'.join(cycle) for cycle in loops))
        self.draw_network()

    def select_router(self, name):
        if self.world.mode == 'local':
            self.visual_current = name
            self.vision_var.set(f'局部视野 · 观察路由器 {name}')
        if self.frames:
            self.display_frame(self.frame_index)
        else:
            self.draw_network()

    def inspect_gate(self, node):
        self.service_focus = node if node in SOURCES else None
        if self.active_frame:
            self.refresh_details()
        self.draw_network()

    def seek_frame(self, value):
        if self._setting_timeline or not self.frames:
            return
        if self.busy and not (self.paused and self.world.protocol == 'service'):
            self.timeline.set(self.frame_index)
            return
        index = int(float(value))
        if index == self.frame_index:
            return
        frame = self.frames[index]
        self.packet_t = None
        packet = frame.get('packet')
        if packet:
            self.packet_t = (packet['sender'], packet['receiver'], .5)
        self.visual_path = []
        self.display_frame(index)
        if self.paused and self.world.protocol == 'service':
            self.play_action = lambda: self._replay_control(self.last_result, index+1)

    def inspect_messages(self):
        popup = tk.Toplevel(self.root)
        popup.title('消息时间线 · 当前时隙明细（观察器）')
        popup.geometry('820x600')
        popup.configure(bg=BG)
        note = '拖动时间线可回看：send=发送，deliver=送达，drop=丢弃，table=更新，loop=环路。'
        self.make_label(popup, note, 10, wraplength=760).pack(anchor='w', padx=16, pady=12)
        view = tk.Text(popup, bg=PANEL, fg=FG, font=('Consolas', 10), wrap='none')
        view.pack(fill='both', expand=True, padx=16, pady=(0, 16))
        data = self.active_frame or {'说明': '请先运行一次，观察实际消息传播。'}
        view.insert('1.0', json.dumps(data, ensure_ascii=False, indent=2))
        view.configure(state='disabled')

    def inspect_ctx(self):
        current = self.inspect_node.get() if self.world.mode == 'local' else SOURCE
        ctx = ctx_for(self.world, current, checkpoint=self.event_checkpoint)
        if self.active_frame and 'observation' in self.active_frame:
            ctx = self.active_frame['observation']
        if self.last_result and current in self.last_result.get('update_contexts', {}):
            ctx = self.last_result['update_contexts'][current]
        popup = tk.Toplevel(self.root)
        popup.title('当前输入 ctx · 只读观察')
        popup.geometry('660x520')
        popup.configure(bg=BG)
        caption = (f'路由器 {current} / 最近 update 输入或起点样例' if self.world.protocol == 'dv'
                   else 'solve(ctx) 本次任务的输入资料')
        self.make_label(popup, caption, 10, 'bold').pack(anchor='w', padx=18, pady=12)
        display = tk.Text(popup, bg=PANEL, fg='#CDE6FF', font=('Consolas', 10), wrap='none', padx=14, pady=12)
        display.pack(fill='both', expand=True, padx=18, pady=(0,18))
        display.insert('1.0', json.dumps(ctx, indent=2, ensure_ascii=False))
        display.configure(state='disabled')

    def show_hint(self):
        if self.world.protocol == 'service':
            level = self.hint_level
            incident = INCIDENTS[self.world.title]
            messagebox.showinfo(f'{incident.id} 调查提示 {level+1}/3', incident.hints[level], parent=self.root)
            self.hint_level = min(2, level + 1)
            return
        from learning_help import help_text
        popup = tk.Toplevel(self.root)
        popup.title('工程师手册 · 边看提示边改代码')
        popup.geometry('800x680')
        popup.configure(bg=BG)
        self.make_label(popup, '观察 → 理解 → 动手修改', 16, 'bold', color=BLUE).pack(anchor='w', padx=20, pady=16)
        frame = tk.Frame(popup, bg=PANEL)
        frame.pack(fill='both', expand=True, padx=20, pady=(0, 20))
        scroll = ttk.Scrollbar(frame)
        scroll.pack(side='right', fill='y')
        view = tk.Text(frame, wrap='word', font=('Microsoft YaHei UI', 12),
                       bg=PANEL, fg=FG, padx=18, pady=16, spacing3=8,
                       yscrollcommand=scroll.set)
        view.pack(fill='both', expand=True)
        scroll.configure(command=view.yview)
        if self.world.protocol == 'carrier':
            guide = (self.world.brief + '\n\n① 在“运营商关系”对照站点所属网络与合同。'
                     '\n② 遍历 ctx["links"] 的有向出口。检查 up、origin 和 peering 的目的地范围。'
                     '\n③ 在合规出口中按 objective 计分：cost 加 fee；delay 加 congestion；risk 累加风险分。'
                     '\n返回从 A 到 F 的站名列表。这里模拟已知合同下的选路，不模拟 BGP 协议。')
        else:
            guide = help_text(self.chapter)
        view.insert('1.0', guide)
        view.configure(state='disabled')

    def load_reference(self):
        if self.busy:
            return
        if self.world.protocol == 'service':
            self.replay_service_baseline()
            return
        new_code = reference_for(self.world)
        if self.editor.get('1.0', 'end-1c').strip() == new_code.strip():
            return
        if not messagebox.askyesno('载入参考实现', '这会替换编辑器里的代码。确定要查看当前环境的参考实现吗？', parent=self.root):
            return
        self.tutorial_step = None
        self.tutorial_bar.pack_forget()
        if self.chapter == 0:
            self.run_btn.config(text='▶ 运行并观察')
            self.code_hint.config(text='返回整条路径 list[str]')
        self.editor.delete('1.0', 'end')
        self.editor.insert('1.0', new_code)
        self.highlight_code()
        self.console_add('ℹ 已加载当前环境的参考实现，可修改后再运行。')

    def run_clicked(self, event=None):
        if self.busy:
            return
        code = self.editor.get('1.0', 'end-1c')
        self.busy = True
        if self.world.protocol == 'service':
            self.service_step.config(text='3/3 · 检验你的判断')
            self.service_instruction.config(text='这次使用和基线完全相同的请求。看队列是否缩短，再检查正常玩家还能不能登录。')
        self.active_frame = None
        self.editor.tag_remove('error_line', '1.0', 'end')
        self.run_btn.configure(state='disabled', bg='#315071', text='⏳ Python 正在运行')
        self.status_var.set('● SIMULATING · 正在计算')
        self.visual_current = SOURCE
        self.visual_path = []
        self.packet_t = None
        self.draw_network()
        self.console_add('────────────────────────────')
        self.console_add('▶ 执行 solve(ctx)')
        payload = {'world': asdict(self.world), 'code': code}
        payload['checkpoint'] = self.event_checkpoint
        if self.chapter == 0 and self.tutorial_step is not None:
            payload['tutorial_step'] = self.tutorial_step
        threading.Thread(target=self._subprocess_worker, args=(payload,), daemon=True).start()

    def _subprocess_worker(self, payload):
        self.results_queue.put(run_isolated(payload, backend=self.backend))

    def poll_results(self):
        try:
            while True:
                self.on_result(self.results_queue.get_nowait())
        except queue.Empty:
            pass
        self.root.after(80, self.poll_results)

    def on_result(self, result):
        if result.get('error_line'):
            line = result['error_line']
            self.editor.tag_configure('error_line', background='#66313D')
            self.editor.tag_remove('error_line', '1.0', 'end')
            self.editor.tag_add('error_line', f'{line}.0', f'{line}.end')
            self.editor.see(f'{line}.0')
        if self.chapter == 0 and self.tutorial_step is not None:
            self.busy = False
            self.run_btn.configure(state='normal', text='▶ 检查本步' if self.tutorial_step < 3 else '▶ 检查并发送', bg='#267ED0')
            self.console_add(result['message'])
            self.feedback = result['message']
            self.refresh_details()
            if not result.get('ok'):
                self.tutorial_passed = False
                self.tutorial_next.config(state='disabled')
                return
            if self.tutorial_step < 3:
                self.tutorial_passed = True
                self.tutorial_next.config(state='normal')
                self.console_add('点击“继续写下一步”，会保留你已写的代码并追加练习。')
                return
            self.tutorial_step = None
            self.tutorial_bar.pack_forget()
            self.run_clicked()
            return
        self.last_result = result
        self.frames = result.get('frames', [])
        self.timeline.configure(to=max(0, len(self.frames)-1))
        self.status_var.set('● REPLAY · 正在回放本次传输')
        events = result.get('events', [])
        if events:
            counts = {kind: sum(e['kind'] == kind for e in events) for kind in ('send', 'deliver', 'drop', 'table', 'loop')}
            self.console_add(f"  控制面：发送 {counts['send']} / 送达 {counts['deliver']} / 丢弃 {counts['drop']}；"
                             f"表变化 {counts['table']}；环路观测 {counts['loop']}。")
        self._replay_control(result)

    def schedule_playback(self, delay, action):
        self.play_action = action
        if not self.paused:
            self.play_timer = self.root.after(max(1, delay // self.speed.get()), self.advance_playback)

    def advance_playback(self):
        action = self.play_action
        self.play_action = self.play_timer = None
        if action:
            action()

    def toggle_playback(self):
        if not self.play_action:
            return
        self.paused = not self.paused
        self.pause_button.config(text='继续' if self.paused else '暂停')
        if self.paused:
            self.root.after_cancel(self.play_timer)
            self.play_timer = None
        else:
            self.advance_playback()

    def step_playback(self):
        if self.play_action and not self.paused:
            self.toggle_playback()
        if self.paused:
            self.advance_playback()

    def _replay_control(self, result, index=0, segment=0):
        if index < len(self.frames):
            self.packet_t = None
            self.display_frame(index)
            if self.frames[index].get('packet'):
                self._animate_route(result['route'], segment, 0, result['ok'])
            else:
                delay = 310 if 'service' in self.frames[index] else 70
                self.schedule_playback(delay, lambda: self._replay_control(result, index + 1, segment))
            return
        route = result.get('route') or []
        if len(route) > 1 and not self.frames:
            self._animate_route(route, 0, 0, bool(result['ok']))
        else:
            self.finish_result(bool(result['ok']))

    def _animate_route(self, route, segment, t, success):
        if segment >= len(route)-1:
            self.packet_t = None
            self.visual_current = route[-1]
            self.visual_path = list(route)
            self.path_var.set(' → '.join(route))
            self.draw_network()
            self.schedule_playback(550, lambda: self.finish_result(success))
            return
        self.visual_current = route[segment]
        self.visual_path = list(route[:segment+1])
        self.packet_t = (route[segment], route[segment+1], min(1, t / 8))
        self.draw_network()
        if t >= 8:
            if self.frames:
                self.visual_current = route[segment + 1]
                self.visual_path = route[:segment + 2]
                self.path_var.set(' → '.join(self.visual_path))
                next_frame = self.frame_index + 1
                self.schedule_playback(60, lambda: self._replay_control(self.last_result, next_frame, segment + 1))
            else:
                self.schedule_playback(60, lambda: self._animate_route(route, segment+1, 0, success))
        else:
            self.schedule_playback(40, lambda: self._animate_route(route, segment, t+1, success))

    def finish_result(self, success):
        if self.last_result.get('preview'):
            first = self.frames[0]['service']
            peak = max(self.frames, key=lambda f: f['service']['offered'])['service']
            self.service_step.config(text='2/3 · 写第一条策略')
            self.service_instruction.config(text=f"窗口 {first['time']} 收到 {first['offered']} 次请求；窗口 {peak['time']} 收到 {peak['offered']} 次。"
                                           "看哪一个入口的重复访问增加了。点「看起手写法」，先运行空策略，再试着只调整一个入口。")
            if self.world.title == 'S2':
                self.service_step.config(text='2/3 · 试运行上一关的规则')
                self.service_instruction.config(text='代码已保留。先点「验证策略」，看有多少正常玩家被误封；再点 B、C、D 比较同样的重试量来自多少会话。')
            self.busy = self.paused = False
            self.pause_button.config(text='暂停')
            self.run_btn.configure(state='normal', text='▶ 验证策略')
            self.status_var.set('● 调查中 · 可拖动时间线或运行策略')
            return
        self.feedback = self.last_result['message'] + '\n' + '\n'.join(self.last_result.get('log', [])[-6:])
        if self.world.protocol == 'service':
            before, after = self.last_result.get('before'), self.last_result.get('after')
            if before and after:
                self.service_instruction.config(text=f"正常登录 {before['availability']:.0%} → {after['availability']:.0%}，"
                                               f"平均积压 {before['mean_queue']:.1f} → {after['mean_queue']:.1f}。"
                                               + ('服务已恢复。' if success else self.last_result['message']))
                if self.world.title == 'S2':
                    self.service_instruction.config(text=f"正常完成 {after['availability']:.0%} · 误封 {after['false_positive']:.0%} · 漏放 {after['false_negative']:.0%}。"
                                                   + self.last_result['message'])
            else:
                self.service_step.config(text='2/3 · 检查策略写法')
                self.service_instruction.config(text='策略还没有生成可比较的结果。看控制台错误；确认 service 分支在读取旧路由字段之前返回配额字典。')
        self.history.append(self.world.headline + ' · ' +
                            (self.feedback if self.world.protocol == 'service' else self.last_result['message']))
        self.history = self.history[-40:]
        self.refresh_details()
        self.paused = False
        self.pause_button.config(text='暂停')
        for entry in self.last_result.get('log', [])[-12:]:
            self.console_add('  ' + entry)
        self.console_add(('✓ ' if success else '✕ ') + self.last_result['message'])
        if success:
            self.success_count += 1
            self.success_var.set(f'成功传输 {self.success_count} 次')
            self.status_var.set('● PACKET DELIVERED · 自动演化中')
            self.console_add('… 传输成功。新的网络事件即将发生。')
            self.root.after(2200, self.next_world)
        else:
            self.status_var.set('● ACTION REQUIRED · 等待修改')
            self.busy = False
            self.run_btn.configure(state='normal', bg='#267ED0', text='▶ 运行并观察')

    def next_world(self):
        self.service_guide.pack_forget()
        if self.last_result and self.last_result.get('ok') and self.world.protocol in ('legacy', 'dv'):
            self.event_checkpoint = self.last_result.get('checkpoint')
        self.tutorial_bar.pack_forget()
        self.chapter += 1
        if self.chapter >= 6:
            self.cycle += 1
        self.world = session_world(self.chapter, self.rng, self.cycle, self.amendments)
        if self.world.protocol == 'carrier':
            self.amendments = self.world.amendments
        self.visual_current = SOURCE
        self.visual_path = []
        self.packet_t = None
        self.frames = []
        self.active_frame = None
        self.last_result = None
        self.timeline.configure(to=0)
        self.route_table.delete(*self.route_table.get_children())
        self.debug_var.set('t=起点 · 上次成功状态延续；失败重试起点固定')
        self.seed_var.set(f'会话 seed={self.session_seed} / 事件 seed={self.world.seed}')
        self.path_var.set('新事件发生 · 等待新策略')
        self.vision_var.set('全局视野' if self.world.mode == 'global' else '局部视野 · 当前路由器 A')
        self.code_hint.config(text='返回整条路径 list[str]' if self.world.mode == 'global' else 'solve(ctx)：update → table + advertise；forward → str / None')
        if self.world.protocol == 'carrier':
            self.vision_var.set('线路标签：总费用 / 延迟')
            self.code_hint.config(text='跨网规划 · 读取 ctx["links"] 和 objective，返回站名列表')
            self.debug_var.set('查看运营商关系及网络状态')
            self.diagnostics.select(self.details['运营商关系'])
        else:
            self.diagnostics.select(0)
        self.push_event(self.world.headline, self.world.brief)
        self.draw_network()
        self.busy = False
        self.run_btn.configure(state='normal', bg='#267ED0', text='▶ 运行并观察')
        self.reference_button.config(text='参考代码')
        if self.world.protocol == 'service':
            self.hint_level = 0
            self.service_focus = None
            self.service_guide.pack(fill='x', padx=16, pady=(0, 8), before=self.editor_wrap)
            self.code_hint.config(text='每窗调用 solve(ctx) · 返回入口配额 · 点提示逐层调查')
            self.vision_var.set('游戏服 F · 三个入口的每窗请求数')
            self.diagnostics.select(self.details['网络状态'])
            self.reference_button.config(text='重放基线')
            self.replay_service_baseline()

    def replay_service_baseline(self):
        self.service_step.config(text='1/3 · 先看服务器怎么变慢')
        self.service_instruction.config(text='这一遍先观察。左侧「网络状态」列出三个入口的请求数和重复次数：队列从哪个窗口开始积压？可以暂停或单步查看。')
        if self.world.title == 'S2':
            self.service_step.config(text='1/3 · 观察活动高峰')
            self.service_instruction.config(text='点一个入口看请求、重复和积压曲线。暂停后拖动地图下方的时间线，对比不同窗口的活跃会话数；点 F 回到全网。')
        self.frames, _ = simulate(self.world.seed, lambda ctx: {}, INCIDENTS[self.world.title])
        self.timeline.configure(to=len(self.frames)-1)
        self.last_result = dict(preview=True, ok=False, route=[])
        self.busy = True
        self.run_btn.configure(state='disabled', text='观察无策略基线')
        self.status_var.set('● 正在播放无策略基线')
        self._replay_control(self.last_result)

    def show_service_example(self):
        popup = tk.Toplevel(self.root)
        popup.title(self.world.title + ' · 给已有 solve 添加一个分支')
        popup.configure(bg=PANEL)
        if self.world.title == 'S2':
            popup.title('S2 · 调整上一关的策略')
            self.make_label(popup, '在现有 service 分支里，找到决定哪个入口要限速的条件。', 10, bg=PANEL).pack(padx=12, pady=8)
            sample = tk.Text(popup, width=54, height=4, bg=BG, fg=FG, font=('Consolas', 11))
            sample.pack(fill='both', expand=True, padx=12)
            sample.insert('1.0', 'for station, stats in ctx["sources"].items():\n'
                          '    retries = stats["repeats"]\n'
                          '    sessions = stats["sessions"]\n'
                          '    # 这批重试集中在少数会话，还是分散在许多人身上？')
            sample.config(state='disabled')
            self.make_label(popup, '用地图上的窗口比较两种情况，再改自己的判断条件。', 10, bg=PANEL).pack(padx=12, pady=8)
            return
        self.make_label(popup, '在 def solve(ctx): 下面、原路由逻辑前面加入这几行。',
                        10, bg=PANEL).pack(anchor='w', padx=12, pady=8)
        sample = tk.Text(popup, width=55, height=6, bg=BG, fg=FG, font=('Consolas', 11))
        sample.pack(fill='both', expand=True, padx=12)
        sample.insert('1.0', '    if ctx["mode"] == "service":\n'
                      '        quotas = {}\n'
                      '        for station, stats in ctx["sources"].items():\n'
                      '            # 比较 stats["requests"] 和 stats["repeats"]\n'
                      '            pass\n'
                      '        return {"repeat_limits": quotas}')
        sample.config(state='disabled')
        self.make_label(popup, '空字典表示放行。先验证一次，再把 pass 换成自己的判断，\n用 quotas[station] 记录该入口每窗允许的重复次数。',
                        10, bg=PANEL, justify='left').pack(anchor='w', padx=12, pady=8)

    def reset(self):
        if self.busy:
            messagebox.showinfo('正在发送数据包', '请等本次动画结束后再重置。', parent=self.root)
            return
        if not messagebox.askyesno('重置网络', '重新开始同一随机种子的网络演化？编辑器代码会保留。', parent=self.root):
            return
        self.chapter = 0
        self.cycle = 0
        self.success_count = 0
        self.service_guide.pack_forget()
        self.rng = random.Random(self.session_seed)
        self.history.clear()
        self.amendments = None
        self.event_checkpoint = None
        self.last_result = None
        self.frames = []
        self.active_frame = None
        self.timeline.configure(to=0)
        self.route_table.delete(*self.route_table.get_children())
        self.seed_var.set(f'会话 seed={self.session_seed}')
        self.debug_var.set('t=0 · 尚未交换消息')
        self.world = world_for(0, self.rng)
        self.reference_button.config(text='参考代码')
        self.visual_current = SOURCE
        self.visual_path = []
        self.packet_t = None
        self.success_var.set('成功传输 0 次')
        self.console.configure(state='normal')
        self.console.delete('1.0', 'end')
        self.console.configure(state='disabled')
        self.path_var.set('尚未发送数据包')
        self.vision_var.set('全局视野')
        self.code_hint.config(text='返回整条路径 list[str] · 当前代码已保留')
        self.push_event(self.world.headline, self.world.brief)
        self.draw_network()


def main():
    parser = argparse.ArgumentParser(description='RouteLab v0.4 · 动态网络与跨网运营')
    parser.add_argument('--seed', type=int, default=20261028, help='固定会话种子，用于重放事件')
    parser.add_argument('--backend', choices=['trusted','isolated'], default='trusted')
    args = parser.parse_args()
    # Set DPI awareness before creating any Tk window on Windows.
    if sys.platform == 'win32':
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except (AttributeError, OSError):
                pass
    root = tk.Tk()
    RouteLabApp(root, seed=args.seed, backend=args.backend)
    root.mainloop()


if __name__ == '__main__':
    main()
