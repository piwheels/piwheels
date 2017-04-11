from glob import glob
import os
import better_exceptions

temp_dir = '/tmp/piwheels'
web_dir = '/var/www/html'

wheels = glob('{}/*'.format(temp_dir))

for wheel in wheels:
    wheel_filename = wheel.split('/')[-1]
    package = '-'.join(wheel_filename.split('-')[:-4])
    web_wheel_dir = '{}/{}'.format(web_dir, package)
    if not os.path.exists(web_wheel_dir):
        os.makedirs(web_wheel_dir)

    final_wheel_path = '{}/{}/{}'.format(
        web_dir, package, wheel_filename
    )
    os.rename(wheel, final_wheel_path)
