import logging
import subprocess
import xmlrpc.client as xmlrpclib


class PiWheelsHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        self.log.append(msg)

    def reset(self):
        self.log = []


def list_pypi_packages():
    client = xmlrpclib.ServerProxy('https://pypi.python.org/pypi')
    return sorted(client.list_packages())

def bash_dush(path):
    du = subprocess.Popen(['du', '-sh', path], stdout=subprocess.PIPE)
    output = du.communicate()[0].split()
    return output[0].decode('UTF-8') + 'B'

def bash_dfh(path='/'):
    df = subprocess.Popen(['df', '-h', path], stdout=subprocess.PIPE)
    output = df.communicate()[0].split()
    return output[11].decode('UTF-8')
