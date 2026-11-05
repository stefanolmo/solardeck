"""Regenerates the README images in docs/ (runs offscreen, no inverter needed):

    QT_QPA_PLATFORM=offscreen python3 docs/make_screenshots.py
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtGui import QColor, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from solardeck import __version__, simulator, theme  # noqa: E402
from solardeck.config import Config  # noqa: E402
from solardeck.mainwindow import MainWindow  # noqa: E402
from solardeck.settings_dialog import SettingsDialog  # noqa: E402
from solardeck.splash import SplashScreen  # noqa: E402

app = QApplication([])
app.setStyleSheet(theme.STYLESHEET)


def pump(seconds):
    t = time.time()
    while time.time() - t < seconds:
        app.processEvents()
        time.sleep(0.01)


# 1) splash (frozen at the moment the whole curve is drawn), transparent corners
s = SplashScreen(__version__)
s.show()
s.set_time(2300)
pm = QPixmap(s.size())
pm.fill(QColor(0, 0, 0, 0))
s.render(pm)
pm.save(os.path.join(HERE, "splash.png"))
s.close()

# 2) main window against the built-in simulator (midday, exporting)
sim = simulator.SimulatedSolarEdge(start_hour=12.5).start()
w = MainWindow(qs=QSettings(os.path.join(HERE, ".shot.ini"), QSettings.IniFormat), sim=sim)
w.resize(1400, 900)
w.show()
pump(3.0)
w.grab().save(os.path.join(HERE, "main.png"))

# 3) settings window
dlg = SettingsDialog(Config(host="192.168.1.50", poll_interval=5), w, simulated=False)
dlg.show()
pump(0.3)
dlg.grab().save(os.path.join(HERE, "settings.png"))
dlg.close()
w.close()
sim.stop()
os.remove(os.path.join(HERE, ".shot.ini")) if os.path.exists(os.path.join(HERE, ".shot.ini")) else None
print("ok")
