import cmd
import argparse
import locale
import logging
from threading import Thread, Event
from signal import pause

import zmq

from ..terminal import TerminalApplication


class PiWheelsMaster(TerminalApplication):
    def main(self, args):


main = PiWheelsMaster()
