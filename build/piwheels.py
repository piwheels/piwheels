import pip
import os

packages = ['gpiozero', 'pigpio', 'rpi.gpio']

wc = pip.commands.WheelCommand()

def main():
    for package in packages:
        module_dir = "wheels/{}".format(package)
        if not os.path.exists(module_dir):
            os.makedirs(module_dir)
        wheel_dir = "--wheel-dir={}".format(module_dir)
        wc.main([wheel_dir, package])

if __name__ == '__main__':
    main()
