import argparse
import os
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from .engine import DownloadManager
if os.name == 'nt':
    from .windows_tray import TrayIcon
else:
    from .tray import TrayIcon
if os.name == 'nt':
    from .windows_install import autostart_enabled, set_autostart
else:
    from .desktop_install import autostart_enabled, set_autostart
from .categories import CATEGORIES, detect_category, category_directory, suggested_directory
from .bridge import AppInstance, drain_inbox, request_show, consume_show

BG = '#17191d'
SURFACE = '#202328'
INK = '#e9e7df'
MUTED = '#9b9fa8'
ACCENT = '#e9bd55'
BORDER = '#34373d'
NAV = '#111316'


def size(value):
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if value < 1024:
            return f'{value:.1f} {unit}'
        value /= 1024
    return f'{value:.1f} PiB'


class DownloadApp:
    def __init__(self, root, manager):
        self.root, self.manager = root, manager
        self.filter = 'All downloads'
        self.queue_filter = None
        self.queue_fingerprint = None
        self.jobs = []
        self.dialog = None
        self.closing = False
        self.refresh_timer = None
        self.directory = str(Path.home() / 'Downloads')
        self.connections = 4
        root.title('LinuxDM — Downloads')
        root.geometry('1080x640')
        root.minsize(900, 560)
        root.configure(bg=BG)
        root.option_add('*Font', '{DejaVu Sans} -12')
        self._styles()
        self._sidebar()
        self._content()
        root.protocol('WM_DELETE_WINDOW', self.hide)
        root.bind('<Control-n>', lambda _: self.add_dialog())
        root.bind('<Control-f>', lambda _: self.search_entry.focus_set())
        self.refresh()

    def _styles(self):
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('.', font=('DejaVu Sans', -12), background=BG, foreground=INK)
        style.configure('TButton', background=SURFACE, foreground=INK, bordercolor=BORDER,
                        lightcolor=SURFACE, darkcolor=SURFACE, padding=(10, 5), relief='flat')
        style.map('TButton', background=[('active', '#30343b')],
                  foreground=[('disabled', '#656a73')])
        style.configure('Primary.TButton', background=ACCENT, foreground=NAV,
                        bordercolor=ACCENT, lightcolor=ACCENT, darkcolor=ACCENT)
        style.map('Primary.TButton', background=[('disabled', '#3b372d'), ('active', '#f5cc70')],
                  foreground=[('disabled', '#8a8067'), ('!disabled', NAV)])
        style.configure('TEntry', fieldbackground=NAV, foreground=INK, insertcolor=ACCENT,
                        bordercolor=BORDER, lightcolor=NAV, darkcolor=NAV, padding=6)
        style.map('TEntry', bordercolor=[('focus', ACCENT)])
        style.configure('TSpinbox', fieldbackground=NAV, foreground=INK, insertcolor=ACCENT,
                        background=SURFACE, arrowcolor=MUTED, bordercolor=BORDER,
                        lightcolor=SURFACE, darkcolor=SURFACE, padding=3)
        style.map('TSpinbox', background=[('active', '#30343b')], arrowcolor=[('active', ACCENT)])
        style.configure('TCombobox', fieldbackground=NAV, foreground=INK, background=SURFACE,
                        arrowcolor=ACCENT, bordercolor=BORDER, padding=4)
        style.map('TCombobox', fieldbackground=[('readonly', NAV)], foreground=[('readonly', INK)])
        self.root.option_add('*TCombobox*Listbox.background', SURFACE)
        self.root.option_add('*TCombobox*Listbox.foreground', INK)
        self.root.option_add('*TCombobox*Listbox.selectBackground', '#403923')
        style.configure('TMenubutton', background=SURFACE, foreground=INK, padding=(8, 5))
        style.configure('Treeview', background=SURFACE, fieldbackground=SURFACE, foreground=INK,
                        bordercolor=SURFACE, lightcolor=SURFACE, darkcolor=SURFACE,
                        rowheight=30, borderwidth=0, font=('DejaVu Sans', -12))
        style.configure('Treeview.Heading', background='#26292f', foreground=MUTED,
                        bordercolor='#26292f', lightcolor='#26292f', darkcolor='#26292f',
                        font=('DejaVu Sans', -10, 'bold'), padding=(7, 7), relief='flat')
        style.map('Treeview', background=[('selected', '#403923')], foreground=[('selected', '#f5d88d')])
        style.map('Treeview.Heading', background=[('active', '#30343b')])
        style.configure('Horizontal.TProgressbar', background=ACCENT, troughcolor=NAV,
                        borderwidth=0, bordercolor=NAV, lightcolor=ACCENT, darkcolor=ACCENT, thickness=6)
        style.configure('Vertical.TScrollbar', background='#3a3e46', troughcolor=SURFACE,
                        bordercolor=SURFACE, lightcolor=SURFACE, darkcolor=SURFACE,
                        arrowcolor=MUTED, borderwidth=0, arrowsize=10)
        style.map('Vertical.TScrollbar', background=[('active', '#545964')])

    def label(self, parent, text='', size_=12, color=INK, bold=False, bg=None, **kwargs):
        return tk.Label(parent, text=text, bg=bg or parent.cget('bg'), fg=color,
                        font=('DejaVu Sans', -abs(size_), 'bold' if bold else 'normal'), **kwargs)

    def _sidebar(self):
        sidebar = tk.Frame(self.root, bg=NAV, width=156)
        sidebar.pack(side='left', fill='y')
        sidebar.pack_propagate(False)
        self.label(sidebar, '↓  LinuxDM', 17, ACCENT, True).pack(anchor='w', padx=16, pady=(20, 3))
        self.label(sidebar, 'DOWNLOAD MANAGER', 9, MUTED).pack(anchor='w', padx=16)
        self.label(sidebar, 'LIBRARY', 9, MUTED, True).pack(anchor='w', padx=16, pady=(28, 8))
        self.nav_buttons = {}
        for title in ('All downloads', 'In progress', 'Paused', 'Completed'):
            button = tk.Button(sidebar, text=title, anchor='w', padx=10, pady=8,
                               bg=NAV, fg=MUTED, activebackground='#302b20', activeforeground=ACCENT,
                               relief='flat', bd=0, highlightthickness=0, cursor='hand2',
                               command=lambda name=title: self.set_filter(name))
            button.pack(fill='x', padx=8, pady=2)
            self.nav_buttons[title] = button
        footer = tk.Frame(sidebar, bg=NAV)
        footer.pack(side='bottom', fill='x', padx=16, pady=18)
        self.label(footer, 'BUILT FOR LINUX', 9, MUTED, True).pack(anchor='w')
        self.label(footer, 'Queue · Pause · Resume', 9,
                   MUTED, justify='left', wraplength=124).pack(anchor='w', pady=(8, 0))
        self.label(sidebar, 'QUEUES', 9, MUTED, True).pack(anchor='w', padx=16, pady=(14, 6))
        queue_area = tk.Frame(sidebar, bg=NAV)
        queue_area.pack(fill='both', expand=True, padx=8)
        self.queue_list = tk.Listbox(queue_area, bg=NAV, fg=INK, selectbackground='#403923',
                                    selectforeground=ACCENT, bd=0, highlightthickness=0,
                                    exportselection=False, activestyle='none', height=3)
        queue_scroll = ttk.Scrollbar(queue_area, orient='vertical', command=self.queue_list.yview)
        self.queue_list.configure(yscrollcommand=queue_scroll.set)
        queue_scroll.pack(side='right', fill='y')
        self.queue_list.pack(fill='both', expand=True)
        self.queue_list.bind('<<ListboxSelect>>', self.select_queue)
        self.queue_toggle = ttk.Button(sidebar, text='Pause queue', command=self.toggle_queue)
        self.queue_toggle.pack(fill='x', padx=8, pady=(6, 4))
        ttk.Button(sidebar, text='Manage queues…', command=self.manage_queues).pack(fill='x', padx=8, pady=(0, 4))

    def _content(self):
        main = tk.Frame(self.root, bg=BG, padx=16, pady=16)
        main.pack(side='left', fill='both', expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(3, weight=1)
        header = tk.Frame(main, bg=BG)
        header.grid(row=0, column=0, sticky='ew')
        titles = tk.Frame(header, bg=BG)
        titles.pack(side='left')
        self.label(titles, 'Downloads', 21, bold=True).pack(anchor='w')
        self.label(titles, 'Your files, under control.', 11, color=MUTED).pack(anchor='w', pady=(5, 0))
        ttk.Button(header, text='+  New download', style='Primary.TButton',
                   command=self.add_dialog).pack(side='right', pady=5)
        options = ttk.Menubutton(header, text='App ▾')
        options.pack(side='right', padx=8)
        menu = tk.Menu(options, tearoff=False, bg=SURFACE, fg=INK)
        menu.add_command(label='Keep running in background', command=self.hide)
        self.autostart = tk.BooleanVar(value=autostart_enabled())
        menu.add_checkbutton(label='Start in background at login', variable=self.autostart,
                             command=self.toggle_autostart)
        menu.add_separator()
        menu.add_command(label='Quit LinuxDM', command=self.close)
        options.configure(menu=menu)
        stats = tk.Frame(main, bg=BG)
        stats.grid(row=1, column=0, sticky='ew', pady=(14, 12))
        self.stats = {}
        for i, (key, caption) in enumerate((('speed', 'TOTAL SPEED'), ('active', 'ACTIVE'), ('queue', 'IN QUEUE'))):
            stats.columnconfigure(i, weight=1, uniform='cards')
            card = tk.Frame(stats, bg=SURFACE, highlightbackground=BORDER, highlightthickness=1, padx=12, pady=9)
            card.grid(row=0, column=i, sticky='ew', padx=(0 if i == 0 else 6, 0 if i == 2 else 6))
            self.label(card, caption, 9, MUTED, True).pack(anchor='w')
            self.stats[key] = self.label(card, '—', 17, ACCENT if key == 'speed' else INK, True)
            self.stats[key].pack(anchor='w', pady=(5, 0))
        toolbar = tk.Frame(main, bg=BG)
        toolbar.grid(row=2, column=0, sticky='ew', pady=(0, 12))
        self.heading = self.label(toolbar, 'All downloads', 12, bold=True)
        self.heading.pack(side='left')
        self.search = tk.StringVar()
        self.search_entry = ttk.Entry(toolbar, textvariable=self.search, width=20)
        self.search_entry.pack(side='right')
        self.label(toolbar, 'Search files  ', 11, MUTED).pack(side='right')
        self.search.trace_add('write', lambda *_: self.render())
        table = tk.Frame(main, bg=SURFACE, highlightbackground=BORDER, highlightthickness=1)
        table.grid(row=3, column=0, sticky='nsew')
        columns = ('name', 'status', 'progress', 'downloaded', 'size', 'speed')
        self.tree = ttk.Treeview(table, columns=columns, show='headings', selectmode='extended')
        for col, title, width in zip(columns, ('FILE NAME', 'STATUS', 'PROGRESS', 'DOWNLOADED', 'TOTAL SIZE', 'SPEED'), (220, 94, 70, 98, 90, 92)):
            self.tree.heading(col, text=title, anchor='w')
            self.tree.column(col, width=width, minwidth=65, stretch=col == 'name', anchor='w')
        scroll = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.tree.pack(fill='both', expand=True)
        for status, color in (('Downloading', ACCENT), ('Complete', '#92b78b'), ('Paused', '#c0b492'),
                              ('Pausing', '#c0b492'), ('Error', '#ed9292')):
            self.tree.tag_configure(status, foreground=color)
        self.tree.bind('<Button-3>', self.context_menu)
        self.tree.bind('<Shift-F10>', self.context_menu)
        self.tree.bind('<<TreeviewSelect>>', lambda _: self.update_details())
        self.tree.bind('<Control-a>', self.select_all_downloads)
        self.tree.bind('<Control-A>', self.select_all_downloads)
        self.tree.bind('<Delete>', lambda _: self.action('remove'))
        self.empty = tk.Frame(table, bg=SURFACE)
        self.label(self.empty, '↓', 22, ACCENT).pack()
        self.empty_title = self.label(self.empty, 'Ready when you are', 14, bold=True)
        self.empty_title.pack(pady=(5, 7))
        self.empty_hint = self.label(self.empty, 'Add a download link to get started.', 11, MUTED)
        self.empty_hint.pack()
        self.empty_add = ttk.Button(self.empty, text='+  New download', command=self.add_dialog)
        self.empty_add.pack(pady=(16, 0))
        actions = tk.Frame(main, bg=BG)
        actions.grid(row=4, column=0, sticky='ew', pady=8)
        self.pause_button = ttk.Button(actions, text='Ⅱ  Pause', command=lambda: self.action('pause'))
        self.pause_button.pack(side='left')
        self.resume_button = ttk.Button(actions, text='▶  Resume', style='Primary.TButton', command=lambda: self.action('resume'))
        self.resume_button.pack(side='left', padx=8)
        self.remove_button = ttk.Button(actions, text='Remove selected', command=lambda: self.action('remove'))
        self.remove_button.pack(side='left')
        self.move_menu = tk.Menu(self.root, tearoff=False, bg=SURFACE, fg=INK,
                                 activebackground='#403923', activeforeground=ACCENT)
        self.pause_all = ttk.Button(actions, text='Pause all', command=lambda: self.action('pause', True))
        self.pause_all.pack(side='right')
        self.resume_all = ttk.Button(actions, text='Resume all', command=lambda: self.action('resume', True))
        self.resume_all.pack(side='right', padx=8)
        self.clear_button = ttk.Button(actions, text='Clear completed', command=self.clear_completed)
        self.clear_button.pack(side='right', padx=(8, 0))
        detail = tk.Frame(main, bg=SURFACE, highlightbackground=BORDER, highlightthickness=1, padx=12, pady=9)
        detail.grid(row=5, column=0, sticky='ew')
        self.detail_title = self.label(detail, 'Select a download', 12, bold=True, anchor='w')
        self.detail_title.pack(fill='x')
        self.detail_text = self.label(detail, 'Its progress and destination will appear here.', 11, MUTED,
                                      anchor='w', justify='left', wraplength=740)
        self.detail_text.pack(fill='x', pady=(4, 7))
        detail.bind('<Configure>', lambda event: [widget.configure(wraplength=max(180, event.width - 30))
                    for widget in (self.detail_text, self.detail_hint)])
        self.progress = ttk.Progressbar(detail, mode='determinate', maximum=100)
        self.progress.pack(fill='x')
        self.detail_hint = self.label(detail, 'Pause and resume controls apply to the selected rows.', 10, MUTED,
                                     anchor='w', justify='left', wraplength=740)
        self.detail_hint.pack(fill='x', pady=(8, 0))
        footer = tk.Frame(main, bg=BG)
        footer.grid(row=6, column=0, sticky='ew', pady=(9, 0))
        self.footer = self.label(footer, 'Queue saved automatically', 10, MUTED)
        self.footer.pack(side='left')
        self.move_button = ttk.Menubutton(footer, text='Move to queue…', menu=self.move_menu)
        self.move_button.pack(side='left', padx=(12, 0))
        self.parallel = tk.StringVar(value=str(self.manager.parallel))
        ttk.Spinbox(footer, from_=1, to=8, width=3, textvariable=self.parallel,
                    command=self.set_parallel).pack(side='right')
        self.label(footer, 'Overall download limit  ', 10, MUTED).pack(side='right')
        self.parallel.trace_add('write', lambda *_: self.set_parallel())

    def select_all_downloads(self, _=None):
        rows = self.tree.get_children()
        self.tree.selection_set(rows)
        if rows:
            self.tree.focus(rows[0])
        self.update_details()
        return 'break'

    def toggle_autostart(self):
        try:
            set_autostart(self.autostart.get())
        except OSError as error:
            self.autostart.set(autostart_enabled())
            messagebox.showerror('Cannot update startup setting', str(error), parent=self.root)
            return
        self.footer.configure(text='LinuxDM will start hidden when you log in.' if self.autostart.get()
                              else 'Start at login is turned off.')

    def hide(self):
        self.root.withdraw()

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def context_menu(self, event):
        if getattr(event, 'num', None) == 3:
            row = self.tree.identify_row(event.y)
            if not row:
                return
            if row not in self.tree.selection():
                self.tree.selection_set(row)
            self.tree.focus(row)
        selected = set(self.tree.selection())
        jobs = [j for j in self.manager.snapshot() if j['id'] in selected]
        if not jobs:
            return
        if getattr(self, 'context_popup', None):
            self.context_popup.destroy()
        menu = self.context_popup = tk.Menu(self.root, tearoff=False, bg=SURFACE, fg=INK,
                       activebackground='#403923', activeforeground=ACCENT)
        for label, action, statuses in (
                ('Pause', 'pause', {'Queued', 'Downloading', 'Resuming'}),
                ('Resume', 'resume', {'Paused', 'Pausing', 'Error'})):
            menu.add_command(label=label, command=lambda a=action: self.action(a),
                             state='normal' if any(j['status'] in statuses for j in jobs) else 'disabled')
        menu.add_separator()
        menu.add_command(label='Open directory', command=self.open_directory)
        move = tk.Menu(menu, tearoff=False, bg=SURFACE, fg=INK)
        for queue in self.manager.queue_snapshot():
            move.add_command(label=queue['name'], command=lambda q=queue['id']: self.move_selected(q))
        menu.add_cascade(label='Move to queue', menu=move)
        menu.add_separator()
        menu.add_command(label='Remove', command=lambda: self.action('remove'))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def open_directory(self):
        selected = set(self.tree.selection())
        directories = {str(Path(j['target']).parent) for j in self.manager.snapshot() if j['id'] in selected}
        for directory in sorted(directories):
            try:
                if os.name == 'nt':
                    os.startfile(directory)
                    continue
                subprocess.Popen(['xdg-open', directory], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError as error:
                messagebox.showerror('Cannot open directory', str(error), parent=self.root)

    def set_parallel(self):
        try:
            value = int(self.parallel.get())
            if 1 <= value <= 8 and value != self.manager.parallel:
                self.manager.set_parallel(value)
        except ValueError:
            pass

    def set_filter(self, name):
        self.filter = name
        self.render()

    def select_queue(self, _=None):
        selected = self.queue_list.curselection()
        if selected:
            self.queue_filter = self.queue_ids[selected[0]]
            self.render()

    def toggle_queue(self):
        if self.queue_filter:
            queue = next(q for q in self.manager.queue_snapshot() if q['id'] == self.queue_filter)
            self.manager.pause_queue(queue['id'], not queue['paused'])
            self.jobs = self.manager.snapshot()
            self.render()

    def move_selected(self, queue_id):
        for job_id in self.tree.selection():
            self.manager.move_to_queue(job_id, queue_id)
        self.jobs = self.manager.snapshot()
        self.render()

    def manage_queues(self):
        if self.dialog and self.dialog.winfo_exists():
            self.dialog.lift()
            return
        dialog = self.dialog = tk.Toplevel(self.root)
        dialog.title('Manage queues')
        dialog.configure(bg=SURFACE)
        dialog.transient(self.root)
        dialog.resizable(False, False)
        body = tk.Frame(dialog, bg=SURFACE, padx=18, pady=18)
        body.pack(fill='both', expand=True)
        self.label(body, 'Named queues', 18, bold=True).pack(anchor='w')
        self.label(body, 'Group downloads and give each queue its own limit.', 11, MUTED).pack(anchor='w', pady=(4, 12))
        listing = tk.Listbox(body, height=6, width=48, bg=NAV, fg=INK, selectbackground='#403923',
                            selectforeground=ACCENT, exportselection=False, highlightthickness=0)
        listing.pack(fill='x')
        self.label(body, 'NAME', 10, MUTED, True).pack(anchor='w', pady=(12, 4))
        name = tk.StringVar()
        ttk.Entry(body, textvariable=name).pack(fill='x')
        limits = tk.Frame(body, bg=SURFACE)
        limits.pack(fill='x', pady=12)
        self.label(limits, 'Simultaneous downloads in this queue', 11).pack(side='left')
        count = tk.StringVar(value='2')
        ttk.Spinbox(limits, from_=1, to=8, width=3, textvariable=count).pack(side='right')
        controls = tk.Frame(body, bg=SURFACE)
        controls.pack(fill='x')
        queues = []

        def load(selected=None):
            queues[:] = self.manager.queue_snapshot()
            listing.delete(0, 'end')
            for q in queues:
                listing.insert('end', q['name'])
            index = next((i for i, q in enumerate(queues) if q['id'] == selected), 0)
            listing.selection_set(index)
            choose()
            self.jobs = self.manager.snapshot()
            self.render()

        def choose(_=None):
            selection = listing.curselection()
            if selection:
                queue = queues[selection[0]]
                name.set(queue['name'])
                count.set(str(queue['parallel']))
                delete.configure(state='disabled' if queue['id'] == 'default' else 'normal')

        def save(create=False):
            try:
                selected = listing.curselection()
                queue_id = None if create or not selected else queues[selected[0]]['id']
                queue_id = self.manager.save_queue(name.get(), int(count.get()), queue_id)
                load(queue_id)
            except (ValueError, OSError) as exc:
                messagebox.showerror('Cannot save queue', str(exc), parent=dialog)

        def remove():
            selected = listing.curselection()
            if selected:
                try:
                    self.manager.delete_queue(queues[selected[0]]['id'])
                    load()
                except (ValueError, OSError) as exc:
                    messagebox.showerror('Cannot delete queue', str(exc), parent=dialog)

        ttk.Button(controls, text='Create new', command=lambda: save(True)).pack(side='left')
        ttk.Button(controls, text='Save changes', style='Primary.TButton', command=save).pack(side='left', padx=8)
        delete = ttk.Button(controls, text='Delete queue', command=remove)
        delete.pack(side='right')
        self.label(body, 'To create a queue, enter a new name and click Create new.\nDeleting a queue moves its downloads to Default.',
                   10, MUTED, justify='left').pack(anchor='w', pady=(12, 8))
        ttk.Button(body, text='Done', command=dialog.destroy).pack(anchor='e')
        listing.bind('<<ListboxSelect>>', choose)
        dialog.bind('<Escape>', lambda _: dialog.destroy())
        load(self.queue_filter)
        self.queue_editor = {'name': name, 'count': count, 'create': lambda: save(True), 'save': save}
        dialog.grab_set()

    def matches(self, job):
        if self.queue_filter and job['queue_id'] != self.queue_filter:
            return False
        status = job['status']
        return (self.filter == 'All downloads'
                or self.filter == 'In progress' and status in ('Ready', 'Queued', 'Downloading', 'Resuming', 'Finishing', 'Removing')
                or self.filter == 'Paused' and status in ('Paused', 'Pausing')
                or self.filter == 'Completed' and status == 'Complete')

    def action(self, action, all_jobs=False):
        ids = [j['id'] for j in self.jobs if not self.queue_filter or j['queue_id'] == self.queue_filter] if all_jobs else self.tree.selection()
        for job_id in ids:
            getattr(self.manager, action)(job_id)
        self.jobs = self.manager.snapshot()
        self.render()

    def clear_completed(self):
        self.manager.clear_completed(self.queue_filter)
        self.jobs = self.manager.snapshot()
        self.render()

    def render(self):
        queues = self.manager.queue_snapshot()
        fingerprint = [(q['id'], q['name'], q['paused']) for q in queues]
        if fingerprint != self.queue_fingerprint:
            self.queue_fingerprint = fingerprint
            self.queue_ids = [None] + [q['id'] for q in queues]
            if self.queue_filter not in self.queue_ids:
                self.queue_filter = None
            self.queue_list.delete(0, 'end')
            self.queue_list.insert('end', 'All queues')
            self.move_menu.delete(0, 'end')
            for q in queues:
                self.queue_list.insert('end', ('Ⅱ ' if q['paused'] else '') + q['name'])
                self.move_menu.add_command(label=q['name'], command=lambda queue_id=q['id']: self.move_selected(queue_id))
        self.queue_list.selection_clear(0, 'end')
        self.queue_list.selection_set(self.queue_ids.index(self.queue_filter))
        current = next((q for q in queues if q['id'] == self.queue_filter), None)
        self.queue_toggle.configure(state='normal' if current else 'disabled',
                                    text='Resume queue' if current and current['paused'] else 'Pause queue')
        queue_title = (current['name'][:22] + '…' if len(current['name']) > 23 else current['name']) if current else ''
        self.heading.configure(text=f"{queue_title} · {self.filter}" if current else self.filter)
        for name, button in self.nav_buttons.items():
            button.configure(bg='#302b20' if name == self.filter else NAV,
                             fg=ACCENT if name == self.filter else MUTED)
        query = self.search.get().strip().casefold()
        visible = [j for j in self.jobs if self.matches(j) and query in Path(j['target']).name.casefold()]
        visible_ids = {j['id'] for j in visible}
        for item in self.tree.get_children():
            if item not in visible_ids:
                self.tree.delete(item)
        for index, j in enumerate(visible):
            progress = f"{min(100, 100 * j['done'] / j['total']):.0f}%" if j['total'] else '—'
            values = (Path(j['target']).name, j['status'], progress,
                      size(j['done']), size(j['total']) if j['total'] else '—',
                      size(j['speed']) + '/s' if j['speed'] else '—')
            if self.tree.exists(j['id']):
                self.tree.item(j['id'], values=values, tags=(j['status'],))
            else:
                self.tree.insert('', 'end', iid=j['id'], values=values, tags=(j['status'],))
            self.tree.move(j['id'], '', index)
        if visible:
            self.empty.place_forget()
        else:
            self.empty_title.configure(text='Ready when you are' if not self.jobs else 'No downloads here')
            self.empty_hint.configure(text='Add a download link to get started.' if not self.jobs
                                      else 'Try another filter or search.')
            self.empty.place(relx=.5, rely=.54, anchor='center')
        scope = [j for j in self.jobs if not self.queue_filter or j['queue_id'] == self.queue_filter]
        self.stats['speed'].configure(text=size(sum(j['speed'] for j in scope)) + '/s')
        self.stats['active'].configure(text=f"{sum(j['status'] in ('Downloading', 'Finishing') for j in scope):02}")
        self.stats['queue'].configure(text=f"{sum(j['status'] in ('Ready', 'Queued', 'Resuming') for j in scope):02}")
        self.footer.configure(text=f'{len(self.jobs)} downloads  ·  Queue saved automatically')
        self.pause_all.configure(state='normal' if any(j['status'] in ('Downloading', 'Queued', 'Resuming') for j in scope) else 'disabled')
        self.resume_all.configure(state='normal' if any(j['status'] in ('Paused', 'Pausing', 'Error') for j in scope) else 'disabled')
        self.clear_button.configure(state='normal' if any(j['status'] == 'Complete' for j in scope) else 'disabled')
        self.update_details()

    def update_details(self):
        selected = [j for j in self.jobs if j['id'] in self.tree.selection()]
        self.move_button.configure(state='normal' if selected else 'disabled')
        self.remove_button.configure(state='normal' if any(j['status'] != 'Removing' for j in selected) else 'disabled')
        self.pause_button.configure(state='normal' if any(j['status'] in ('Queued', 'Downloading', 'Resuming') for j in selected) else 'disabled')
        self.resume_button.configure(state='normal' if any(j['status'] in ('Paused', 'Pausing', 'Error') for j in selected) else 'disabled',
                                     text='↻  Retry' if selected and all(j['status'] == 'Error' for j in selected) else '▶  Resume')
        if not selected:
            self.detail_title.configure(text='Select a download')
            self.detail_text.configure(text='Its progress and destination will appear here.', fg=MUTED)
            self.detail_hint.configure(text='Remove clears queue entries and temporary data. Completed files stay on disk.')
            self.progress['value'] = 0
            return
        j = selected[0]
        self.detail_title.configure(text=Path(j['target']).name if len(selected) == 1 else f'{len(selected)} downloads selected')
        self.detail_text.configure(text=j['error'] or j['target'], fg='#ed9292' if j['error'] else MUTED)
        self.progress['value'] = min(100, 100 * j['done'] / j['total']) if j['total'] else 0
        hint = f"{size(j['done'])} of {size(j['total']) if j['total'] else 'unknown size'}"
        queue = next(q for q in self.manager.queue_snapshot() if q['id'] == j['queue_id'])
        hint += f"  ·  Queue: {queue['name']}" + (' (paused)' if queue['paused'] else '')
        if j['status'] == 'Ready':
            hint += '  ·  Waiting for your choice in the Chrome download dialog'
        elif j['status'] == 'Removing':
            hint += '  ·  Stopping connections and removing temporary data…'
        elif j['status'] == 'Pausing':
            hint += '  ·  Stopping connections… Resume can be requested now.'
        elif j['status'] == 'Resuming':
            hint += '  ·  Resume requested. Waiting for previous connections to stop…'
        elif j['status'] == 'Finishing':
            hint += '  ·  Saving the completed file…'
        elif j['status'] == 'Complete':
            hint += '  ·  Download complete'
        elif j.get('kind') == 'video':
            hint += '  ·  ' + j.get('video_phase', 'Streaming video')
        elif 'resumable' in j:
            hint += '  ·  Resume supported' if j['resumable'] else '  ·  This server requires restarting when resumed'
            if j['status'] == 'Downloading':
                hint += f"  ·  {j.get('used_connections', 1)} connections"
        self.detail_hint.configure(text=hint)

    def add_dialog(self, browser_job=None):
        if self.closing:
            return
        if self.dialog and self.dialog.winfo_exists():
            self.dialog.lift()
            return
        dialog = self.dialog = tk.Toplevel(self.root)
        dialog.title('Download from browser' if browser_job else 'New download')
        dialog.configure(bg=SURFACE)
        dialog.transient(self.root)
        dialog.resizable(False, False)
        body = tk.Frame(dialog, bg=SURFACE, padx=18, pady=18)
        body.pack(fill='both', expand=True)
        self.label(body, 'Download from browser' if browser_job else 'Add a download', 18, bold=True).pack(anchor='w')
        self.label(body, 'Choose where to save this file and when to start.' if browser_job
                   else 'Paste a direct link. We’ll take care of the queue.', 11, MUTED).pack(anchor='w', pady=(5, 16))
        self.label(body, 'DOWNLOAD URL', 10, MUTED, True).pack(anchor='w', pady=(0, 6))
        url = tk.StringVar(value=browser_job['url'] if browser_job else '')
        entry = ttk.Entry(body, textvariable=url, width=60)
        entry.pack(fill='x')
        selectors = tk.Frame(body, bg=SURFACE)
        selectors.pack(fill='x', pady=(12, 0))
        queue_options = self.manager.queue_snapshot()
        queue_field = tk.Frame(selectors, bg=SURFACE)
        queue_field.pack(side='left', fill='x', expand=True, padx=(0, 12))
        self.label(queue_field, 'QUEUE', 10, MUTED, True).pack(anchor='w')
        queue_choice = ttk.Combobox(queue_field, values=[q['name'] for q in queue_options], state='readonly', width=22)
        queue_choice.pack(fill='x', pady=(4, 0))
        default_queue = self.queue_filter or (browser_job['queue_id'] if browser_job else 'default')
        queue_choice.current(next(i for i, q in enumerate(queue_options) if q['id'] == default_queue))
        type_field = tk.Frame(selectors, bg=SURFACE)
        type_field.pack(side='right')
        self.label(type_field, 'DOWNLOAD TYPE', 10, MUTED, True).pack(anchor='w')
        kind = tk.StringVar(value='Streaming video' if browser_job and browser_job.get('kind') == 'video' else 'File')
        kind_choice = ttk.Combobox(type_field, textvariable=kind, values=['File', 'Streaming video'],
                                   state='disabled' if browser_job else 'readonly', width=18)
        kind_choice.pack(pady=(4, 0))
        filename = tk.StringVar(value=Path(browser_job['target']).name if browser_job else '')
        if browser_job:
            entry.configure(state='readonly')
            self.label(body, 'FILE NAME', 10, MUTED, True).pack(anchor='w', pady=(14, 6))
            ttk.Entry(body, textvariable=filename).pack(fill='x')
        self.label(body, 'CATEGORY', 10, MUTED, True).pack(anchor='w', pady=(12, 6))
        category = tk.StringVar(value='Automatic')
        category_choice = ttk.Combobox(body, textvariable=category,
                                      values=['Automatic', *CATEGORIES], state='readonly')
        category_choice.pack(fill='x')
        self.label(body, 'SAVE TO', 10, MUTED, True).pack(anchor='w', pady=(18, 6))
        row = tk.Frame(body, bg=SURFACE)
        row.pack(fill='x')
        directory = tk.StringVar(value=str(Path(browser_job['target']).parent) if browser_job
                                 else suggested_directory(self.directory))
        last_suggestion = suggested_directory(self.directory, url.get(), filename.get(),
                                               'video' if kind.get() == 'Streaming video' else 'file')

        def suggest_folder(*_, force=False):
            nonlocal last_suggestion
            chosen = category.get()
            if chosen == 'Automatic':
                chosen = detect_category(url.get(), filename.get(),
                                         'video' if kind.get() == 'Streaming video' else 'file')
            proposed = category_directory(self.directory, chosen)
            # Editing the path or browsing to a folder overrides automatic suggestions.
            if force or directory.get() == last_suggestion:
                directory.set(proposed)
            last_suggestion = proposed

        url.trace_add('write', suggest_folder)
        filename.trace_add('write', suggest_folder)
        kind.trace_add('write', suggest_folder)
        category_choice.bind('<<ComboboxSelected>>', lambda _: suggest_folder(force=True))
        ttk.Entry(row, textvariable=directory).pack(side='left', fill='x', expand=True)

        def browse():
            path = filedialog.askdirectory(parent=dialog, initialdir=directory.get())
            if path:
                directory.set(path)

        ttk.Button(row, text='Browse…', command=browse).pack(side='right', padx=(8, 0))
        options = tk.Frame(body, bg=SURFACE)
        options.pack(fill='x', pady=(18, 6))
        self.label(options, 'Connections', 11).pack(side='left')
        connections = tk.StringVar(value=str(browser_job['connections'] if browser_job else self.connections))
        ttk.Spinbox(options, from_=1, to=16, width=4, textvariable=connections).pack(side='left', padx=(8, 20))
        self.label(options, 'Video quality', 11).pack(side='left')
        quality_labels = ['Best available', '1080p', '720p', '480p']
        quality_values = ['best', '1080', '720', '480']
        quality = ttk.Combobox(options, values=quality_labels, state='readonly', width=14)
        quality.current(quality_values.index(browser_job.get('quality', 'best') if browser_job else 'best'))
        quality.pack(side='right', padx=10)
        kind.trace_add('write', lambda *_: quality.configure(state='readonly' if kind.get() == 'Streaming video' else 'disabled'))
        quality.configure(state='readonly' if kind.get() == 'Streaming video' else 'disabled')
        self.label(body, 'Uses fewer connections when the file or server requires it.', 10, MUTED).pack(anchor='w')
        buttons = tk.Frame(body, bg=SURFACE)
        buttons.pack(fill='x', pady=(16, 0))

        def submit(_=None, start=True):
            try:
                count = int(connections.get())
                if not 1 <= count <= 16:
                    raise ValueError('Choose between 1 and 16 connections.')
                if not directory.get().strip():
                    raise ValueError('Choose a destination folder.')
                if browser_job:
                    job_id = browser_job['id']
                    self.manager.confirm(job_id, directory.get(), filename.get(), count, start=start,
                                         queue_id=queue_options[queue_choice.current()]['id'],
                                         quality=quality_values[quality.current()])
                else:
                    job_id = self.manager.add(url.get().strip(), directory.get(), count,
                                              queue_id=queue_options[queue_choice.current()]['id'],
                                              kind='video' if kind.get() == 'Streaming video' else 'file',
                                              quality=quality_values[quality.current()])
            except (ValueError, OSError) as exc:
                messagebox.showerror('Cannot add download', str(exc), parent=dialog)
                return
            self.connections = count
            self.queue_filter = queue_options[queue_choice.current()]['id']
            dialog.destroy()
            self.filter = 'All downloads'
            self.search.set('')
            self.jobs = self.manager.snapshot()
            self.render()
            self.tree.selection_set(job_id)
            self.tree.see(job_id)

        def dismiss():
            if browser_job:
                self.manager.defer(browser_job['id'])
            dialog.destroy()

        def discard():
            self.manager.remove(browser_job['id'])
            dialog.destroy()
            self.jobs = self.manager.snapshot()
            self.render()

        self.dialog_start = ttk.Button(buttons, text='Start download' if browser_job else 'Add to queue',
                                      style='Primary.TButton', command=submit)
        self.dialog_start.pack(side='right')
        if browser_job:
            self.dialog_later = ttk.Button(buttons, text='Download later', command=lambda: submit(start=False))
            self.dialog_later.pack(side='right', padx=8)
            self.dialog_discard = ttk.Button(buttons, text='Discard', command=discard)
            self.dialog_discard.pack(side='left')
        else:
            ttk.Button(buttons, text='Cancel', command=dismiss).pack(side='right', padx=8)
        self.dialog_fields = {'filename': filename, 'directory': directory, 'connections': connections,
                              'url': url, 'queue': queue_choice, 'quality': quality, 'kind': kind,
                              'category': category_choice}
        dialog.bind('<Return>', submit)
        dialog.bind('<Escape>', lambda _: dismiss())
        dialog.protocol('WM_DELETE_WINDOW', dismiss)
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - dialog.winfo_reqwidth()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - dialog.winfo_reqheight()) // 2
        dialog.geometry(f'+{max(0, x)}+{max(0, y)}')
        dialog.grab_set()
        if browser_job:
            self.root.deiconify()
            dialog.lift()
            self.dialog_start.focus_set()
        else:
            entry.focus_set()

    def refresh(self):
        if self.closing:
            return
        if consume_show(self.manager.root):
            self.show()
        imported = drain_inbox(self.manager,
                               lambda url, filename, kind: suggested_directory(self.directory, url, filename, kind),
                               self.connections, awaiting_confirmation=True)
        self.jobs = self.manager.snapshot()
        self.render()
        if imported:
            self.filter = 'All downloads'
            self.queue_filter = None
            self.search.set('')
            self.render()
            self.tree.selection_set(imported[-1])
            self.tree.see(imported[-1])
        if not self.dialog or not self.dialog.winfo_exists():
            waiting = next((j for j in self.jobs if j.get('needs_confirmation') and j['status'] == 'Ready'), None)
            if waiting:
                self.add_dialog(waiting)
        self.refresh_timer = self.root.after(300, self.refresh)

    def close(self):
        if self.closing:
            return
        self.closing = True
        if getattr(self, 'tray', None):
            self.tray.close()
        if self.refresh_timer is not None:
            self.root.after_cancel(self.refresh_timer)
            self.refresh_timer = None
        self.manager.close()
        self.footer.configure(text='Stopping downloads and saving the queue…')
        self._wait_for_close()

    def _wait_for_close(self):
        with self.manager.lock:
            active = bool(self.manager.active)
        if active:
            self.root.after(100, self._wait_for_close)
        else:
            self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description='LinuxDM desktop download manager')
    parser.add_argument('--background', action='store_true', help='Start with the window hidden')
    args = parser.parse_args()
    # Only one process may own the queue, including when Chrome starts the app.
    with AppInstance() as instance:
        if not instance.acquired:
            if not args.background:
                request_show()
            return
        root = tk.Tk(className='LinuxDM')
        if args.background:
            root.withdraw()  # Hide before constructing widgets to avoid a startup window flash.
        app = DownloadApp(root, DownloadManager())
        app.tray = TrayIcon(root, app.show, app.close)
        if app.tray.error:
            app.footer.configure(text='Tray unavailable. Open LinuxDM from the application menu to restore it.')
        try:
            root.mainloop()
        finally:
            app.tray.close()


if __name__ == '__main__':
    main()
