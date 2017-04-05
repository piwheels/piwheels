import pip
import os
import xmlrpc.client as xmlrpclib

#packages = ['gpiozero', 'pigpio', 'rpi.gpio', 'numpy']

client = xmlrpclib.ServerProxy('https://pypi.python.org/pypi')
packages = client.list_packages()

wc = pip.commands.WheelCommand()

def main():
    for package in packages[:10]:
        module_dir = "wheels/{}".format(package)
        if not os.path.exists(module_dir):
            os.makedirs(module_dir)
        wheel_dir = "--wheel-dir={}".format(module_dir)
        no_deps = "--no-deps"
        wc.main([wheel_dir, no_deps, package])

if __name__ == '__main__':
    main()
