#!/usr/bin/env python

import datetime
import json
import os
import sqlite3
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView, QDialog, QLineEdit, QFormLayout,
    QTabWidget, QMessageBox, QTextEdit, QHBoxLayout
)

from PySide6.QtGui import QIcon

script_path = os.path.dirname(os.path.abspath(__file__))
icon_path = os.path.join(script_path, "edusn_logo")
DB_PATH = os.path.join(script_path, "timetable.db")
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

class AddClassDialog(QDialog):
    def __init__(self, day, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Add New Class for {day}")
        self.layout = QFormLayout(self)
        self.day = day

        self.name_input = QLineEdit(self)
        self.duration_input = QLineEdit(self)
        self.grade_input = QLineEdit(self)
        self.time_input = QLineEdit(self)

        self.layout.addRow("Class Name:", self.name_input)
        self.layout.addRow("Duration:", self.duration_input)
        self.layout.addRow("Grade:", self.grade_input)
        self.layout.addRow("Time:", self.time_input)

        buttons = QPushButton("OK")
        buttons.clicked.connect(self.accept)
        self.layout.addWidget(buttons)

    def get_data(self):
        return (
            self.name_input.text(),
            self.duration_input.text(),
            self.grade_input.text(),
            self.time_input.text(),
            self.day
        )

class LessonPlanDialog(QDialog):
    def __init__(self, class_id, day, initial_text, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Lesson Plan for {day}")
        self.resize(500, 400)
        self.class_id = class_id
        self.day = day
        self.layout = QVBoxLayout(self)

        self.text_editor = QTextEdit(self)
        self.text_editor.setText(initial_text)
        self.layout.addWidget(self.text_editor)

        save_button = QPushButton("Save Plan")
        save_button.clicked.connect(self.save_plan)
        self.layout.addWidget(save_button)

    def save_plan(self):
        plan_text = self.text_editor.toPlainText()
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT plan_text FROM lesson_plans WHERE class_id = ? AND day = ?", (self.class_id, self.day))
            existing_plan = cursor.fetchone()

            if existing_plan:
                conn.execute("UPDATE lesson_plans SET plan_text = ? WHERE class_id = ? AND day = ?",
                             (plan_text, self.class_id, self.day))
            else:
                conn.execute("INSERT INTO lesson_plans (class_id, day, plan_text) VALUES (?, ?, ?)",
                             (self.class_id, self.day, plan_text))
        self.accept()

class TimetableApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("My Class Timetable")
        self.resize(1000, 600)
        self.layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.layout.addWidget(self.tabs)

        self.tables = {}

        for day in WEEKDAYS:
            tab = QWidget()
            tab_layout = QVBoxLayout(tab)
            table = QTableWidget()
            tab_layout.addWidget(table)

            add_btn = QPushButton(f"Add New Class ({day})")
            add_btn.clicked.connect(lambda checked, d=day: self.add_class_dialog(d))
            tab_layout.addWidget(add_btn)

            self.tables[day] = table
            self.tabs.addTab(tab, day)
            table.cellClicked.connect(lambda r, c, d=day: self.handle_toggle(r, c, d))

        self.init_db()
        self.alter_table_add_columns()
        self.backup_if_monday()

        today = datetime.datetime.today().strftime('%A')
        self.tabs.setCurrentIndex(WEEKDAYS.index(today) if today in WEEKDAYS else 0)

        self.load_all_days()
        self.tabs.currentChanged.connect(self.load_current_day)

    def init_db(self):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS classes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                duration TEXT NOT NULL,
                lesson_prepared BOOLEAN NOT NULL DEFAULT 0,
                done BOOLEAN NOT NULL DEFAULT 0,
                classroom_created BOOLEAN NOT NULL DEFAULT 0,
                day TEXT NOT NULL DEFAULT 'Monday'
            )
            """)

            conn.execute("""
            CREATE TABLE IF NOT EXISTS class_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_class_id INTEGER,
                name TEXT,
                duration TEXT,
                grade TEXT,
                time TEXT,
                lesson_prepared BOOLEAN,
                done BOOLEAN,
                classroom_created BOOLEAN,
                day TEXT,
                backup_date TEXT DEFAULT (date('now'))
            )
            """)

            conn.execute("""
            CREATE TABLE IF NOT EXISTS lesson_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                class_id INTEGER,
                day TEXT,
                plan_text TEXT,
                FOREIGN KEY(class_id) REFERENCES classes(id)
            )
            """)

    def alter_table_add_columns(self):
        with sqlite3.connect(DB_PATH) as conn:
            try: conn.execute("ALTER TABLE classes ADD COLUMN grade TEXT DEFAULT ''")
            except sqlite3.OperationalError: pass
            try: conn.execute("ALTER TABLE classes ADD COLUMN time TEXT DEFAULT ''")
            except sqlite3.OperationalError: pass

    def backup_if_monday(self):
        today = datetime.datetime.today()
        today_str = today.strftime('%Y-%m-%d')
        is_monday = today.strftime('%A') == "Monday"
        prev_file = os.path.join(script_path, "previous_monday.json")

        if os.path.exists(prev_file):
            with open(prev_file, "r") as f:
                data = json.load(f)
                last_backup = data.get("last_backup", "")
        else:
            last_backup = ""

        if not is_monday or last_backup == today_str:
            return

        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute("""
                SELECT id, name, duration, grade, time, lesson_prepared, done, classroom_created, day
                FROM classes
            """).fetchall()

            for row in rows:
                conn.execute("""
                INSERT INTO class_history (original_class_id, name, duration, grade, time,
                                         lesson_prepared, done, classroom_created, day)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, row)

            conn.execute("""
            UPDATE classes
            SET lesson_prepared = 0,
                done = 0,
                classroom_created = 0
            """)

        with open(prev_file, "w") as f:
            json.dump({"last_backup": today_str}, f)

    def load_all_days(self):
        for day in WEEKDAYS:
            self.load_data(day)

    def load_current_day(self, index):
        self.load_data(WEEKDAYS[index])

    def load_data(self, day):
        table = self.tables[day]
        table.blockSignals(True)
        table.clear()

        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute("""
                SELECT c.id, c.name, c.duration, c.grade, c.time, c.lesson_prepared, c.done,
                       c.classroom_created, lp.plan_text
                FROM classes c
                LEFT JOIN lesson_plans lp ON c.id = lp.class_id AND c.day = lp.day
                WHERE c.day=?
            """, (day,)).fetchall()

        table.setColumnCount(8)
        table.setHorizontalHeaderLabels([
            "Class Name", "Duration", "Grade", "Time",
            "Prepared", "Done", "Classroom Created",
            "Lesson Plan", "Delete"
        ])
        table.setRowCount(len(rows))

        for row_idx, (id_, name, duration, grade, time_str, prepared, done, created, plan_text) in enumerate(rows):
            table.setItem(row_idx, 0, QTableWidgetItem(name))
            table.setItem(row_idx, 1, QTableWidgetItem(duration))
            table.setItem(row_idx, 2, QTableWidgetItem(grade))
            table.setItem(row_idx, 3, QTableWidgetItem(time_str))

            prep_item = QTableWidgetItem("✅" if prepared else "❌")
            prep_item.setTextAlignment(Qt.AlignCenter)
            prep_item.setData(Qt.UserRole, (id_, "lesson_prepared"))
            table.setItem(row_idx, 4, prep_item)

            done_item = QTableWidgetItem("✅" if done else "❌")
            done_item.setTextAlignment(Qt.AlignCenter)
            done_item.setData(Qt.UserRole, (id_, "done"))
            table.setItem(row_idx, 5, done_item)

            created_item = QTableWidgetItem("✅" if created else "❌")
            created_item.setTextAlignment(Qt.AlignCenter)
            created_item.setData(Qt.UserRole, (id_, "classroom_created"))
            table.setItem(row_idx, 6, created_item)

            lesson_plan_btn = QPushButton("📝 Edit Plan")
            lesson_plan_btn.clicked.connect(lambda _, i=id_, d=day, pt=plan_text: self.edit_lesson_plan(i, d, pt))
            table.setCellWidget(row_idx, 7, lesson_plan_btn)

            delete_button = QPushButton("🗑")
            delete_button.clicked.connect(lambda _, i=id_, d=day: self.delete_class(i, d))
            table.setCellWidget(row_idx, 8, delete_button)

        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(7, QHeaderView.Stretch)
        table.blockSignals(False)

    def handle_toggle(self, row, column, day):
        if column not in (4, 5, 6):
            return

        table = self.tables[day]
        item = table.item(row, column)
        if not item:
            return

        class_id, field = item.data(Qt.UserRole)
        current = item.text() == "✅"
        new_value = int(not current)

        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(f"UPDATE classes SET {field} = ? WHERE id = ?", (new_value, class_id))

        self.load_data(day)

    def edit_lesson_plan(self, class_id, day, initial_text):
        dialog = LessonPlanDialog(class_id, day, initial_text, self)
        if dialog.exec() == QDialog.Accepted:
            self.load_data(day)

    def delete_class(self, class_id, day):
        confirm = QMessageBox.question(self, "Confirm Delete", "Delete this class?", QMessageBox.Yes | QMessageBox.No)
        if confirm == QMessageBox.Yes:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("DELETE FROM classes WHERE id = ?", (class_id,))
                conn.execute("DELETE FROM lesson_plans WHERE class_id = ?", (class_id,))
            self.load_data(day)

    def add_class_dialog(self, day):
        dialog = AddClassDialog(day, self)
        if dialog.exec() == QDialog.Accepted:
            name, duration, grade, time_str, day = dialog.get_data()
            if name.strip() and duration.strip():
                with sqlite3.connect(DB_PATH) as conn:
                    conn.execute("""
                    INSERT INTO classes (name, duration, lesson_prepared, done,
                                         classroom_created, day, grade, time)
                    VALUES (?, ?, 0, 0, 0, ?, ?, ?)
                    """, (name.strip(), duration.strip(), day, grade.strip(), time_str.strip()))
                self.load_data(day)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(icon_path))
    window = TimetableApp()
    window.show()
    sys.exit(app.exec())
