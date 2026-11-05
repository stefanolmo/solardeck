import argparse
import os
import signal
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

from . import __version__, theme
from .mainwindow import APP_NAME, MainWindow
from .splash import SplashScreen


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="solardeck", description="SolarEdge HD-Wave monitor over Modbus TCP")
    ap.add_argument("--sim", action="store_true", help="connect to a built-in simulated inverter (no hardware needed)")
    ap.add_argument("--sim-hour", type=float, metavar="H", help="simulated hour of the day at start (default: now)")
    ap.add_argument("--screenshot", metavar="PNG", help="(development) save a screenshot and exit")
    ap.add_argument("--no-splash", action="store_true", help="do not show the splash screen")
    args = ap.parse_args(argv)

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName("solardeck")
    icon_path = os.path.join(os.path.dirname(__file__), "solardeck.svg")    # shipped inside the package
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    app.setStyleSheet(theme.STYLESHEET)
    f = QFont(app.font())
    f.setPointSize(10)
    app.setFont(f)
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    sim = None
    if args.sim or args.screenshot:
        from .simulator import SimulatedSolarEdge
        sim = SimulatedSolarEdge(start_hour=args.sim_hour if args.sim_hour is not None else (12.5 if args.screenshot else None)).start()

    w = MainWindow(sim=sim)
    use_splash = (w.cfg.show_splash and not (args.no_splash or args.screenshot or os.environ.get("SOLARDECK_NO_SPLASH")))
    splash = None
    if use_splash:
        splash = SplashScreen(__version__)     # 3 s; shown first, the main window is prepared behind it
        splash.start()
        app.processEvents()
    if splash is None:
        w.show()
    else:
        splash.finished.connect(w.show)
        splash.finished.connect(w.raise_)
    if args.screenshot:
        QTimer.singleShot(int(os.environ.get("SOLARDECK_SHOT_DELAY", "3500")),
                          lambda: (w.grab().save(args.screenshot), w.close(), app.quit()))
        w.show()
    rc = app.exec()
    if sim is not None:
        sim.stop()
    return rc


if __name__ == "__main__":
    sys.exit(main())
