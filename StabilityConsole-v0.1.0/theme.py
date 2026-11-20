"""Shared Matrix-inspired presentation. No network, storage or animation."""
import tkinter as tk
from tkinter import ttk

BG = '#080d0b'
PANEL = '#0e1913'
FIELD = '#14231b'
SIDEBAR = '#0b130f'
BORDER = '#284233'
ACCENT = '#63f5a4'
ACCENT_HOVER = '#a1ffcb'
FG = '#e2efe7'
MUTED = '#9bb3a4'
SELECT = '#205139'
BUTTON = '#173b29'
HOVER = '#24563c'
DISABLED = '#728e7d'


def apply_theme(root):
    """Cover ttk states, native Tk fields and the combobox popup together."""
    root.option_add('*Font', ('Segoe UI', 10))
    for name, value in {
        '*Entry.background': FIELD, '*Entry.foreground': FG,
        '*Entry.readonlyBackground': FIELD, '*Entry.disabledBackground': PANEL,
        '*Entry.insertBackground': ACCENT, '*Entry.relief': 'flat',
        '*Entry.highlightThickness': 1, '*Entry.highlightBackground': BORDER,
        '*Entry.highlightColor': ACCENT,
        '*Entry.selectBackground': SELECT, '*Entry.selectForeground': FG,
        '*Text.insertBackground': ACCENT, '*Text.selectBackground': SELECT,
        '*Text.selectForeground': FG, '*Text.highlightThickness': 1,
        '*Text.highlightBackground': BORDER, '*Text.highlightColor': ACCENT,
        '*Text.relief': 'flat', '*Text.padX': 10, '*Text.padY': 8,
        '*Listbox.selectForeground': FG, '*Listbox.highlightThickness': 1,
        '*Listbox.highlightBackground': BORDER, '*Listbox.highlightColor': ACCENT,
        '*Listbox.selectBorderWidth': 0, '*Listbox.exportSelection': False,
        '*Checkbutton.activeBackground': BG, '*Checkbutton.activeForeground': ACCENT,
        '*Checkbutton.highlightThickness': 0, '*Checkbutton.selectColor': FIELD,
        '*Spinbox.relief': 'flat', '*Spinbox.buttonBackground': BUTTON,
        '*Spinbox.insertBackground': ACCENT, '*Spinbox.readonlyBackground': FIELD,
        '*Spinbox.highlightThickness': 1, '*Spinbox.highlightBackground': BORDER,
        '*Spinbox.highlightColor': ACCENT,
        '*Spinbox.selectBackground': SELECT, '*Spinbox.selectForeground': FG,
        '*TCombobox*Listbox.background': FIELD, '*TCombobox*Listbox.foreground': FG,
        '*TCombobox*Listbox.selectBackground': SELECT,
        '*TCombobox*Listbox.selectForeground': FG,
    }.items():
        root.option_add(name, value)
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', background=BG, foreground=FG, font=('Segoe UI', 10),
                    bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                    focuscolor=ACCENT)
    style.configure('TFrame', background=BG)
    style.configure('TNotebook', background=BG, borderwidth=0, tabmargins=(0, 4, 0, 8))
    style.configure('TNotebook.Tab', background=PANEL, foreground=MUTED,
                    padding=(14, 10), font=('Segoe UI', 10), borderwidth=0)
    style.map('TNotebook.Tab', background=[('selected', SELECT), ('active', FIELD)],
              foreground=[('selected', ACCENT), ('active', FG)],
              padding=[('selected', (14, 10)), ('!selected', (14, 10))])
    # The outer notebook keeps the existing page-selection API; navigation lives left.
    style.layout('Shell.TNotebook.Tab', [])
    style.configure('Shell.TNotebook', background=BG, borderwidth=0, tabmargins=0)
    style.configure('Treeview', background=PANEL, foreground=FG,
                    fieldbackground=PANEL, rowheight=34, borderwidth=0,
                    font=('Segoe UI', 10))
    style.map('Treeview', background=[('selected', SELECT)], foreground=[('selected', FG)])
    style.configure('Treeview.Heading', background=FIELD, foreground=MUTED,
                    font=('Segoe UI', 9, 'bold'), padding=(10, 10), relief='flat')
    style.map('Treeview.Heading', background=[('active', BUTTON)], foreground=[('active', ACCENT)])
    style.configure('TCombobox', fieldbackground=FIELD, background=FIELD, foreground=FG,
                    arrowcolor=ACCENT, padding=7, bordercolor=BORDER, selectbackground=SELECT,
                    selectforeground=FG)
    style.map('TCombobox', fieldbackground=[('readonly', FIELD), ('disabled', PANEL)],
              foreground=[('disabled', DISABLED), ('readonly', FG)],
              background=[('readonly', FIELD)], bordercolor=[('focus', ACCENT)])
    for direction in ('Vertical', 'Horizontal'):
        name = direction+'.TScrollbar'
        style.configure(name, background=BORDER, troughcolor=BG, arrowcolor=MUTED,
                        borderwidth=0, arrowsize=12, gripcount=0)
        style.map(name, background=[('active', SELECT), ('pressed', HOVER)])
    return style


def button(parent, text, command, primary=False):
    background = ACCENT if primary else BUTTON
    foreground = BG if primary else FG
    hover = ACCENT_HOVER if primary else HOVER
    widget = tk.Button(parent, text=text, command=command, bg=background, fg=foreground,
                       activebackground=hover, activeforeground=foreground,
                       disabledforeground=DISABLED, relief='flat', borderwidth=0,
                       highlightthickness=1, highlightbackground=BORDER,
                       highlightcolor=ACCENT, padx=13, pady=9,
                       font=('Segoe UI', 10, 'bold'), cursor='hand2', takefocus=True)
    widget.bind('<Enter>', lambda _: widget.configure(bg=hover) if str(widget['state'])!='disabled' else None)
    widget.bind('<Leave>', lambda _: widget.configure(bg=background))
    return widget


def stripe_rows(tree):
    tree.tag_configure('alternate', background='#111f17')
    for index, row in enumerate(tree.get_children()):
        tags = tuple(tag for tag in tree.item(row, 'tags') if tag != 'alternate')
        tree.item(row, tags=tags+(('alternate',) if index % 2 else ()))


def wrap_labels(parent):
    """Keep explanatory text within its page when the workspace is resized."""
    for widget in parent.winfo_children():
        if isinstance(widget, tk.Label):
            text = str(widget.cget('text'))
            if widget.cget('wraplength') or len(text) > 90:
                widget.configure(anchor='w',justify='left')
                widget.bind('<Configure>', lambda event: event.widget.configure(
                    wraplength=max(180, event.width-24)), add='+')
        wrap_labels(widget)
