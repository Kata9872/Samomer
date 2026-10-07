from datetime import date
import tkinter as tk
from tkinter import messagebox, ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from pydantic import ValidationError

from business_logic import DataError, Store


KINDS = {
    "boolean": "Выполнение",
    "counter": "Количество",
    "duration": "Длительность",
    "numeric": "Число",
    "scale": "Шкала",
}


def format_number(value):
    return f"{value:g}"


class Samomer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Самомер")
        self.geometry("850x650")
        self.minsize(550, 420)
        self.configure(bg="#f3f6f8")
        self.store = Store()

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TButton", padding=7)
        style.configure("TProgressbar", troughcolor="#e2e8f0", background="#0f766e")

        header = ttk.Frame(self, padding=18)
        header.pack(fill="x")
        ttk.Label(header, text="Самомер", font=("Segoe UI", 22, "bold")).pack(side="left")
        ttk.Button(header, text="Создать трекер", command=self.create_window).pack(side="right")

        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        self.canvas = tk.Canvas(outer, bg="#f3f6f8", highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.cards = ttk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.cards, anchor="nw", tags="cards")
        self.cards.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure("cards", width=event.width))
        self.refresh()

    def perform(self, button, action):
        button.configure(state="disabled")
        try:
            action()
        except (ValueError, ValidationError, DataError) as exc:
            messagebox.showerror("Не удалось выполнить действие", str(exc), parent=self)
        finally:
            if button.winfo_exists():
                button.configure(state="normal")

    def refresh(self):
        for child in self.cards.winfo_children():
            child.destroy()
        try:
            trackers = self.store.get_trackers()
        except DataError as exc:
            ttk.Label(self.cards, text=str(exc), wraplength=650, foreground="#b91c1c").pack(pady=25)
            return
        if not trackers:
            ttk.Label(self.cards, text="Начните с одной цели", font=("Segoe UI", 16, "bold")).pack(pady=(55, 8))
            ttk.Label(self.cards, text="Создайте первый трекер, чтобы увидеть прогресс.").pack()
            return
        for tracker in trackers:
            box = ttk.LabelFrame(self.cards, text=f"{tracker['name']} · {KINDS[tracker['type']]}", padding=15)
            box.pack(fill="x", pady=7)
            period = "Сегодня" if tracker["period"] == "daily" else "Эта неделя"
            caption = f"{period}: {format_number(tracker['current_value'])} / {format_number(tracker['period_target'])} {tracker['unit']}"
            ttk.Label(box, text=caption, font=("Segoe UI", 11)).pack(anchor="w")
            ttk.Progressbar(box, value=tracker["completion_percent"], maximum=100).pack(fill="x", pady=(8, 2))
            ttk.Label(box, text=f"{format_number(tracker['completion_percent'])}% выполнено").pack(anchor="w")

            buttons = ttk.Frame(box)
            buttons.pack(fill="x", pady=(10, 0))
            tracker_id = tracker["id"]
            if tracker["type"] in ("boolean", "counter"):
                button = ttk.Button(buttons, text="Выполнено" if tracker["type"] == "boolean" else "+1")
                button.configure(command=lambda b=button, i=tracker_id: self.perform(b, lambda: self.save_log(i, 1)))
                button.pack(side="left")
            else:
                value = ttk.Entry(buttons, width=12)
                value.pack(side="left", padx=(0, 8))
                ttk.Label(buttons, text=tracker["unit"]).pack(side="left", padx=(0, 8))
                button = ttk.Button(buttons, text="Добавить")
                button.configure(command=lambda b=button, i=tracker_id, e=value: self.perform(b, lambda: self.save_log(i, e.get())))
                button.pack(side="left")
            stats_button = ttk.Button(buttons, text="Статистика")
            stats_button.configure(command=lambda b=stats_button, i=tracker_id: self.perform(b, lambda: self.stats_window(i)))
            stats_button.pack(side="right")

    def save_log(self, tracker_id, value):
        self.store.add_log(tracker_id, value, date.today().isoformat())
        self.refresh()

    def create_window(self):
        window = tk.Toplevel(self)
        window.title("Создать трекер")
        window.geometry("400x370")
        window.transient(self)
        window.grab_set()
        frame = ttk.Frame(window, padding=20)
        frame.pack(fill="both", expand=True)
        entries = {}
        for row, (label, field) in enumerate((("Название", "name"), ("Тип", "type"), ("Цель", "target_value"), ("Период", "period"), ("Единица", "unit"))):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=8)
            if field == "type":
                widget = ttk.Combobox(frame, state="readonly", values=list(KINDS), width=21)
                widget.set("counter")
            elif field == "period":
                widget = ttk.Combobox(frame, state="readonly", values=("daily", "weekly"), width=21)
                widget.set("daily")
            else:
                widget = ttk.Entry(frame, width=24)
            widget.grid(row=row, column=1, sticky="ew", padx=(10, 0), pady=8)
            entries[field] = widget
        ttk.Label(frame, text="Для weekly цель задаётся на один день\nи умножается на 7 для недельного прогресса.", foreground="#475569").grid(row=5, column=0, columnspan=2, sticky="w", pady=10)
        button = ttk.Button(frame, text="Создать")

        def submit():
            self.store.create_tracker(*(entries[field].get() for field in ("name", "type", "target_value", "period", "unit")))
            window.destroy()
            self.refresh()

        button.configure(command=lambda: self.perform(button, submit))
        button.grid(row=6, column=1, sticky="e", pady=10)
        entries["name"].focus_set()

    def stats_window(self, tracker_id):
        stats = self.store.get_stats(tracker_id)
        window = tk.Toplevel(self)
        window.title(f"Статистика — {stats['name']}")
        window.geometry("760x700")
        window.transient(self)
        frame = ttk.Frame(window, padding=15)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=stats["name"], font=("Segoe UI", 16, "bold")).pack(anchor="w")
        streak = f"Серия: {stats['streak']} дн." if stats["streak"] is not None else "Недельная серия не рассчитывается"
        ttk.Label(frame, text=f"Выполнение: {format_number(stats['completion_percent'])}% · {streak}").pack(anchor="w", pady=8)

        figure = Figure(figsize=(6.5, 3), dpi=90)
        plot = figure.add_subplot(111)
        dates = [item["date"] for item in stats["by_date"]]
        values = [item["value"] for item in stats["by_date"]]
        plot.plot(dates, values, marker="o", color="#0f766e")
        plot.set_xlabel("Дата")
        plot.set_ylabel(stats["unit"])
        plot.tick_params(axis="x", labelrotation=35)
        figure.tight_layout()
        chart = FigureCanvasTkAgg(figure, master=frame)
        chart.draw()
        chart.get_tk_widget().pack(fill="both", expand=True)

        ttk.Label(frame, text="История записей", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(12, 4))
        history = ttk.Treeview(frame, columns=("date", "value"), show="headings", height=7)
        history.heading("date", text="Дата")
        history.heading("value", text=f"Значение ({stats['unit']})")
        for item in stats["history"]:
            history.insert("", "end", values=(item["date"], format_number(item["value"])))
        history.pack(fill="both", expand=True)


if __name__ == "__main__":
    try:
        Samomer().mainloop()
    except DataError as exc:
        messagebox.showerror("Ошибка базы данных", str(exc))
